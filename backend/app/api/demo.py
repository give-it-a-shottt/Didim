"""샘플 체험 세션 열기 (F-010, D-025 · D-029).

로그인 없이 부른다. 샘플 사용자(google_sub = SAMPLE_GOOGLE_SUB)의 세션 쿠키를 지금 쿠키 자리에 바꿔 끼운다 —
로그인한 사람이 부르면 로그아웃된다(화면이 버튼 옆에 미리 알림). 샘플 세션은 읽기만 한다(app/api/sample_guard.py).
샘플 데이터는 시드 스크립트가 넣는다. 아직 없으면 503으로 알린다.

다른 사이트가 이 주소로 form을 보내 방문자를 몰래 로그아웃시키지 못하게, 브라우저가 붙이는 Sec-Fetch-Site가
same-origin · none이 아니면 403. 머리말이 없는 요청(오래된 브라우저 · 테스트 · curl)은 그대로 받는다.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AUTH_NOT_CONFIGURED_DETAIL, get_settings, set_session_cookie
from app.config import SAMPLE_GOOGLE_SUB, Settings
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import SessionConfigError, create_session_token

router = APIRouter(prefix="/demo", tags=["demo"])

SAMPLE_NOT_READY_DETAIL = "샘플 데이터가 아직 준비되지 않았어요."
CROSS_SITE_DETAIL = "다른 사이트에서 보낸 요청은 받지 않아요."
# 같은 사이트 화면의 fetch(same-origin)와 주소창 · 북마크(none)만 받는다
ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
def open_sample_session(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    sec_fetch_site: str | None = Header(default=None),
) -> Response:
    if sec_fetch_site is not None and sec_fetch_site.lower() not in ALLOWED_FETCH_SITES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CROSS_SITE_DETAIL)
    sample_id = db.execute(select(User.id).where(User.google_sub == SAMPLE_GOOGLE_SUB)).scalar_one_or_none()
    if sample_id is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=SAMPLE_NOT_READY_DETAIL)
    try:
        token = create_session_token(sample_id, settings.session_secret, sample=True)
    except SessionConfigError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=AUTH_NOT_CONFIGURED_DETAIL) from exc
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookie(response, token, settings)
    return response
