"""기록 가져오기 요청을 본문을 받기 전에 · 받는 동안 거른다 (F-002, 1차 R2-1 · R2-6, 2차 R2 반영).

FastAPI는 업로드 본문을 끝까지 받아 임시 파일에 쓴 다음에야 로그인 확인(의존성)과 엔드포인트를 부른다.
그래서 이 경로는 그보다 앞에서 도는 ASGI 미들웨어가 지킨다.
0. (모든 요청) 경로에 제어 문자(줄바꿈 등)가 있으면 본문을 읽지 않고 400.
   라우터의 경로 비교는 끝 줄바꿈을 무시해서 "/api/notes/import\\n"이 가져오기로 들어가는데,
   그런 주소로 이 가드를 비켜 가지 못하게 한다(2차 R2).
1. 세션 쿠키가 없거나 서명 · 만료가 틀리면 본문을 읽지 않고 401. (DB에 사용자가 있는지는 get_current_user가 본다)
2. Content-Length 머리말이 상한을 넘으면 본문을 읽지 않고 413.
3. 머리말이 없거나 거짓이어도, 실제로 받은 바이트를 세다 상한을 넘는 순간 413으로 끊는다.
   (FastAPI는 본문을 읽다 난 HTTPException을 그대로 응답으로 바꾼다.)
"""

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.deps import (
    AUTH_NOT_CONFIGURED_DETAIL,
    LOGIN_REQUIRED_DETAIL,
    SESSION_EXPIRED_DETAIL,
    get_settings,
)
from app.config import BYTES_PER_MB, MAX_IMPORT_REQUEST_BYTES, MAX_IMPORT_TOTAL_BYTES, SESSION_COOKIE_NAME
from app.services.auth_service import SessionConfigError, verify_session_token

# app/main.py의 "/api" + app/api/notes.py의 "/notes" + "/import". 경로가 바뀌면 tests/test_import_markdown.py가 잡는다.
IMPORT_PATH = "/api/notes/import"
TOO_LARGE_DETAIL = f"한 번에 올릴 수 있는 용량({MAX_IMPORT_TOTAL_BYTES // BYTES_PER_MB}MB)을 넘었어요."
BAD_PATH_DETAIL = "잘못된 주소예요."


def _route_path(scope: Scope) -> str:
    """라우터가 비교하는 경로와 같은 기준: 앞에 붙은 root_path(배포 때 하위 경로)를 뗀 경로."""
    path: str = scope["path"]
    root_path: str = scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        return path[len(root_path) :] or "/"
    return path


def _has_control_character(path: str) -> bool:
    return any(ord(character) < 0x20 or ord(character) == 0x7F for character in path)


class ImportUploadGuard:
    """모든 HTTP 요청의 경로를 먼저 보고, POST /api/notes/import에는 쿠키 · 크기 확인을 더 건다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if _has_control_character(scope["path"]):
            await _reply(scope, receive, send, status.HTTP_400_BAD_REQUEST, BAD_PATH_DETAIL)
            return

        if scope["method"] != "POST" or _route_path(scope) != IMPORT_PATH:
            await self.app(scope, receive, send)
            return

        rejection = _check_session_cookie(scope)
        if rejection is not None:
            await _reply(scope, receive, send, *rejection)
            return

        declared = HTTPConnection(scope).headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > MAX_IMPORT_REQUEST_BYTES:
            await _reply(scope, receive, send, status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE_DETAIL)
            return

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_IMPORT_REQUEST_BYTES:
                    raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=TOO_LARGE_DETAIL)
            return message

        await self.app(scope, counting_receive, send)


def _check_session_cookie(scope: Scope) -> tuple[int, str] | None:
    """쿠키가 없거나 서명 · 만료가 틀리면 (상태 코드, 문구). 통과면 None.

    설정은 엔드포인트의 get_current_user와 같은 곳(get_settings, 테스트에서 바꿔 끼운 것 포함)에서 읽는다.
    """
    token = HTTPConnection(scope).cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return status.HTTP_401_UNAUTHORIZED, LOGIN_REQUIRED_DETAIL
    app = scope.get("app")
    settings_provider = getattr(app, "dependency_overrides", {}).get(get_settings, get_settings)
    try:
        user_id = verify_session_token(token, settings_provider().session_secret)
    except SessionConfigError:
        return status.HTTP_500_INTERNAL_SERVER_ERROR, AUTH_NOT_CONFIGURED_DETAIL
    if user_id is None:
        return status.HTTP_401_UNAUTHORIZED, SESSION_EXPIRED_DETAIL
    return None


async def _reply(scope: Scope, receive: Receive, send: Send, status_code: int, detail: str) -> None:
    await JSONResponse(status_code=status_code, content={"detail": detail})(scope, receive, send)
