import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import (
    MIN_SESSION_SECRET_LENGTH,
    OAUTH_STATE_MAX_AGE_SECONDS,
    SESSION_MAX_AGE_SECONDS,
    Settings,
)
from app.db.models import User

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_OAUTH_SCOPE = "openid email profile"
GOOGLE_HTTP_TIMEOUT_SECONDS = 10.0

PURPOSE_SESSION = "session"
PURPOSE_OAUTH_STATE = "oauth_state"


class SessionConfigError(RuntimeError):
    """SESSION_SECRET 환경변수가 비어 있거나 너무 짧을 때 발생한다."""


class OAuthConfigError(RuntimeError):
    """구글 OAuth 환경변수가 설정되지 않았을 때 발생한다."""


class OAuthExchangeError(RuntimeError):
    """구글 OAuth 토큰 교환이나 사용자 정보 조회가 실패했을 때 발생한다."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class GoogleProfile:
    sub: str
    email: str
    name: str


def _require_secret(secret: str) -> bytes:
    if len(secret) < MIN_SESSION_SECRET_LENGTH:
        raise SessionConfigError(
            f"환경변수 SESSION_SECRET은 최소 {MIN_SESSION_SECRET_LENGTH}자 이상이어야 해요."
        )
    return secret.encode("utf-8")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode((encoded + padding).encode("ascii"))


def _sign_payload(payload: dict[str, object], secret: str) -> str:
    key = _require_secret(secret)
    body_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = _b64url_encode(body_bytes)
    sig = hmac.new(key, body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{body_b64}.{_b64url_encode(sig)}"


def _verify_payload(token: str, secret: str, expected_purpose: str) -> dict[str, object] | None:
    key = _require_secret(secret)
    if not token.isascii():
        # 우리가 만든 토큰은 base64url(ASCII)뿐이다. 다른 글자가 있으면 위조로 보고 401 쪽(None)으로 보낸다.
        # (아래 encode("ascii")에서 예외가 나 500 · ERROR 로그가 되던 것을 막음, F-002 3차 R2)
        return None
    parts = token.split(".")
    if len(parts) != 2:
        return None
    body_b64, sig_b64 = parts
    if not body_b64 or not sig_b64:
        return None

    expected_sig = hmac.new(key, body_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
        raw_body = _b64url_decode(body_b64)
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return None

    if not hmac.compare_digest(expected_sig, actual_sig):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("purpose") != expected_purpose:
        return None

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None

    return payload


def create_session_token(
    user_id: int,
    secret: str,
    *,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
) -> str:
    """user_id와 만료 시각을 담아 서명한 세션 토큰을 만든다."""
    payload: dict[str, object] = {
        "purpose": PURPOSE_SESSION,
        "uid": user_id,
        "exp": int(time.time()) + max_age_seconds,
    }
    return _sign_payload(payload, secret)


def verify_session_token(token: str, secret: str) -> int | None:
    """세션 토큰 서명과 만료 시각을 검증해 user_id를 돌려준다. 위조·만료면 None."""
    payload = _verify_payload(token, secret, PURPOSE_SESSION)
    if payload is None:
        return None
    uid = payload.get("uid")
    if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
        return None
    return uid


def create_oauth_state_token(
    secret: str,
    *,
    max_age_seconds: int = OAUTH_STATE_MAX_AGE_SECONDS,
) -> str:
    """OAuth 로그인 요청 위조(CSRF)를 막기 위한 서명된 state 토큰을 만든다."""
    payload: dict[str, object] = {
        "purpose": PURPOSE_OAUTH_STATE,
        "nonce": secrets.token_urlsafe(24),
        "exp": int(time.time()) + max_age_seconds,
    }
    return _sign_payload(payload, secret)


def verify_oauth_state_token(
    query_state: str,
    cookie_state: str,
    secret: str,
) -> bool:
    """콜백 쿼리의 state와 쿠키의 state가 일치하고 만료되지 않았는지 검증한다."""
    if not query_state or not cookie_state:
        return False
    if not hmac.compare_digest(query_state, cookie_state):
        return False
    return _verify_payload(query_state, secret, PURPOSE_OAUTH_STATE) is not None


def build_google_authorize_url(settings: Settings, state: str) -> str:
    """구글 OAuth 동의 화면 주소를 만든다."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise OAuthConfigError("GOOGLE_CLIENT_ID와 GOOGLE_CLIENT_SECRET 환경변수가 필요해요.")

    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_OAUTH_SCOPE,
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{GOOGLE_AUTH_ENDPOINT}?{query}"


async def exchange_google_code_for_profile(code: str, settings: Settings) -> GoogleProfile:
    """구글 인가 코드를 액세스 토큰으로 바꾸고 사용자 프로필(sub, email, name)을 가져온다."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise OAuthConfigError("GOOGLE_CLIENT_ID와 GOOGLE_CLIENT_SECRET 환경변수가 필요해요.")

    try:
        async with httpx.AsyncClient(timeout=GOOGLE_HTTP_TIMEOUT_SECONDS) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                raise OAuthExchangeError("token_exchange_failed")

            token_data = token_resp.json()
            access_token = token_data.get("access_token") if isinstance(token_data, dict) else None
            if not isinstance(access_token, str) or not access_token:
                raise OAuthExchangeError("token_exchange_failed")

            userinfo_resp = await client.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_resp.status_code != 200:
                raise OAuthExchangeError("userinfo_failed")

            profile_data = userinfo_resp.json()
    except OAuthExchangeError:
        raise
    except httpx.HTTPError as exc:
        raise OAuthExchangeError("oauth_network_error") from exc
    except ValueError as exc:
        raise OAuthExchangeError("invalid_oauth_response") from exc

    if not isinstance(profile_data, dict):
        raise OAuthExchangeError("invalid_profile")

    sub = str(profile_data.get("sub") or "").strip()
    email = str(profile_data.get("email") or "").strip()
    raw_name = str(profile_data.get("name") or "").strip()
    email_verified = profile_data.get("email_verified")

    if not sub or not email or email_verified is False:
        raise OAuthExchangeError("invalid_profile")

    name = raw_name or email.split("@")[0]
    return GoogleProfile(sub=sub, email=email, name=name[:100])


def get_or_create_google_user(db: Session, profile: GoogleProfile) -> User:
    """google_sub 기준으로 계정을 찾고, 없으면 새로 만든다."""
    stmt = select(User).where(User.google_sub == profile.sub)
    existing = db.execute(stmt).scalar_one_or_none()
    if existing is not None:
        if existing.email != profile.email or existing.name != profile.name:
            existing.email = profile.email
            existing.name = profile.name
            db.commit()
            db.refresh(existing)
        return existing

    user = User(
        google_sub=profile.sub,
        email=profile.email,
        name=profile.name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # 동시에 같은 google_sub로 가입 요청이 들어온 경우 롤백 후 기존 계정을 조회한다.
        db.rollback()
        raced = db.execute(stmt).scalar_one_or_none()
        if raced is not None:
            return raced
        raise

    db.refresh(user)
    return user


def get_user_by_id(db: Session, user_id: int) -> User | None:
    """ID로 사용자를 조회한다."""
    stmt = select(User).where(User.id == user_id)
    return db.execute(stmt).scalar_one_or_none()
