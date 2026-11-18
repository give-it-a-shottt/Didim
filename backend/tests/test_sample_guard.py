"""샘플 체험 세션 · 읽기 전용 미들웨어 테스트 (F-010, D-029)."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
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


# --- 실패 · 보안 경로 ---


def test_sample_search_does_not_save_logs(client: TestClient, db_session: Session, monkeypatch) -> None:
    """샘플은 GET 검색도 DB에 쓰지 않는다(검색 로그). 라우터가 save_log=False를 넘기는지 본다."""
    import app.api.search as search_api

    seen: list[bool] = []

    def fake_search_records(*_args, save_log: bool = True, **_kwargs):
        seen.append(save_log)
        raise search_api.SearchUnavailableError("멈춤")  # 응답 모양은 이 테스트의 관심이 아님

    monkeypatch.setattr(search_api, "search_records", fake_search_records)
    _open_sample(client, db_session)
    client.get("/api/search", params={"q": "캐시"})
    client.cookies.clear()
    user = get_or_create_google_user(db_session, GoogleProfile(sub="555", email="b@example.com", name="나"))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user.id, SECRET))
    client.get("/api/search", params={"q": "캐시"})
    assert seen == [False, True]


def test_search_records_skips_the_log_when_asked(db_session: Session) -> None:
    from app.db.models import SearchLog
    from app.search import SearchQuery
    from app.services.search_service import search_records

    class EmptySearcher:
        method = "fake"

        def search(self, db, *, user_id, query: SearchQuery, limit, max_per_note):
            return []

    user = get_or_create_google_user(db_session, GoogleProfile(sub="556", email="c@example.com", name="다"))
    search_records(db_session, EmptySearcher(), user_id=user.id, text="캐시", limit=5, save_log=False)  # type: ignore[arg-type]
    assert db_session.scalar(select(func.count()).select_from(SearchLog)) == 0
    search_records(db_session, EmptySearcher(), user_id=user.id, text="캐시", limit=5)  # type: ignore[arg-type]
    assert db_session.scalar(select(func.count()).select_from(SearchLog)) == 1


def test_sample_mark_must_match_the_account(client: TestClient, db_session: Session) -> None:
    """토큰의 샘플 표시와 계정이 다르면 401(샘플 계정을 다시 만들며 번호가 다른 사람에게 간 경우)."""
    normal = get_or_create_google_user(db_session, GoogleProfile(sub="557", email="d@example.com", name="라"))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(normal.id, SECRET, sample=True))
    assert client.get("/api/auth/me").status_code == 401
    sample_id = _sample_user(db_session)
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(sample_id, SECRET))  # 샘플 계정인데 표시 없음
    assert client.get("/api/auth/me").status_code == 401


def test_open_sample_refuses_cross_site_requests(client: TestClient, db_session: Session) -> None:
    """다른 사이트가 보낸 form으로 방문자를 로그아웃시키지 못하게(로그인 CSRF)."""
    _sample_user(db_session)
    for site in ("cross-site", "same-site"):
        response = client.post("/api/demo/session", headers={"Sec-Fetch-Site": site})
        assert response.status_code == 403, site
        assert SESSION_COOKIE_NAME not in response.cookies
    assert client.post("/api/demo/session", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 204
    # 주소창 · 북마크(none)와 대소문자가 다른 값도 받는다
    for site in ("none", "Same-Origin", "NONE"):
        assert client.post("/api/demo/session", headers={"Sec-Fetch-Site": site}).status_code == 204, site
    assert client.post("/api/demo/session", headers={"Sec-Fetch-Site": "Cross-Site"}).status_code == 403


def test_open_sample_reports_session_config_errors(client: TestClient, db_session: Session, test_settings) -> None:
    """세션 비밀키 설정이 틀리면 500."""
    import dataclasses

    from app.api.deps import AUTH_NOT_CONFIGURED_DETAIL, get_settings

    _sample_user(db_session)
    client.app.dependency_overrides[get_settings] = lambda: dataclasses.replace(test_settings, session_secret="짧음")  # type: ignore[attr-defined]
    response = client.post("/api/demo/session")
    assert response.status_code == 500
    assert response.json()["detail"] == AUTH_NOT_CONFIGURED_DETAIL


def test_seeding_account_cannot_be_opened_by_any_token(client: TestClient, db_session: Session) -> None:
    """샘플 시드의 임시 계정은 예약 계정 — 일반 토큰 · 샘플 토큰 모두 401."""
    from app.config import SAMPLE_SEEDING_SUB
    from app.db.models import User

    staging = User(google_sub=SAMPLE_SEEDING_SUB, email="sample@didim.local", name="샘플", daily_limit=10_000)
    db_session.add(staging)
    db_session.commit()
    for sample in (False, True):
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(staging.id, SECRET, sample=sample))
        assert client.get("/api/auth/me").status_code == 401, sample
