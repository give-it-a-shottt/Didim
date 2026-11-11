from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import CARD_TITLE_MAX_CHARS, DEFAULT_DAILY_LIMIT, NOTE_TITLE_MAX_CHARS
from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """계정 테이블 (data-model.md — 1주차 생성).

    사용자를 삭제하면 연결된 notes · chunks가 DB 외래키(ON DELETE CASCADE)로 함께 지워진다.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=DEFAULT_DAILY_LIMIT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    notes: Mapped[list["Note"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Note(Base):
    """가져온 기록 원문 테이블 (data-model.md — 1주차 생성).

    모든 조회는 반드시 user_id 조건을 함께 건다 (D-004).
    """

    __tablename__ = "notes"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_notes_user_content_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(NOTE_TITLE_MAX_CHARS), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    user: Mapped["User"] = relationship(back_populates="notes")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="note",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Chunk(Base):
    """기록 조각 테이블 (data-model.md — 1주차 생성, 위치 컬럼은 F-002 · 버전 0002).

    조각은 노트 원문의 한 구간이다: content == note.content[start_offset:end_offset].
    위치는 파이썬 문자 단위(유니코드 코드 포인트)다. 근거를 "어느 노트의 어느 제목 아래, 원문 몇 번째 글자"로
    보여 주기 위해 저장한다(설계 원칙 1, D-003).
    검색(F-003)은 "사용자 + 본문" GIN 색인을 쓴다(버전 0003). 임베딩 컬럼은 평가로 비교한 뒤에 붙인다(D-016).
    """

    __tablename__ = "chunks"
    __table_args__ = (
        # 키워드 검색용 색인: 사용자 조건(btree_gin)과 본문 비슷함(pg_trgm)을 GIN 하나로 같이 거른다.
        # 따로 두면 PostgreSQL이 user_id 색인으로 내 조각을 전부 읽고 행마다 비슷함을 계산하는 계획을 골랐다
        # (사용자당 조각 5천에서 맞는 게 없어도 476ms → 합친 색인 1ms, F-003 1차 리뷰 뒤 실측 · 사용자 확인).
        # SQLite(테스트)에서는 보통 (user_id, content) 색인으로 만들어진다.
        Index(
            "ix_chunks_user_content_trgm",
            "user_id",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    note_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # 조각이 속한 제목 경로. 예) "# React > ## useEffect". 첫 제목 앞의 글이면 빈 문자열.
    heading_path: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    note: Mapped["Note"] = relationship(back_populates="chunks")


class SearchLog(Base):
    """기록 검색 로그 (F-003, 버전 0003).

    검색마다 질문 · 방식 · 결과(조각 ID와 점수)를 남겨 평가 세트로 채점할 수 있게 한다(D-005, 설계 원칙 5).
    사용자를 지우면 DB 외래키(ON DELETE CASCADE)로 같이 지워진다. 조회는 반드시 user_id 조건을 건다(D-004).
    """

    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    # 검색 방식 이름(예: "keyword"). 임베딩을 붙이면 방식별로 점수를 비교한다(D-016).
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    # [{"chunk_id": 1, "score": 0.82}, ...] — 순위 순서. 조각이 나중에 지워져도 로그는 남는다.
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class AIUsageLog(Base):
    """AI 사용량 기록 (D-018, 버전 0004). 모든 AI 기능이 같이 쓴다.

    AI를 부른 요청 하나마다 한 줄. 하루 상한(users.daily_limit)은 오늘(한국 시간 0시부터) calls 합계로 센다.
    보낸 내용 · 받은 내용 · API 키는 넣지 않는다(F-014 오류 문구 규칙과 같음).
    """

    __tablename__ = "ai_usage_logs"
    __table_args__ = (Index("ix_ai_usage_logs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # 어느 기능이 불렀는지(예: "quiz_generate"). 사용량 화면(7주차)에서 기능별로 나눠 보여 준다.
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    # 실제 HTTP 호출 수(연결 재시도 · 형식 재요청 · 실패한 호출 포함 — F-014 usage.calls)
    calls: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 결과 종류만(ok · invalid_output · rate_limited · unavailable · config_error · request_error · error · save_failed)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class Quiz(Base):
    """복습 문제 (F-004, 버전 0004).

    객관식 · OX 모두 "보기 목록 + 정답 번호"로 저장한다(OX는 보기 ["O", "X"]). 채점 규칙이 하나로 같다.
    근거(설계 원칙 1, D-003): 근거 조각(chunk_id)과, 정답의 근거가 되는 원문 문장(quote)과 그 위치를 같이 둔다.
    quote == note.content[quote_start:quote_end] (파이썬 문자 단위, chunks의 위치와 같은 단위).
    노트 · 조각이 지워지면 문제도 같이 지워진다(노트는 편집할 수 없어서 근거가 바뀌는 경우가 없다).
    조각마다 문제는 하나(chunk_id 유니크) — 동시에 두 번 만들어도 DB가 막는 안전망(동시 클릭 1차 방어는 note_quiz_claims).
    """

    __tablename__ = "quizzes"
    __table_args__ = (UniqueConstraint("chunk_id", name="uq_quizzes_chunk_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[int] = mapped_column(Integer, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # "mcq"(4지 객관식) · "ox"
    question: Mapped[str] = mapped_column(Text, nullable=False)
    choices: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    answer_index: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_start: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_end: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class NoteQuizClaim(Base):
    """노트별 [문제 만들기] 선점 (F-004, 버전 0004 — 동시 클릭 막기, 사용자 확인 2026-11-11).

    AI를 부르기 전에 노트당 한 줄을 넣고 커밋한다(note_id 유니크). 동시에 들어온 두 번째 요청은 유니크 제약에 걸려
    AI를 부르지 않고 409로 끝난다 — AI 호출(최대 180초) 동안 DB를 잠그지 않으면서 한 번만 부르게 하는 방법.
    - AI 실패 · 문제가 모두 버려짐 · 저장 실패 → 선점을 지워 다시 누를 수 있게 한다.
    - 성공 → 선점을 남긴다("이 노트는 문제가 있음" 표시).
    - 서버가 도중에 죽어 남은 선점은 QUIZ_CLAIM_STALE_SECONDS(5분)가 지나면 새 요청이 가져간다.
    """

    __tablename__ = "note_quiz_claims"
    __table_args__ = (UniqueConstraint("note_id", name="uq_note_quiz_claims_note_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note_id: Mapped[int] = mapped_column(Integer, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class QuizReview(Base):
    """문제마다 하나인 복습 상태 (F-004, 버전 0004).

    문제 내용(AI가 만든 것 + 근거)과 학습 상태(사용자 활동)를 나눠 둔다(사용자 확인, 2026-11-11).
    next_review_on은 한국 날짜다(D-018과 같은 하루 기준). '오늘 복습' = next_review_on <= 오늘.
    interval_step: 0 → 당일, 1 → 1일, 2 → 3일, 3 → 7일, 4 → 14일 뒤.
    """

    __tablename__ = "quiz_reviews"
    __table_args__ = (
        UniqueConstraint("quiz_id", name="uq_quiz_reviews_quiz_id"),  # 문제마다 복습 상태는 하나
        Index("ix_quiz_reviews_user_next", "user_id", "next_review_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    quiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    next_review_on: Mapped[date] = mapped_column(Date, nullable=False)
    interval_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_wrong_notes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class QuizAttempt(Base):
    """문제를 푼 기록 (F-004, 버전 0004). 답할 때마다 한 줄 — 복습 상태의 근거이자 이후 통계용."""

    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quiz_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chosen_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class QuizGenerationLog(Base):
    """문제 만들기 평가 로그 (F-004 완료 기준 2 · 7, 설계 원칙 5, 버전 0004).

    [문제 만들기] 한 번마다 보낸 조각 수 · 남긴 수 · 버린 수와 이유를 남긴다. 호출 · 토큰은 ai_usage_logs(D-018).
    note_id는 외래키가 아니다: 노트가 지워져도 평가 로그는 남긴다(search_logs의 조각 ID와 같은 방식).
    """

    __tablename__ = "quiz_generation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chunks_sent: Mapped[int] = mapped_column(Integer, nullable=False)
    kept: Mapped[int] = mapped_column(Integer, nullable=False)
    dropped: Mapped[int] = mapped_column(Integer, nullable=False)
    # 버린 이유별 개수. 예) {"quote_not_found": 2, "bad_answer_index": 1}
    drop_reasons: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class Card(Base):
    """경험 카드 (F-006, 버전 0005).

    [카드 후보 찾기]로 'candidate'(후보)가 생기고, 사용자가 [저장]하면 'saved'가 된다. 카드는 후보에서만 생긴다.
    본문은 칸(card_fields)에 있다. 카드에는 원문 인용 · 사용자 답 · 근거 링크만 저장한다(D-003).
    title은 AI가 제안하고 저장 때 사용자가 확인 · 수정하는 이름표다 — 자소서 근거로 쓰지 않는다(사용자 확인 2026-11-11).
    note_id는 SET NULL: 노트가 지워져도 사용자 답이 든 카드는 남고 근거만 '원문 없음'이 된다.
    """

    __tablename__ = "cards"
    __table_args__ = (Index("ix_cards_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    note_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("notes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(CARD_TITLE_MAX_CHARS), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # "candidate" · "saved"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    fields: Mapped[list["CardField"]] = relationship(
        back_populates="card",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CardField(Base):
    """카드의 한 칸 + 그 칸의 근거 (F-006, 버전 0005). 카드마다 4줄(situation · task · action · result).

    한 칸에 세 가지를 따로 둔다(사용자 확인 2026-11-11 — 인용은 고정 + 내 답 덧붙이기):
    - 원문 인용(quote · quote_start · quote_end · chunk_id): AI가 고른 내 노트 문장. 서버가 원문에 글자 그대로 있는지
      확인한 것만 남는다. quote == notes.content[quote_start:quote_end] (파이썬 문자 단위, quizzes와 같음).
      사용자는 고칠 수 없고 [인용 빼기]로 지울 수만 있다.
    - question: 빈칸일 때 AI가 묻는 질문. 화면에만 보여 주고 카드 내용으로 쓰지 않는다.
    - answer: 사용자가 쓴 답.
    빈칸 = 인용도 답도 없음. 근거 수 = 인용이 있는 칸 수. 처음 계획한 card_evidence를 여기에 합쳤다(근거가 칸 단위).
    chunk_id는 SET NULL: 조각이 지워져도 칸(사용자 답)은 남는다.
    """

    __tablename__ = "card_fields"
    __table_args__ = (UniqueConstraint("card_id", "slot", name="uq_card_fields_card_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_id: Mapped[int] = mapped_column(Integer, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False)
    slot: Mapped[str] = mapped_column(String(16), nullable=False)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    card: Mapped["Card"] = relationship(back_populates="fields")


class NoteCardClaim(Base):
    """노트별 [카드 후보 찾기] 선점 (F-006, 버전 0005 — note_quiz_claims 구조 + finished_at).

    AI를 부르기 전에 노트당 한 줄을 넣고 커밋한다(note_id 유니크). 동시에 두 번 눌러도 AI는 한 번만 부른다.
    - finished_at 비어 있음 = 찾는 중(5분 지나면 새 요청이 가져감).
    - finished_at 있음 = 이미 찾은 노트 → 409. 후보를 모두 버려도 남는다(카드 유무로는 알 수 없어서 — 사용자 확인 2026-11-11).
    - AI 실패 · 후보 0개 · 저장 실패 → 선점을 지워 다시 누를 수 있게 한다(사용자 확인 2026-11-11).
    """

    __tablename__ = "note_card_claims"
    __table_args__ = (UniqueConstraint("note_id", name="uq_note_card_claims_note_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note_id: Mapped[int] = mapped_column(Integer, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CardGenerationLog(Base):
    """카드 후보 찾기 평가 로그 (F-006 완료 기준 7, 설계 원칙 5, 버전 0005).

    [카드 후보 찾기] 한 번마다 보낸 조각 수 · 남긴 후보 수 · 인용이 들어간 칸 수 · 인용 검사로 빈칸이 된 칸 수와
    이유를 남긴다. 호출 · 토큰은 ai_usage_logs(D-018). note_id는 외래키가 아니다(노트가 지워져도 로그는 남김).
    """

    __tablename__ = "card_generation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chunks_sent: Mapped[int] = mapped_column(Integer, nullable=False)
    candidates: Mapped[int] = mapped_column(Integer, nullable=False)
    quoted_fields: Mapped[int] = mapped_column(Integer, nullable=False)
    emptied_fields: Mapped[int] = mapped_column(Integer, nullable=False)
    # 빈칸으로 돌리거나 버린 이유별 개수. 예) {"quote_not_found": 2, "no_quote_and_no_question": 1}
    drop_reasons: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


# pg_trgm · btree_gin 확장은 테이블보다 먼저 있어야 검색 색인을 만들 수 있다. create_all(테스트)도 같은 순서를 따르게 한다.
# 실제 DB는 버전 파일 0003이 확장을 설치한다.
for _extension in ("pg_trgm", "btree_gin"):
    event.listen(
        Base.metadata,
        "before_create",
        DDL(f"CREATE EXTENSION IF NOT EXISTS {_extension}").execute_if(dialect="postgresql"),
    )
