"""로그인 허용 목록 테스트 (F-015, D-031) — 공개 배포에서 허용한 이메일만 로그인하고, 나머지는 샘플 체험으로."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import LOGIN_ERROR_HEADER, NOT_ALLOWED_DETAIL, get_settings
from app.config import (
    OAUTH_STATE_COOKIE_NAME,
    SAMPLE_GOOGLE_SUB,
    SESSION_COOKIE_NAME,
    LoginConfigError,
    Settings,
    check_login_allowlist,
    check_login_allowlist_from_env,
    parse_email_list,
)
from app.db.models import User
from app.main import app
from app.services import auth_service
from app.services.auth_service import (
    GoogleProfile,
    create_session_token,
    get_or_create_google_user,
    is_login_allowed,
)

OWNER = "owner@example.com"


@pytest.fixture()
def allow_owner(client: TestClient, test_settings: Settings) -> Settings:
    """허용 목록에 본인만 둔 설정으로 바꿔 끼운다(conftest의 client가 끝날 때 되돌린다)."""
    settings = replace(test_settings, allowed_login_emails=frozenset({OWNER}))
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


def _google_callback(client: TestClient, profile: GoogleProfile):
    login = client.get("/api/auth/google/login", follow_redirects=False)
    state = login.cookies.get(OAUTH_STATE_COOKIE_NAME)
    assert state is not None
    client.cookies.set(OAUTH_STATE_COOKIE_NAME, state)
    with patch("app.api.auth.exchange_google_code_for_profile", new=AsyncMock(return_value=profile)):
        return client.get("/api/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)


def test_parse_email_list() -> None:
    assert parse_email_list(" Owner@Example.com, ,b@x.com ,") == frozenset({"owner@example.com", "b@x.com"})
    assert parse_email_list("") == frozenset()
    assert parse_email_list("\u212aim@x.com, a@x.com") == frozenset({"a@x.com"})  # ASCII가 아닌 항목은 뺌


def test_is_login_allowed(test_settings: Settings) -> None:
    open_settings = test_settings  # 목록이 비면 누구나(로컬 개발)
    assert is_login_allowed(open_settings, "anyone@example.com", email_verified=False)
    closed = replace(test_settings, allowed_login_emails=frozenset({OWNER}))
    assert is_login_allowed(closed, " OWNER@Example.com ", email_verified=True)  # 대소문자 · 앞뒤 빈칸 무시
    assert not is_login_allowed(closed, "other@example.com", email_verified=True)
    assert not is_login_allowed(closed, OWNER, email_verified=False)  # 구글이 확인하지 않은 이메일은 안 됨
    kim = replace(test_settings, allowed_login_emails=frozenset({"kim@x.com"}))
    assert is_login_allowed(kim, "Kim@x.com", email_verified=True)
    assert not is_login_allowed(kim, "\u212aim@x.com", email_verified=True)  # 켈빈 기호(K)는 소문자로 k가 되지만 막힘
    assert GoogleProfile(sub="s", email=OWNER, name="n").email_verified is False  # 값을 빠뜨리면 닫는 쪽


def test_not_allowed_login_makes_no_account(client: TestClient, db_session: Session, allow_owner: Settings) -> None:
    """목록 밖이면 계정을 만들지 않고 로그인 화면의 샘플 안내로 보낸다(완료 기준 1 · 2)."""
    response = _google_callback(client, GoogleProfile(sub="g-other", email="other@example.com", name="남"))
    assert response.status_code == 302
    assert response.headers["location"] == f"{allow_owner.frontend_url}/login?error=not_allowed"
    assert SESSION_COOKIE_NAME not in response.cookies
    state_cookie = [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{OAUTH_STATE_COOKIE_NAME}=")]
    assert state_cookie and "Max-Age=0" in state_cookie[0]  # 쓴 state 쿠키는 지운다
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_unverified_email_is_not_allowed_even_if_listed(client: TestClient, db_session: Session, allow_owner: Settings) -> None:
    profile = GoogleProfile(sub="g-owner", email=OWNER, name="본인", email_verified=False)
    response = _google_callback(client, profile)
    assert response.headers["location"].endswith("/login?error=not_allowed")
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_allowed_login_works_case_insensitively(client: TestClient, allow_owner: Settings) -> None:
    response = _google_callback(client, GoogleProfile(sub="g-owner", email="Owner@Example.COM", name="본인", email_verified=True))
    assert response.headers["location"] == f"{allow_owner.frontend_url}/home"
    client.cookies.set(SESSION_COOKIE_NAME, response.cookies[SESSION_COOKIE_NAME])
    assert client.get("/api/auth/me").status_code == 200


def test_removed_from_list_is_blocked_on_next_request(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    """세션이 남아 있어도 목록에서 빠지면 다음 요청부터 401(완료 기준 3)."""
    user = get_or_create_google_user(db_session, GoogleProfile(sub="g-former", email="former@example.com", name="전"))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user.id, test_settings.session_secret))
    assert client.get("/api/auth/me").status_code == 200  # 목록이 비어 있을 때는 열림

    closed = replace(test_settings, allowed_login_emails=frozenset({OWNER}))
    app.dependency_overrides[get_settings] = lambda: closed
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == NOT_ALLOWED_DETAIL
    assert response.headers[LOGIN_ERROR_HEADER] == "not_allowed"  # 화면이 안내 있는 로그인 화면으로 보내는 신호
    assert client.get("/api/notes").status_code == 401  # 회원 API 전체가 같은 의존성을 거친다
    files = {"files": ("a.md", b"# a", "text/markdown")}
    assert client.post("/api/notes/import", files=files).status_code == 401  # 가져오기도(미들웨어 다음 라우터에서)


def test_sample_opens_regardless_of_list(client: TestClient, db_session: Session, allow_owner: Settings) -> None:
    """샘플 체험은 목록과 상관없다(완료 기준 5)."""
    get_or_create_google_user(db_session, GoogleProfile(sub=SAMPLE_GOOGLE_SUB, email="sample@didim.local", name="샘플 지원자"))
    response = client.post("/api/demo/session")
    assert response.status_code == 204
    client.cookies.set(SESSION_COOKIE_NAME, response.cookies[SESSION_COOKIE_NAME])
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["is_sample"] is True


@pytest.mark.parametrize(
    "production",
    [
        {"cookie_secure": True},
        {"frontend_url": "https://didim.example"},
        {"frontend_url": "http://203.0.113.5:3000"},
        # 화면 주소까지 기본값(localhost)으로 둔 운영 — 구글 돌아올 주소는 공개 주소일 수밖에 없다(3차 리뷰 R2)
        {"google_redirect_uri": "https://didim.example/api/auth/google/callback"},
    ],
)
def test_production_without_allowlist_refuses_to_start(test_settings: Settings, production: dict[str, object]) -> None:
    """운영인데 목록이 비면 시작하지 않는다 — COOKIE_SECURE를 false로 둔 운영(https · localhost가 아닌 주소)도(F-015 리뷰 R2)."""
    with pytest.raises(LoginConfigError, match="ALLOWED_LOGIN_EMAILS"):
        check_login_allowlist(replace(test_settings, **production))  # type: ignore[arg-type]
    check_login_allowlist(replace(test_settings, allowed_login_emails=frozenset({OWNER}), **production))  # type: ignore[arg-type]


def test_local_without_allowlist_starts(test_settings: Settings) -> None:
    for url in ("http://localhost:3000", "http://127.0.0.1:3000"):
        check_login_allowlist(replace(test_settings, frontend_url=url))  # 로컬은 비어도 됨(완료 기준 4)


def test_dropped_non_ascii_entries_are_logged_by_count(test_settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    check_login_allowlist(test_settings, "\u212aim@x.com, a@x.com")
    assert "1개" in caplog.text and "\u212a" not in caplog.text and "a@x.com" not in caplog.text  # 이메일 값은 로그에 안 씀


@pytest.mark.parametrize(("verified", "expected"), [(True, True), (None, False), ("true", False)])
def test_exchange_maps_email_verified(test_settings: Settings, verified: object, expected: bool) -> None:
    """구글 userinfo의 email_verified가 true일 때만 확인된 이메일로 본다(값이 없거나 글자 'true'는 아님)."""
    userinfo: dict[str, object] = {"sub": "g-1", "email": OWNER, "name": "본인"}
    if verified is not None:
        userinfo["email_verified"] = verified

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "token_type": "Bearer"})
        return httpx.Response(200, json=userinfo)

    real_client = httpx.AsyncClient
    with patch.object(auth_service.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
        profile = asyncio.run(auth_service.exchange_google_code_for_profile("code", test_settings))
    assert profile.email_verified is expected

def test_startup_passes_the_raw_env_for_the_warning(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """시작 함수가 환경변수 원문을 넘겨 버린 개수 경고가 실제로 난다(3차 리뷰 R3)."""
    for name in ("COOKIE_SECURE", "FRONTEND_URL", "GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)  # 로컬 기본값 — 시작은 되고 경고만
    monkeypatch.setenv("ALLOWED_LOGIN_EMAILS", "\u212aim@x.com, a@x.com")
    check_login_allowlist_from_env()
    assert "1개" in caplog.text


def test_production_without_secure_cookie_is_warned(test_settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    """운영으로 보이는데 COOKIE_SECURE가 꺼져 있으면 경고(강제 여부는 배포 때 정함 — Q-012, 3차 리뷰 R2)."""
    production = replace(test_settings, frontend_url="https://didim.example", allowed_login_emails=frozenset({OWNER}))
    check_login_allowlist(production)
    assert "COOKIE_SECURE" in caplog.text
    caplog.clear()
    check_login_allowlist(replace(production, cookie_secure=True))
    assert "COOKIE_SECURE" not in caplog.text
