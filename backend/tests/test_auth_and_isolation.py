from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_settings
from app.config import (
    MIN_SESSION_SECRET_LENGTH,
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    Settings,
)
from app.db.models import Chunk, Note, User
from app.main import app
from app.services.auth_service import (
    GoogleProfile,
    OAuthExchangeError,
    create_oauth_state_token,
    create_session_token,
    get_or_create_google_user,
)
from app.services.chunking import split_markdown
from app.services.note_service import (
    DuplicateNoteError,
    create_note_for_user,
    delete_user_account,
    get_note_for_user,
    list_chunks_for_user,
    list_notes_for_user,
)

ENV_EXAMPLE_PATH = Path(__file__).resolve().parent.parent / ".env.example"


def _read_example_session_secret() -> str:
    """backend/.env.example에 적힌 SESSION_SECRET 예시 값을 그대로 읽는다.

    테스트 안에 "CHANGE_ME"를 직접 적지 않고 파일에서 읽는 이유: 누가 나중에 예시 값을
    다시 32자 이상으로 바꾸면 이 테스트가 그 변경을 잡아내야 하기 때문이다.
    """
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("SESSION_SECRET="):
            return line.removeprefix("SESSION_SECRET=").strip()
    raise AssertionError("backend/.env.example에 SESSION_SECRET 줄이 없어요.")


# client · test_settings fixture는 tests/conftest.py에 있다(F-002 테스트와 같이 씀).


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "로그인이 필요해요."}


def test_me_rejects_forged_or_expired_or_wrong_purpose_cookie(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    secret = test_settings.session_secret
    user = get_or_create_google_user(
        db_session,
        GoogleProfile(sub="google-sub-1", email="user1@example.com", name="김디딤"),
    )

    # 1) 위조된 서명
    forged = create_session_token(user.id, secret)[:-4] + "aaaa"
    client.cookies.set(SESSION_COOKIE_NAME, forged)
    resp_forged = client.get("/api/auth/me")
    assert resp_forged.status_code == 401

    # 2) 만료된 토큰
    expired = create_session_token(user.id, secret, max_age_seconds=-10)
    client.cookies.set(SESSION_COOKIE_NAME, expired)
    resp_expired = client.get("/api/auth/me")
    assert resp_expired.status_code == 401

    # 3) OAuth state 토큰을 세션 쿠키 자리에 넣은 경우 (purpose 불일치 차단)
    state_token = create_oauth_state_token(secret)
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
    test_settings: Settings,
) -> None:
    state_cookie = create_oauth_state_token(test_settings.session_secret)
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


def test_login_refuses_to_start_with_example_session_secret(
    client: TestClient,
    test_settings: Settings,
) -> None:
    """.env.example의 예시 SESSION_SECRET을 그대로 쓰면 로그인이 시작되지 않아야 한다(F-001 3차 R2 · 4차 R3).

    왜 중요한가: 예시 값은 레포에 공개돼 있다. 그 값이 서명 키로 쓰이면 누구나 세션 쿠키를 위조할 수 있다.
    그래서 예시 값을 일부러 32자보다 짧게 두고, 짧은 키로는 서버가 서명을 거부하게 했다.

    무엇을 하는가:
    1. .env.example에서 예시 값을 읽고, 그 값이 정말 32자(MIN_SESSION_SECRET_LENGTH)보다 짧은지 먼저 확인한다.
    2. 서버 설정의 SESSION_SECRET만 그 예시 값으로 바꿔 끼운다(나머지 설정은 정상 테스트 값 그대로).
    3. GET /api/auth/google/login을 부른다.
    4. 구글로 보내지 않고 /login?error=oauth_not_configured로 돌려보내는지,
       위조 방지용 state 쿠키를 발급하지 않았는지 확인한다.

    이 테스트가 실패한다면: 예시 값이 다시 길어졌거나(1번에서 실패),
    짧은 키를 거부하는 검사(auth_service._require_secret)가 사라졌다는 뜻.
    """
    example_secret = _read_example_session_secret()
    assert len(example_secret) < MIN_SESSION_SECRET_LENGTH

    weak_settings = replace(test_settings, session_secret=example_secret)
    app.dependency_overrides[get_settings] = lambda: weak_settings

    response = client.get("/api/auth/google/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/login?error=oauth_not_configured"
    assert response.cookies.get(OAUTH_STATE_COOKIE_NAME) is None


def test_me_returns_500_when_session_secret_is_example_value(
    client: TestClient,
    test_settings: Settings,
) -> None:
    """예시 SESSION_SECRET으로는 세션 쿠키 확인도 하지 않고 500(서버 설정 오류)을 돌려줘야 한다.

    왜 중요한가: 로그인 시작만 막고 세션 확인은 짧은 키로 통과시키면, 공개된 예시 값으로 만든
    가짜 쿠키가 받아들여질 수 있다. 세션 확인도 같은 키 검사를 거쳐야 한다.
    401(로그인 필요)이 아니라 500인 이유: 사용자 잘못이 아니라 서버 설정이 잘못된 상황이기 때문이다.

    무엇을 하는가:
    1. 서버 설정의 SESSION_SECRET을 .env.example 예시 값으로 바꿔 끼운다.
    2. 아무 값이나 넣은 세션 쿠키를 붙여 GET /api/auth/me를 부른다.
       (쿠키가 없으면 키 검사 전에 401로 끝나므로, 키 검사까지 가게 하려고 쿠키를 붙인다.)
    3. 500과 "서버 인증 설정이 완료되지 않았어요." 메시지가 오는지 확인한다.

    이 테스트가 실패한다면: 세션 확인(deps.get_current_user)에서 짧은 키 검사가 빠졌거나,
    설정 오류를 다른 응답 코드로 바꿨다는 뜻.
    """
    weak_settings = replace(test_settings, session_secret=_read_example_session_secret())
    app.dependency_overrides[get_settings] = lambda: weak_settings

    client.cookies.set(SESSION_COOKIE_NAME, "any-cookie-value")
    response = client.get("/api/auth/me")

    assert response.status_code == 500
    assert response.json() == {"detail": "서버 인증 설정이 완료되지 않았어요."}


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

    content_a = "sessionStorage 대신 Redis를 써서 탭을 닫아도 유지되게 했다."
    note_a = create_note_for_user(
        db_session,
        user_id=user_a.id,
        title="A의 Redis 캐시 재설계 노트",
        content=content_a,
        source="markdown",
        kind="project",
        chunks=split_markdown(content_a),
    )
    content_b = "프로세스와 스레드의 차이를 정리했다."
    note_b = create_note_for_user(
        db_session,
        user_id=user_b.id,
        title="B의 운영체제 정리 노트",
        content=content_b,
        source="markdown",
        kind="study",
        chunks=split_markdown(content_b),
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

    same_content = "# 같은 노트\n\n## 첫 구역\n같은 마크다운 원문이라도\n\n## 둘째 구역\n다른 사용자는 각자 올릴 수 있어야 한다."
    note_a = create_note_for_user(
        db_session,
        user_id=user_a.id,
        title="A 노트",
        content=same_content,
        chunks=split_markdown(same_content),
    )
    assert len(note_a.chunks) == 2

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
        chunks=split_markdown(same_content)[:1],
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
