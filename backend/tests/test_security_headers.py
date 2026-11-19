"""백엔드 응답 보안 머리말 테스트 (D-032, F-016)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import SAMPLE_GOOGLE_SUB, SESSION_COOKIE_NAME, Settings
from app.services.auth_service import (
    GoogleProfile,
    create_session_token,
    get_or_create_google_user,
)


def test_every_response_has_nosniff(client: TestClient) -> None:
    for response in (client.get("/api/health"), client.get("/api/auth/me"), client.get("/api/report")):
        assert response.headers["x-content-type-options"] == "nosniff"


def test_signed_in_responses_are_not_cached(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    assert "cache-control" not in client.get("/api/health").headers  # 쿠키 없음 — 공개 응답은 그대로
    user = get_or_create_google_user(db_session, GoogleProfile(sub="g-cache", email="c@example.com", name="캐", email_verified=True))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user.id, test_settings.session_secret))
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_guard_and_error_responses_also_have_nosniff(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    """가드가 직접 끝낸 응답(401 · 403)과 없는 주소(404)에도 — 머리말 미들웨어가 가장 바깥이어야 한다(F-016 2차 리뷰 R3)."""
    assert client.get("/api/no-such-route").headers["x-content-type-options"] == "nosniff"  # 404
    # 가져오기 가드(ImportUploadGuard)가 쿠키 없는 요청을 본문을 받기 전에 401로 끝낸다
    blocked = client.post("/api/notes/import", headers={"content-type": "multipart/form-data; boundary=x"}, content=b"")
    assert blocked.status_code == 401
    assert blocked.headers["x-content-type-options"] == "nosniff"
    # 샘플 세션의 쓰기는 샘플 가드(SampleReadOnlyGuard)가 403으로 끝낸다
    get_or_create_google_user(db_session, GoogleProfile(sub=SAMPLE_GOOGLE_SUB, email="sample@didim.local", name="샘플", email_verified=True))
    assert client.post("/api/demo/session").status_code == 204
    forbidden = client.post("/api/notes", json={})
    assert forbidden.status_code == 403
    assert forbidden.headers["x-content-type-options"] == "nosniff"
    assert forbidden.headers["cache-control"] == "no-store"  # 샘플 세션 쿠키가 실린 요청
