"""샘플 체험 세션은 읽기만 한다 — 쓰기 · AI 호출을 라우터 앞에서 한 번에 막는다 (F-010, D-029).

- 기본이 '막기'다: 읽기 메서드(GET · HEAD · OPTIONS)가 아니면 모두 403. 허용은 ALLOWED_WRITES뿐이라,
  새 쓰기 API를 만들면서 깜빡해도 샘플로는 새지 않는다.
- GET이어도 무언가를 저장하는 경로(노션 연결 · 콜백 — 토큰 저장)는 BLOCKED_READS로 막는다. GET 경로를 새로 만들 때
  저장을 한다면 여기에 더한다(tests/test_sample_guard.py가 지금 목록을 확인).
- 샘플인지는 서명된 세션 토큰의 표시로 본다(auth_service.is_sample_session_token) — DB를 보지 않는다.
  쿠키가 없거나 틀린 요청은 그대로 넘겨 원래 로그인 확인(get_current_user · 업로드 가드)이 답하게 한다.
"""

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.deps import get_settings
from app.api.upload_limit import route_path
from app.config import SESSION_COOKIE_NAME
from app.services.auth_service import SessionConfigError, is_sample_session_token

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# 샘플 세션이 해도 되는 쓰기: 체험 끝내기(로그아웃) · 체험 다시 열기
ALLOWED_WRITES = frozenset({("POST", "/api/auth/logout"), ("POST", "/api/demo/session")})
# GET이지만 저장하는 경로
BLOCKED_READS = frozenset({"/api/notion/connect", "/api/notion/callback"})
SAMPLE_READ_ONLY_DETAIL = "샘플 체험에서는 바꿀 수 없어요. 구글로 로그인하면 내 기록으로 써 볼 수 있어요."


def is_blocked_for_sample(method: str, path: str) -> bool:
    if method in READ_METHODS:
        return path in BLOCKED_READS
    return (method, path) not in ALLOWED_WRITES


class SampleReadOnlyGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_blocked_for_sample(scope["method"], route_path(scope)):
            await self.app(scope, receive, send)
            return
        token = HTTPConnection(scope).cookies.get(SESSION_COOKIE_NAME)
        if token and _is_sample(scope, token):
            response = JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": SAMPLE_READ_ONLY_DETAIL})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _is_sample(scope: Scope, token: str) -> bool:
    # 설정은 get_current_user와 같은 곳(테스트에서 바꿔 끼운 것 포함)에서 읽는다 — 업로드 가드와 같은 방식
    app = scope.get("app")
    settings_provider = getattr(app, "dependency_overrides", {}).get(get_settings, get_settings)
    try:
        return is_sample_session_token(token, settings_provider().session_secret)
    except SessionConfigError:
        return False  # 설정이 틀리면 뒤의 로그인 확인이 500으로 답한다
