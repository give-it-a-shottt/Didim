from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.config import (
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
    is_sample_session_token,
    is_sample_user,
    verify_session_token,
)

# 인증 오류 문구. 가져오기 업로드 가드(app/api/upload_limit.py)도 같은 문구를 쓴다.
LOGIN_REQUIRED_DETAIL = "로그인이 필요해요."
SESSION_EXPIRED_DETAIL = "로그인이 만료되었어요. 다시 로그인해 주세요."
AUTH_NOT_CONFIGURED_DETAIL = "서버 인증 설정이 완료되지 않았어요."


def get_settings() -> Settings:
    return load_settings()


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
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 계정이에요. 다시 로그인해 주세요.",
        )

    # 샘플 표시가 있는 토큰은 샘플 계정이어야 하고, 샘플 계정은 샘플 표시가 있는 토큰으로만 열린다. 시드가 샘플 계정을 다시 만들며
    # 번호가 다른 사람에게 가는 DB(SQLite 등)에서 옛 샘플 토큰이 그 사람으로 열리지 않게 한다(F-010 1차 R2). 위에서 서명을 이미 확인해
    # 설정 오류는 나지 않는다.
    token_is_sample = is_sample_session_token(session_token, settings.session_secret)
    account_is_sample = is_sample_user(user)
    if token_is_sample != account_is_sample:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 계정이에요. 다시 로그인해 주세요.",
        )

    return user


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """세션 쿠키 옵션은 여기 한 곳 — 구글 로그인 콜백과 샘플 체험 열기가 같이 쓴다(F-010 1차 R1)."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
