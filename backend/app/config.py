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
# DB 번호(id) 상한 — PostgreSQL integer(32비트). 이보다 큰 번호로 조회하면 DB가 "범위 초과"(500)를 내므로
# DB에 묻기 전에 "없음"(404)으로 답한다(F-003 1차 리뷰 E, 노트 · 문제 공용 — F-004 1차 리뷰 R1)
MAX_DB_ID = 2_147_483_647

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

# 퀴즈 · 복습 (F-004 설계 의도, 사용자 확인 2026-11-10 · 11)
MAX_QUIZZES_PER_NOTE = 10  # 노트당 최대 10개(조각마다 1개)
QUIZ_MIN_CHUNK_CHARS = 80  # 공백을 뺀 글자 수가 이보다 적은 조각은 건너뜀. 평가 뒤 조정
# 근거 인용 문장의 최소 길이(공백 뺀 글자 수). "React" 같은 낱말 하나로 근거 검사를 통과하지 않게
QUIZ_MIN_QUOTE_CHARS = 10
QUIZ_MAX_QUESTION_CHARS = 500
QUIZ_MAX_CHOICE_CHARS = 200
QUIZ_MAX_EXPLANATION_CHARS = 1000
QUIZ_MCQ_CHOICES = 4  # 객관식은 4지(D-006)
QUIZ_OX_CHOICES = ("O", "X")
# 복습 간격(일): 단계 0 → 당일, 1 → 1일, 2 → 3일, 3 → 7일, 4 → 14일 뒤
QUIZ_REVIEW_INTERVAL_DAYS = (0, 1, 3, 7, 14)
# [문제 만들기] 선점이 이보다 오래되면 서버가 도중에 죽은 것으로 보고 새 요청이 가져간다(초).
# AI 전체 시간 상한 180초(app/llm/settings.py) + 저장 여유. 사용자 확인 2026-11-11
QUIZ_CLAIM_STALE_SECONDS = 300
# '오늘 복습' 한 번에 보내는 문제 수 상한(오래 밀린 것부터). 전체 개수는 따로 알려 준다. 임시값 — 리뷰 때 확인
MAX_REVIEW_SESSION_QUIZZES = 100
# 기록 · 복습 홈 노트 목록에 한 번에 보내는 노트 수 상한(최근 올린 것부터). 전체 개수는 따로 알려 준다. 임시값 — 리뷰 때 확인
MAX_NOTE_LIST = 200

# 경험 카드 (F-006 설계 의도, 사용자 확인 2026-11-11)
# 칸 이름: 상황 · 과제 · 행동 · 결과. DB card_fields.slot과 API 경로 /fields/{slot}이 같이 쓴다.
CARD_SLOTS = ("situation", "task", "action", "result")
CARD_STATUS_CANDIDATE = "candidate"  # 후보 찾기로 생김, 검토 전
CARD_STATUS_SAVED = "saved"  # 사용자가 [저장]을 누름
# 카드 제목(AI 제안 → 저장 때 사용자 확인) 길이. (사용자 확인 2026-11-11, F-006 1차 리뷰)
CARD_TITLE_MAX_CHARS = 100
CARD_MAX_CANDIDATES_PER_NOTE = 3  # 노트당 후보 최대 3개 (사용자 확인 2026-11-11, F-006 1차 리뷰)
# [카드 후보 찾기]에 보내는 범위(원칙 6). 노트 앞에서부터 조각 순서대로, 둘 중 먼저 닿는 곳까지. (사용자 확인 2026-11-11, F-006 1차 리뷰)
CARD_MAX_CHUNKS_SENT = 40
CARD_MAX_CHARS_SENT = 12_000
# 원문 인용 길이(공백 뺀 최소 · 전체 최대). 낱말 하나로 근거 검사를 통과하거나 조각을 통째로 옮기지 않게. (사용자 확인 2026-11-11, F-006 1차 리뷰)
CARD_MIN_QUOTE_CHARS = 10
CARD_MAX_QUOTE_CHARS = 500
CARD_MAX_QUESTION_CHARS = 300  # 빈칸 질문 길이 상한. 넘거나 비면 아래 기본 질문을 쓴다
# AI가 질문을 주지 않거나 쓸 수 없을 때 빈칸에 보여 주는 고정 질문(AI가 만든 글이 아님)
CARD_DEFAULT_QUESTIONS = {
    "situation": "이 경험은 어떤 상황에서 시작됐나요?",
    "task": "그때 내가 맡은 일이나 풀어야 할 문제는 무엇이었나요?",
    "action": "문제를 풀려고 내가 직접 한 일은 무엇인가요?",
    "result": "그 결과 무엇이 달라졌나요?",
}
# 선점이 이보다 오래되면 서버가 도중에 죽은 것으로 보고 새 요청이 가져간다(초). 문제 만들기와 같은 이유 · 같은 값
CARD_CLAIM_STALE_SECONDS = QUIZ_CLAIM_STALE_SECONDS
CARD_MAX_ANSWER_CHARS = 2_000  # 칸 하나에 쓰는 내 답 길이 상한. (사용자 확인 2026-11-11, F-006 1차 리뷰)
MAX_CARD_LIST = 200  # 카드 목록 한 번에 보내는 수(최근 고친 것부터). 전체 개수는 따로 알려 준다. (사용자 확인 2026-11-11, F-006 1차 리뷰)


