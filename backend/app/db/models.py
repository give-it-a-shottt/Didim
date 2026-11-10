from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    임베딩 벡터 컬럼은 2주차(F-003 RAG)에서 pgvector와 함께 붙인다.
    """

    __tablename__ = "chunks"

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
