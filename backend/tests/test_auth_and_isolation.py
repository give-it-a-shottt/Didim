from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_settings
from app.config import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    Settings,
)
from app.db.base import Base
from app.db.models import Chunk, Note, User
from app.db.session import create_db_engine, get_db
from app.main import app
from app.services.auth_service import (
    GoogleProfile,
    OAuthExchangeError,
    create_oauth_state_token,
    create_session_token,
    get_or_create_google_user,
)
from app.services.note_service import (
    DuplicateNoteError,
    create_note_for_user,
    delete_user_account,
    get_note_for_user,
    list_chunks_for_user,
    list_notes_for_user,
)

TEST_SECRET = "test-only-session-secret-at-least-32-bytes-long"


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        session_secret=TEST_SECRET,
        google_client_id="test-client-id.apps.googleusercontent.com",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:3000/api/auth/google/callback",
        frontend_url="http://localhost:3000",
        cookie_secure=False,
    )


@pytest.fixture()
def db_session( tmp_path: pytest.TempPathFactory ) -> Generator[Session, None, None]:
    db_file = tmp_path / "test_didim.db"
    engine = create_db_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session: Session, test_settings: Settings) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def _override_get_settings() -> Settings:
        return test_settings

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = _override_get_settings
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "로그인이 필요해요."}


def test_me_rejects_forged_or_expired_or_wrong_purpose_cookie(
    client: TestClient,
    db_session: Session,
) -> None:
    user = get_or_create_google_user(
        db_session,
        GoogleProfile(sub="google-sub-1", email="user1@example.com", name="김디딤"),
    )

    # 1) 위조된 서명
    forged = create_session_token(user.id, TEST_SECRET)[:-4] + "aaaa"
    client.cookies.set(SESSION_COOKIE_NAME, forged)
    resp_forged = client.get("/api/auth/me")
    assert resp_forged.status_code == 401

    # 2) 만료된 토큰
    expired = create_session_token(user.id, TEST_SECRET, max_age_seconds=-10)
    client.cookies.set(SESSION_COOKIE_NAME, expired)
    resp_expired = client.get("/api/auth/me")
    assert resp_expired.status_code == 401

    # 3) OAuth state 토큰을 세션 쿠키 자리에 넣은 경우 (purpose 불일치 차단)
    state_token = create_oauth_state_token(TEST_SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, state_token)
    resp_wrong_purpose = client.get("/api/auth/me")
    assert resp_wrong_purpose.status_code == 401


def test_google_login_flow_and_logout(client: TestClient, db_session: Session) -> None:
    # 1) 구글 로그인 시작 → state 쿠키 발급 + Google 동의 화면 리다이렉트
    login_resp = client.get("/api/auth/google/login", follow_redirects=False)
    assert login_resp.status_code == 302
    location = login_resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    state_cookie = login_resp.cookies.get(OAUTH_STATE_COOKIE_NAME)
    assert state_cookie is not None

    # 2) 콜백 성공 → 사용자 생성 + 세션 쿠키 발급 + /home 이동
    mock_profile = GoogleProfile(
        sub="google-sub-login-test",
        email="didim@example.com",
        name="이디딤",
    )
    with patch(
        "app.api.auth.exchange_google_code_for_profile",
        new=AsyncMock(return_value=mock_profile),
    ):
        client.cookies.set(OAUTH_STATE_COOKIE_NAME, state_cookie)
        callback_resp = client.get(
            "/api/auth/google/callback",
            params={"code": "valid-oauth-code", "state": state_cookie},
            follow_redirects=False,
        )

    assert callback_resp.status_code == 302
    assert callback_resp.headers["location"] == "http://localhost:3000/home"
    session_cookie = callback_resp.cookies.get(SESSION_COOKIE_NAME)
    assert session_cookie is not None

    # 3) 발급된 세션 쿠키로 /api/auth/me 조회
    client.cookies.set(SESSION_COOKIE_NAME, session_cookie)
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["email"] == "didim@example.com"
    assert body["name"] == "이디딤"
    assert isinstance(body["id"], int)

    # 4) 로그아웃 → 204
    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 204


