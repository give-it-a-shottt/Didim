import os
from dataclasses import dataclass

# 쿠키 이름과 만료 시간 상수 (매직 넘버 방지)
SESSION_COOKIE_NAME = "didim_session"
OAUTH_STATE_COOKIE_NAME = "didim_oauth_state"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7일
OAUTH_STATE_MAX_AGE_SECONDS = 60 * 10  # 10분
MIN_SESSION_SECRET_LENGTH = 32
# DB 연결을 기다리는 최대 시간. 없으면 연결이 응답 없이 끝없이 멈출 수 있다(T-002).
DB_CONNECT_TIMEOUT_SECONDS = 5

# 사용자 기본 하루 AI 호출 상한 (didim-design.md SET_01_001 기준 30회)
DEFAULT_DAILY_LIMIT = 30

BYTES_PER_MB = 1024 * 1024

# 노트 제목 길이. DB 컬럼(app/db/models.py Note.title)과 가져오기 어댑터가 같이 쓴다.
NOTE_TITLE_MAX_CHARS = 255

# 기록 가져오기 상한 (F-002 설계 의도, 사용자 확인). 화면(frontend/src/lib/import-records.ts)에도 같은 값이 있다.
MAX_IMPORT_FILES = 20
MAX_IMPORT_FILE_BYTES = 1 * BYTES_PER_MB  # 파일당 1MB
MAX_IMPORT_TOTAL_BYTES = MAX_IMPORT_FILES * MAX_IMPORT_FILE_BYTES  # 파일 합계 20MB
# 요청 본문 전체 상한: 파일 합계 + 여러 파일을 묶는 형식(multipart)의 머리말 몫 1MB
MAX_IMPORT_REQUEST_BYTES = MAX_IMPORT_TOTAL_BYTES + 1 * BYTES_PER_MB
# 조각 기준 길이(글자 수). 넘으면 문단 경계에서 다시 자른다. 임시값 — 2주차 검색 품질을 보고 조정.
CHUNK_MAX_CHARS = 1500
# 노트 하나의 조각 수 상한(사용자 확인, F-002 1차 리뷰). 넘으면 그 파일만 실패. 2주차 임베딩 비용 상한도 된다.
MAX_CHUNKS_PER_NOTE = 2000
# 제목 경로에 넣는 제목 한 단계의 글자 수 상한. 긴 제목이 조각마다 복사돼 커지는 것을 막는다(F-002 1차 R2).
HEADING_PATH_TEXT_MAX_CHARS = 200

# 기록 검색 (F-003 설계 의도, 사용자 확인). 검색창(frontend REV_01_001)도 같은 글자 수 상한을 쓴다.
MAX_SEARCH_QUERY_CHARS = 200
MAX_SEARCH_RESULTS = 5  # 완료 기준 1: 최대 5개
# 질문에서 쓰는 낱말 수 · 최소 글자 수. 낱말마다 조건이 하나씩 붙으므로 개수를 막아 둔다.
MAX_SEARCH_TERMS = 10
MIN_SEARCH_TERM_CHARS = 2
# 결과 줄에 보여 줄 발췌 길이(글자 수)와, 찾은 낱말 앞에 남길 글자 수
SEARCH_EXCERPT_CHARS = 160
SEARCH_EXCERPT_LEAD_CHARS = 40
# 검색 한 번의 DB 시간 상한(밀리초). 넘으면 멈추고 다시 찾아 달라고 안내한다(F-003 1차 리뷰 A, 사용자 확인 3초).
SEARCH_TIMEOUT_MS = 3000
# 낱말이 조각 안의 구간과 이 정도 이상 비슷해야 "맞음"으로 본다(pg_trgm word_similarity, 기본값과 같은 0.6).
# 검색할 때 DB 설정(pg_trgm.word_similarity_threshold)도 이 값으로 맞춰, 색인 조건과 점수 기준이 어긋나지 않게 한다.
SEARCH_WORD_SIMILARITY_THRESHOLD = 0.6
# 검색 로그 · 평가 결과에 남기는 점수 자릿수
SEARCH_SCORE_DIGITS = 4


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
        # DB는 PostgreSQL(D-008). 기본값을 두지 않는다: 비어 있으면 조용히 다른 DB로 넘어가지 않고 시작할 때 멈춘다.
        database_url=os.getenv("DATABASE_URL", "").strip(),
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
