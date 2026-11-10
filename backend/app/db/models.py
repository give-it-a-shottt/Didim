from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DDL, JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import DEFAULT_DAILY_LIMIT, NOTE_TITLE_MAX_CHARS
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


# pg_trgm · btree_gin 확장은 테이블보다 먼저 있어야 검색 색인을 만들 수 있다. create_all(테스트)도 같은 순서를 따르게 한다.
# 실제 DB는 버전 파일 0003이 확장을 설치한다.
for _extension in ("pg_trgm", "btree_gin"):
    event.listen(
        Base.metadata,
        "before_create",
        DDL(f"CREATE EXTENSION IF NOT EXISTS {_extension}").execute_if(dialect="postgresql"),
    )