# 노션 연결 (F-005 설계 의도, 사용자 확인 2026-11-12)
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2026-03-11"  # 요청 머리말 Notion-Version. 이 버전부터 archived 대신 in_trash
NOTION_HTTP_TIMEOUT_SECONDS = 15.0
# 노션 호출 한도는 평균 초당 약 3번. 요청 사이를 이만큼 띄운다(초).
NOTION_MIN_REQUEST_INTERVAL_SECONDS = 0.34
NOTION_MAX_RETRIES = 2  # 429 · 5xx · 연결 실패면 다시 해 볼 횟수
NOTION_MAX_RETRY_WAIT_SECONDS = 10.0  # 429의 Retry-After가 이보다 길면 이만큼만 기다린다
NOTION_SERVER_ERROR_RETRY_WAIT_SECONDS = 1.0  # 5xx · 연결 실패 뒤 다시 하기 전 쉬는 시간
NOTION_MIN_REQUEST_SECONDS = 1.0  # 마감까지 이보다 적게 남았으면 새 요청을 보내지 않는다(받기 전에 끊김)
NOTION_API_PAGE_SIZE = 100  # 노션 API 한 번에 받는 최대 개수(검색 · 블록 목록)
NOTION_WORKSPACE_ID_MAX_CHARS = 64  # DB notion_connections 칸 길이(workspace_id · bot_id)
NOTION_WORKSPACE_NAME_MAX_CHARS = 255
# 토큰 만료 시각이 이만큼 남았으면 미리 갱신한다(초). 만료 시각을 모르면 401을 받았을 때 한 번 갱신한다.
NOTION_TOKEN_REFRESH_MARGIN_SECONDS = 60
NOTION_STATE_COOKIE_NAME = "didim_notion_state"
NOTION_STATE_MAX_AGE_SECONDS = 60 * 10  # 10분
NOTION_STATUS_CONNECTED = "connected"
NOTION_STATUS_BROKEN = "broken"  # 갱신 실패 — 설정에서 다시 연결
# 아래 상한값은 사용자 확인(2026-11-12, F-005 1차 리뷰 E)
NOTION_MAX_PAGE_LIST = 100  # 가져올 페이지 목록에 보여 주는 수(최근 수정한 것부터)
NOTION_MAX_IMPORT_PAGES = 20  # 한 번에 가져오는 페이지 수 — 마크다운 파일 상한과 같은 값
NOTION_MAX_BLOCKS_PER_PAGE = 2_000  # 페이지 하나에서 읽는 블록 수 상한. 넘으면 그 페이지만 실패
NOTION_MAX_BLOCK_DEPTH = 6  # 토글 · 목록 안쪽으로 내려가는 깊이 상한
# 가져오기 한 번의 시간 예산(초). 넘으면 남은 페이지는 시작하지 않고 실패로 알려 준다.
# Next 프록시 상한 200초(frontend/next.config.ts, T-005) 안에서 끝나게.
# 마감은 노션 호출 '사이'뿐 아니라 호출 하나 안에서도 지킨다(요청 시간 상한 · 재시도 대기를 남은 시간으로 자름, 1차 리뷰 C).
# 요청이 들어온 시각부터 센다. httpx 시간 상한은 연결 · 읽기 단계마다 따로라 요청 하나가 상한을 조금 넘을 수 있어
# 150초에서 140초로 낮췄다(2차 리뷰 R2, 사용자 확인 범위 — "C를 고치며 더 낮출 수 있음").
NOTION_IMPORT_TIME_BUDGET_SECONDS = 140.0
# 사용자당 가져오기 하나(1차 리뷰 D, 사용자 선택). 이보다 오래된 '가져오는 중' 표시는 서버가 도중에 죽은 것으로 보고 새 요청이 가져간다(초).
NOTION_IMPORT_CLAIM_STALE_SECONDS = 300
NOTION_PAGE_ID_LENGTH = 36  # 하이픈 있는 UUID (DB notes.notion_page_id 길이)
NOTION_MAX_PAGE_ID_INPUT_CHARS = 64  # 요청의 페이지 번호 한 개 길이 상한(형식 검사 전, 1차 리뷰 R2)


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_secret: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    frontend_url: str
    cookie_secure: bool
    # 노션 연결(F-005). 비어 있으면 연결 버튼이 "설정이 아직 안 됐어요"로 안내한다.
    notion_client_id: str = ""
    notion_client_secret: str = ""
    notion_redirect_uri: str = "http://localhost:3000/api/notion/callback"
    # 노션 토큰 암호화 키(Fernet, base64 32바이트). 만들기: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    notion_token_key: str = ""

    @property
    def notion_configured(self) -> bool:
        return bool(self.notion_client_id and self.notion_client_secret and self.notion_token_key)


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
        notion_client_id=os.getenv("NOTION_CLIENT_ID", "").strip(),
        notion_client_secret=os.getenv("NOTION_CLIENT_SECRET", "").strip(),
        # 노션은 http 리디렉트를 localhost에만 허용한다(127.0.0.1 안 됨). 노션에 등록한 주소와 한 글자도 같아야 한다.
        notion_redirect_uri=os.getenv(
            "NOTION_REDIRECT_URI",
            "http://localhost:3000/api/notion/callback",
        ).strip(),
        notion_token_key=os.getenv("NOTION_TOKEN_KEY", "").strip(),
    )
