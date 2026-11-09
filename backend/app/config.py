import os
from dataclasses import dataclass

# 쿠키 이름과 만료 시간 상수 (매직 넘버 방지)
SESSION_COOKIE_NAME = "didim_session"
OAUTH_STATE_COOKIE_NAME = "didim_oauth_state"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7일
OAUTH_STATE_MAX_AGE_SECONDS = 60 * 10  # 10분
MIN_SESSION_SECRET_LENGTH = 32

# 사용자 기본 하루 AI 호출 상한 (didim-design.md SET_01_001 기준 30회)
DEFAULT_DAILY_LIMIT = 30


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_secret: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    frontend_url: str
    cookie_secure: bool


def load_settings() -> Settings:
    """환경변수에서 서버 설정을 읽는다. 비밀키는 코드에 기본값을 두지 않는다."""
    raw_secure = os.getenv("COOKIE_SECURE", "false").strip().lower()
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./didim_local.db").strip(),
        session_secret=os.getenv("SESSION_SECRET", "").strip(),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        google_redirect_uri=os.getenv(
            "GOOGLE_REDIRECT_URI",
            "http://localhost:3000/api/auth/google/callback",
        ).strip(),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:3000").strip().rstrip("/"),
        cookie_secure=raw_secure in ("1", "true", "yes"),
    )