def test_google_callback_rejects_mismatched_state_and_oauth_failure(
    client: TestClient,
) -> None:
    state_cookie = create_oauth_state_token(TEST_SECRET)
    client.cookies.set(OAUTH_STATE_COOKIE_NAME, state_cookie)

    # 1) state 불일치
    bad_state_resp = client.get(
        "/api/auth/google/callback",
        params={"code": "some-code", "state": "wrong-state"},
        follow_redirects=False,
    )
    assert bad_state_resp.status_code == 302
    assert bad_state_resp.headers["location"] == "http://localhost:3000/login?error=invalid_oauth_state"

    # 2) 사용자가 구글 동의 화면에서 거절한 경우
    denied_resp = client.get(
        "/api/auth/google/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert denied_resp.status_code == 302
    assert denied_resp.headers["location"] == "http://localhost:3000/login?error=oauth_access_denied"

    # 3) 구글 토큰 교환 실패 대응
    with patch(
        "app.api.auth.exchange_google_code_for_profile",
        new=AsyncMock(side_effect=OAuthExchangeError("token_exchange_failed")),
    ):
        client.cookies.set(OAUTH_STATE_COOKIE_NAME, state_cookie)
        exchange_fail_resp = client.get(
            "/api/auth/google/callback",
            params={"code": "expired-code", "state": state_cookie},
            follow_redirects=False,
        )
    assert exchange_fail_resp.status_code == 302
    assert (
        exchange_fail_resp.headers["location"]
        == "http://localhost:3000/login?error=token_exchange_failed"
    )


def test_user_a_note_is_never_visible_to_user_b(db_session: Session) -> None:
    """F-001 핵심 완료 기준: A가 올린 노트가 B에게 보이지 않는 테스트를 통과한다."""
    user_a = get_or_create_google_user(
        db_session,
        GoogleProfile(sub="sub-user-a", email="a@example.com", name="사용자A"),
    )
    user_b = get_or_create_google_user(
        db_session,
        GoogleProfile(sub="sub-user-b", email="b@example.com", name="사용자B"),
    )

    note_a = create_note_for_user(
        db_session,
        user_id=user_a.id,
        title="A의 Redis 캐시 재설계 노트",
        content="sessionStorage 대신 Redis를 써서 탭을 닫아도 유지되게 했다.",
        source="markdown",
        kind="project",
        chunk_contents=["sessionStorage 대신 Redis를 써서 탭을 닫아도 유지되게 했다."],
    )
    note_b = create_note_for_user(
        db_session,
        user_id=user_b.id,
        title="B의 운영체제 정리 노트",
        content="프로세스와 스레드의 차이를 정리했다.",
        source="markdown",
        kind="study",
        chunk_contents=["프로세스와 스레드의 차이를 정리했다."],
    )

    # B가 목록 조회 시 A의 노트는 보이지 않고 B의 노트만 보인다.
    b_notes = list_notes_for_user(db_session, user_id=user_b.id)
    assert [n.id for n in b_notes] == [note_b.id]

    # B가 A의 note_id를 직접 지정해 단건 조회해도 None이 반환된다.
    assert get_note_for_user(db_session, user_id=user_b.id, note_id=note_a.id) is None
    assert get_note_for_user(db_session, user_id=user_a.id, note_id=note_a.id) is not None

    # 조각(chunks) 조회 역시 사용자별로 완전히 분리된다.
    b_chunks = list_chunks_for_user(db_session, user_id=user_b.id)
    assert len(b_chunks) == 1
    assert b_chunks[0].note_id == note_b.id


def test_duplicate_note_per_user_and_cascade_delete_on_user_removal(
    db_session: Session,
) -> None:
    """사용자를 삭제하면 그 사용자의 노트·조각이 함께 지워지고, 다른 사용자 데이터는 남는다."""
    user_a = get_or_create_google_user(
        db_session,
        GoogleProfile(sub="sub-cascade-a", email="ca@example.com", name="삭제대상A"),
    )
    user_b = get_or_create_google_user(
        db_session,
        GoogleProfile(sub="sub-cascade-b", email="cb@example.com", name="유지대상B"),
    )

    same_content = "같은 마크다운 원문이라도 다른 사용자는 각자 올릴 수 있어야 한다."
    create_note_for_user(
        db_session,
        user_id=user_a.id,
        title="A 노트",
        content=same_content,
        chunk_contents=["조각 A-1", "조각 A-2"],
    )

    # 같은 사용자(A)가 똑같은 원문을 다시 올리면 중복 오류가 발생한다.
    with pytest.raises(DuplicateNoteError):
        create_note_for_user(
            db_session,
            user_id=user_a.id,
            title="A 중복 노트",
            content=same_content,
        )

    # 다른 사용자(B)는 같은 원문을 올려도 정상 저장된다.
    note_b = create_note_for_user(
        db_session,
        user_id=user_b.id,
        title="B 노트",
        content=same_content,
        chunk_contents=["조각 B-1"],
    )

    # 사용자 A 삭제 → A의 User · Note · Chunk가 DB 외래키 ON DELETE CASCADE로 모두 삭제됨
    deleted = delete_user_account(db_session, user_id=user_a.id)
    assert deleted is True

    assert db_session.execute(select(User).where(User.id == user_a.id)).scalar_one_or_none() is None
    assert list_notes_for_user(db_session, user_id=user_a.id) == []
    assert list_chunks_for_user(db_session, user_id=user_a.id) == []

    # 사용자 B의 노트와 조각은 그대로 남아 있음
    assert [n.id for n in list_notes_for_user(db_session, user_id=user_b.id)] == [note_b.id]
    assert len(list_chunks_for_user(db_session, user_id=user_b.id)) == 1
