from urllib.parse import urlsplit

from fastapi import Cookie, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.config import (
    SAMPLE_SEEDING_SUB,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    Settings,
    load_settings,
)
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import (
    SessionConfigError,
    get_user_by_id,
    is_login_allowed,
    is_sample_session_token,
    is_sample_user,
    verify_session_token,
)

# 인증 오류 문구. 가져오기 업로드 가드(app/api/upload_limit.py)도 같은 문구를 쓴다.
LOGIN_REQUIRED_DETAIL = "로그인이 필요해요."
SESSION_EXPIRED_DETAIL = "로그인이 만료되었어요. 다시 로그인해 주세요."
AUTH_NOT_CONFIGURED_DETAIL = "서버 인증 설정이 완료되지 않았어요."
NOT_ALLOWED_DETAIL = "지금은 샘플 체험만 열려 있어요."
# 401의 이유를 화면에 알리는 머리말(값: not_allowed) — frontend/src/lib/auth.ts가 읽어 /login?error=not_allowed로 보낸다
LOGIN_ERROR_HEADER = "X-Didim-Login-Error"
CROSS_SITE_DETAIL = "다른 사이트에서 보낸 요청은 받지 않아요."
# 같은 사이트 화면의 fetch(same-origin)와 주소창 · 북마크(none)만 받는다
ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})


def get_settings() -> Settings:
    return load_settings()


def reject_cross_site(
    sec_fetch_site: str | None = Header(default=None),
    origin: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """세션 쿠키를 바꾸는 요청(샘플 세션 열기 · 로그아웃)에 건다 — 다른 사이트가 form을 보내 방문자를 몰래
    로그아웃시키거나 샘플 세션으로 바꿔 끼우지 못하게(로그인 CSRF).
    - 브라우저가 붙이는 Sec-Fetch-Site가 same-origin · none이 아니면 403.
    - Sec-Fetch-Site가 없으면(오래된 브라우저, 또는 앞단 프록시가 뺀 경우) Origin을 본다 — 화면 주소(FRONTEND_URL)와 다르면 403.
    - 둘 다 없으면(테스트 · curl) 받는다. 화면은 같은 주소의 /api/*(Next 프록시)로만 부르고, 배포 프록시가 두 머리말을 넘겨야 한다(Q-012).
    """
    if sec_fetch_site is not None:
        if sec_fetch_site.lower() not in ALLOWED_FETCH_SITES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CROSS_SITE_DETAIL)
        return
    if origin is not None and origin.rstrip("/").lower() != _origin_of(settings.frontend_url):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CROSS_SITE_DETAIL)


def _origin_of(url: str) -> str:
    """'http://localhost:3000/경로' → 'http://localhost:3000'(브라우저가 Origin에 싣는 모양)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """httpOnly 세션 쿠키를 검증해 현재 로그인한 사용자를 돌려준다 (D-010).

    쿠키가 없거나 위조·만료되었거나 DB에 사용자가 없으면 401을 반환한다.
    """
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=LOGIN_REQUIRED_DETAIL,
        )

    try:
        user_id = verify_session_token(session_token, settings.session_secret)
    except SessionConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=AUTH_NOT_CONFIGURED_DETAIL,
        ) from exc

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=SESSION_EXPIRED_DETAIL,
        )

    user = get_user_by_id(db, user_id)
    # 샘플 시드의 임시 계정은 예약 계정 — 어떤 토큰으로도 열리지 않는다
    if user is None or user.google_sub == SAMPLE_SEEDING_SUB:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 계정이에요. 다시 로그인해 주세요.",
        )

    # 샘플 표시가 있는 토큰은 샘플 계정이어야 하고, 샘플 계정은 샘플 표시가 있는 토큰으로만 열린다. 시드가 샘플 계정을 다시 만들며
    # 번호가 다른 사람에게 가는 DB(SQLite 등)에서 옛 샘플 토큰이 그 사람으로 열리지 않게 한다. 위에서 서명을 이미 확인해
    # 설정 오류는 나지 않는다.
    token_is_sample = is_sample_session_token(session_token, settings.session_secret)
    account_is_sample = is_sample_user(user)
    if token_is_sample != account_is_sample:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 계정이에요. 다시 로그인해 주세요.",
        )
    # 허용 목록에서 빠진 사람은 세션이 남아 있어도(최대 7일) 다음 요청부터 막는다. 샘플 계정은 목록과 상관없다(F-015 · D-031).
    # email_verified=True: DB 이메일은 로그인 때 받은 것 — 목록이 있을 때는 확인된 이메일만 들어온다(목록이 빈 채 들어온
    # 확인 안 된 주소를 나중에 목록에 넣는 경우만 남는데, 구글 계정 이메일은 사실상 늘 확인돼 있다).
    # 화면이 '샘플 체험만 열려 있어요' 안내로 보내게 머리말로 알린다(문구가 아니라 머리말로 구분 — F-015 1차 리뷰 R3).
    if not account_is_sample and not is_login_allowed(settings, user.email, email_verified=True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=NOT_ALLOWED_DETAIL,
            headers={LOGIN_ERROR_HEADER: "not_allowed"},
        )

    return user


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """세션 쿠키 옵션은 여기 한 곳 — 구글 로그인 콜백과 샘플 체험 열기가 같이 쓴다."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
