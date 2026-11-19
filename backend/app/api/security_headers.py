"""백엔드 응답 기본 보안 머리말 (D-032, F-016 1차 리뷰 R2).

백엔드(Vercel ②)의 주소는 화면이 넘기려면 공개여야 해서 직접 불릴 수 있다. 응답은 JSON이라 영향은 작지만 두 가지를 붙인다.
- 모든 응답: `X-Content-Type-Options: nosniff` — 브라우저가 파일 종류를 추측하지 않게.
- 로그인 쿠키가 실린 요청의 응답: `Cache-Control: no-store` — 개인 기록이 브라우저 · 중간 캐시에 남지 않게(응답이 이미 정했으면 그대로).
순수 ASGI라 본문을 건드리지 않는다(BaseHTTPMiddleware를 쓰지 않음).
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import SESSION_COOKIE_NAME


def _has_session_cookie(scope: Scope) -> bool:
    for name, value in scope.get("headers") or []:
        if name == b"cookie" and f"{SESSION_COOKIE_NAME}=".encode() in value:
            return True
    return False


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        signed_in = _has_session_cookie(scope)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                names = {name.lower() for name, _ in headers}
                if b"x-content-type-options" not in names:
                    headers.append((b"x-content-type-options", b"nosniff"))
                if signed_in and b"cache-control" not in names:
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
