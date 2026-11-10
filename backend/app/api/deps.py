from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import SESSION_COOKIE_NAME, Settings, load_settings
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import (
    SessionConfigError,
    get_user_by_id,
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

    return user
