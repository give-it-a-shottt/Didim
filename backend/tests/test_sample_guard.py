"""샘플 체험 세션 · 읽기 전용 미들웨어 테스트 (F-010, D-029)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.sample_guard import (
    ALLOWED_WRITES,
    BLOCKED_READS,
    SAMPLE_READ_ONLY_DETAIL,
    is_blocked_for_sample,
)
from app.config import SAMPLE_GOOGLE_SUB, SESSION_COOKIE_NAME, Settings
from app.main import app
from app.services.auth_service import (
    GoogleProfile,
    create_session_token,
    get_or_create_google_user,
    is_sample_session_token,
)

SECRET = "test-only-session-secret-at-least-32-bytes-long"


def _sample_user(db: Session) -> int:
    return get_or_create_google_user(db, GoogleProfile(sub=SAMPLE_GOOGLE_SUB, email="sample@didim.local", name="샘플 지원자")).id


def _open_sample(client: TestClient, db: Session) -> None:
    _sample_user(db)
    response = client.post("/api/demo/session")
    assert response.status_code == 204
    assert SESSION_COOKIE_NAME in response.cookies


def test_sample_session_needs_seeded_user(client: TestClient) -> None:
    response = client.post("/api/demo/session")
    assert response.status_code == 503
    assert SESSION_COOKIE_NAME not in response.cookies


def test_sample_session_reads_and_me_says_sample(client: TestClient, db_session: Session) -> None:
    _open_sample(client, db_session)
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["is_sample"] is True
    assert client.get("/api/applications").status_code == 200
    assert client.get("/api/cards").status_code == 200


def test_sample_session_cannot_write_or_call_ai(client: TestClient, db_session: Session) -> None:
    _open_sample(client, db_session)
    for method, path in [
        ("POST", "/api/applications"),
        ("POST", "/api/notes/1/quizzes"),
        ("POST", "/api/quizzes/1/answer"),
        ("PATCH", "/api/applications/1"),
        ("DELETE", "/api/cards/1"),
        ("POST", "/api/notes/import"),  # 업로드 가드보다 먼저 막힌다
        ("GET", "/api/notion/connect"),
        ("GET", "/api/notion/callback"),
    ]:
        response = client.request(method, path)
        assert response.status_code == 403, (method, path)
        assert response.json()["detail"] == SAMPLE_READ_ONLY_DETAIL


def test_sample_session_can_end(client: TestClient, db_session: Session) -> None:
    _open_sample(client, db_session)
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


def test_normal_user_is_not_blocked(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    user = get_or_create_google_user(db_session, GoogleProfile(sub="1234", email="a@example.com", name="가"))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user.id, test_settings.session_secret))
    assert client.get("/api/auth/me").json()["is_sample"] is False
    response = client.post("/api/applications", json={})
    assert response.status_code != 403  # 입력이 틀려 422 — 샘플 가드는 끼어들지 않는다


def test_sample_mark_cannot_be_forged() -> None:
    token = create_session_token(1, SECRET, sample=True)
    assert is_sample_session_token(token, SECRET)
    assert not is_sample_session_token(create_session_token(1, SECRET), SECRET)
    assert not is_sample_session_token(token, "other-secret-that-is-also-at-least-32-bytes")
    assert not is_sample_session_token(token[:-4] + "aaaa", SECRET)
    assert not is_sample_session_token(create_session_token(1, SECRET, sample=True, max_age_seconds=-10), SECRET)


def _registered() -> list[tuple[str, str]]:
    # 이 FastAPI는 include_router를 감싸 app.routes에 경로가 안 보인다 — 실제 경로 목록은 OpenAPI에서 읽는다
    return [(method.upper(), path) for path, ops in app.openapi()["paths"].items() for method in ops]


def test_every_write_route_is_blocked_by_default() -> None:
    """기본이 '막기'인지 — 실제 등록된 모든 경로로 확인. 허용 목록은 로그아웃 · 체험 열기뿐."""
    assert ALLOWED_WRITES == {("POST", "/api/auth/logout"), ("POST", "/api/demo/session")}
    routes = _registered()
    assert ALLOWED_WRITES <= set(routes)
    writes = [(m, p) for m, p in routes if m not in {"GET", "HEAD", "OPTIONS"}]
    assert len(writes) == 23, writes  # 쓰기 21 + 로그아웃 + 체험 열기
    for method, path in routes:
        if method == "GET":
            assert is_blocked_for_sample(method, path) == (path in BLOCKED_READS)
        else:
            assert is_blocked_for_sample(method, path) == ((method, path) not in ALLOWED_WRITES)


def test_get_routes_snapshot() -> None:
    """GET 경로가 늘면 여기서 멈춘다 — 새 GET이 무언가를 저장한다면 BLOCKED_READS에 더할지 보고 이 숫자를 고친다."""
    gets = sorted(p for m, p in _registered() if m == "GET")
    assert BLOCKED_READS <= set(gets)
    assert len(gets) == 21, gets  # F-010 GET /api/report 추가(읽기만 함)
