"""샘플 체험 세션 열기 (F-010, D-025 · D-029).

로그인 없이 부른다. 샘플 사용자(google_sub = SAMPLE_GOOGLE_SUB)의 세션 쿠키를 지금 쿠키 자리에 바꿔 끼운다 —
로그인한 사람이 부르면 로그아웃된다(화면이 버튼 옆에 미리 알림). 샘플 세션은 읽기만 한다(app/api/sample_guard.py).
샘플 데이터는 시드 스크립트가 넣는다. 아직 없으면 503으로 알린다.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AUTH_NOT_CONFIGURED_DETAIL, get_settings
from app.config import (
    SAMPLE_GOOGLE_SUB,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    Settings,
)
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import SessionConfigError, create_session_token

router = APIRouter(prefix="/demo", tags=["demo"])

SAMPLE_NOT_READY_DETAIL = "샘플 데이터가 아직 준비되지 않았어요."


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
def open_sample_session(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> Response:
    sample_id = db.execute(select(User.id).where(User.google_sub == SAMPLE_GOOGLE_SUB)).scalar_one_or_none()
    if sample_id is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=SAMPLE_NOT_READY_DETAIL)
    try:
        token = create_session_token(sample_id, settings.session_secret, sample=True)
    except SessionConfigError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=AUTH_NOT_CONFIGURED_DETAIL) from exc
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response
