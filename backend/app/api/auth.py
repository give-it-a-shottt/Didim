from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, Query, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_settings
from app.config import (
    OAUTH_STATE_COOKIE_NAME,
    OAUTH_STATE_MAX_AGE_SECONDS,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    Settings,
)
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import (
    OAuthConfigError,
    OAuthExchangeError,
    SessionConfigError,
    build_google_authorize_url,
    create_oauth_state_token,
    create_session_token,
    exchange_google_code_for_profile,
    get_or_create_google_user,
    verify_oauth_state_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class CurrentUserResponse(BaseModel):
    id: int
    email: str
    name: str


def _login_error_redirect(settings: Settings, error_code: str) -> RedirectResponse:
    query = urlencode({"error": error_code})
    response = RedirectResponse(
        url=f"{settings.frontend_url}/login?{query}",
        status_code=status.HTTP_302_FOUND,
    )
    response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/")
    return response


@router.get("/google/login")
def google_login(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    """구글 로그인 화면으로 이동하며 위조 방지용 state 쿠키를 함께 저장한다."""
    try:
        state_token = create_oauth_state_token(settings.session_secret)
        authorize_url = build_google_authorize_url(settings, state_token)
    except (SessionConfigError, OAuthConfigError):
        return _login_error_redirect(settings, "oauth_not_configured")

    response = RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state_token,
        max_age=OAUTH_STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


@router.get("/google/callback")
async def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    cookie_state: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """구글 OAuth 콜백을 처리해 계정을 확인·생성하고 httpOnly 세션 쿠키를 발급한다."""
    if error:
        return _login_error_redirect(settings, "oauth_access_denied")

    if not code or not state or not cookie_state:
        return _login_error_redirect(settings, "invalid_oauth_state")

    try:
        state_ok = verify_oauth_state_token(state, cookie_state, settings.session_secret)
    except SessionConfigError:
        return _login_error_redirect(settings, "oauth_not_configured")

    if not state_ok:
        return _login_error_redirect(settings, "invalid_oauth_state")

    try:
        profile = await exchange_google_code_for_profile(code, settings)
        user = get_or_create_google_user(db, profile)
        session_token = create_session_token(user.id, settings.session_secret)
    except OAuthConfigError:
        return _login_error_redirect(settings, "oauth_not_configured")
    except OAuthExchangeError as exc:
        return _login_error_redirect(settings, exc.reason_code)
    except Exception:
        db.rollback()
        return _login_error_redirect(settings, "login_failed")

    response = RedirectResponse(
        url=f"{settings.frontend_url}/home",
        status_code=status.HTTP_302_FOUND,
    )
    response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/")
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


@router.get("/me", response_model=CurrentUserResponse)
def read_current_user(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    """현재 로그인한 사용자 정보를 돌려준다. 비로그인 시 401을 반환한다."""
    return CurrentUserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(settings: Settings = Depends(get_settings)) -> Response:
    """세션 쿠키를 삭제하고 204를 돌려준다."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return response
