import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import MAX_NOTE_LIST
from app.db.models import Chunk, Note, Quiz, User
from app.services.chunking import ChunkDraft


class DuplicateNoteError(ValueError):
    """같은 사용자가 이미 같은 원문(content_hash)의 노트를 올렸을 때 발생한다."""


class ChunkLocationError(ValueError):
    """조각 내용이 노트 원문의 [start_offset:end_offset] 구간과 다를 때 발생한다(근거 위치가 틀린 조각은 저장하지 않음)."""


def compute_content_hash(content: str) -> str:
    """노트 원문의 중복 여부를 확인하기 위한 SHA-256 해시를 계산한다."""
    normalized = content.strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _check_chunk_locations(content: str, chunks: Sequence[ChunkDraft]) -> None:
    for index, chunk in enumerate(chunks):
        if content[chunk.start_offset : chunk.end_offset] != chunk.content or chunk.start_offset >= chunk.end_offset:
            raise ChunkLocationError(f"{index}번째 조각의 위치가 원문과 맞지 않아요.")


def create_note_for_user(
    db: Session,
    *,
    user_id: int,
    title: str,
    content: str,
    source: str = "markdown",
    kind: str = "study",
    chunks: Sequence[ChunkDraft] = (),
    notion_page_id: str | None = None,
) -> Note:
    """특정 사용자의 노트(및 조각)를 저장한다. 항상 user_id를 함께 기록한다.

    조각은 원문의 구간이어야 한다(content == 원문[start:end]). 아니면 아무것도 저장하지 않고 ChunkLocationError.
    """
    _check_chunk_locations(content, chunks)
    content_hash = compute_content_hash(content)
    note = Note(
        user_id=user_id,
        title=title.strip(),
        content=content,
        source=source,
        kind=kind,
        content_hash=content_hash,
        notion_page_id=notion_page_id,
    )
    db.add(note)
    try:
        db.flush()
        for position, chunk in enumerate(chunks):
            db.add(
                Chunk(
                    user_id=user_id,
                    note_id=note.id,
                    position=position,
                    heading_path=chunk.heading_path,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    content=chunk.content,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateNoteError("이미 같은 내용의 노트가 등록되어 있어요.") from exc

    # commit 뒤에 다시 읽지(refresh) 않는다. 세션이 expire_on_commit=False라 id · 값이 그대로 남아 있고,
    # 다시 읽다 실패하면 "저장됐는데 실패로 보이는" 일이 생긴다(F-002 1차 R3-6).
    return note


def list_notes_for_user(db: Session, *, user_id: int) -> list[Note]:
    """로그인한 사용자의 노트 목록만 돌려준다 (D-004 사용자 데이터 분리)."""
    stmt = (
        select(Note)
        .where(Note.user_id == user_id)
        .order_by(Note.created_at.desc(), Note.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


@dataclass(frozen=True)
class NoteSummary:
    id: int
    title: str
    kind: str
    created_at: datetime
    chunk_count: int
    quiz_count: int


@dataclass(frozen=True)
class NoteSummaryPage:
    total: int  # 내 노트 전체 개수
    notes: list[NoteSummary]  # 최근 올린 것부터 최대 limit개


def list_note_summaries_for_user(db: Session, *, user_id: int, limit: int = MAX_NOTE_LIST) -> NoteSummaryPage:
    """기록 · 복습 홈 노트 목록(F-004). 원문은 빼고 제목 · 종류 · 조각 수 · 문제 수만.

    조각 · 문제 수는 노트마다 서브쿼리로 센다. 서브쿼리에도 user_id 조건을 건다(D-004 — 조각 · 문제는 노트 주인과
    user_id가 같게 저장되지만, 조건을 빼면 그 약속이 깨졌을 때 남의 수가 섞인다).
    """
    chunk_count = (
        select(func.count(Chunk.id))
        .where(Chunk.note_id == Note.id, Chunk.user_id == user_id)
        .correlate(Note)
        .scalar_subquery()
    )
    quiz_count = (
        select(func.count(Quiz.id))
        .where(Quiz.note_id == Note.id, Quiz.user_id == user_id)
        .correlate(Note)
        .scalar_subquery()
    )
    stmt = (
        select(Note.id, Note.title, Note.kind, Note.created_at, chunk_count, quiz_count)
        .where(Note.user_id == user_id)
        .order_by(Note.created_at.desc(), Note.id.desc())
        .limit(limit)
    )
    notes = [
        NoteSummary(id=row[0], title=row[1], kind=row[2], created_at=row[3], chunk_count=row[4], quiz_count=row[5])
        for row in db.execute(stmt).all()
    ]
    total = db.execute(select(func.count(Note.id)).where(Note.user_id == user_id)).scalar_one()
    return NoteSummaryPage(total=total, notes=notes)


def find_note_by_content_hash_for_user(db: Session, *, user_id: int, content_hash: str) -> Note | None:
    """같은 사용자가 같은 원문을 이미 올렸는지 찾는다(중복 안내용). 다른 사용자의 노트는 보지 않는다(D-004)."""
    stmt = select(Note).where(Note.user_id == user_id, Note.content_hash == content_hash)
    return db.execute(stmt).scalar_one_or_none()


def get_note_for_user(db: Session, *, user_id: int, note_id: int) -> Note | None:
    """노트 단건 조회에도 반드시 user_id 조건을 함께 걸어 남의 노트가 보이지 않게 한다."""
    stmt = select(Note).where(Note.id == note_id, Note.user_id == user_id)
    return db.execute(stmt).scalar_one_or_none()


def list_chunks_for_user(db: Session, *, user_id: int) -> list[Chunk]:
    """로그인한 사용자의 기록 조각만 돌려준다 (D-004 사용자 데이터 분리)."""
    stmt = (
        select(Chunk)
        .where(Chunk.user_id == user_id)
        .order_by(Chunk.note_id.asc(), Chunk.position.asc())
    )
    return list(db.execute(stmt).scalars().all())


def list_chunks_for_note_for_user(db: Session, *, user_id: int, note_id: int) -> list[Chunk]:
    """노트 하나의 조각을 순서대로 돌려준다. 노트 주인이 아니면 빈 목록(user_id 조건, D-004)."""
    stmt = (
        select(Chunk)
        .where(Chunk.user_id == user_id, Chunk.note_id == note_id)
        .order_by(Chunk.position.asc())
    )
    return list(db.execute(stmt).scalars().all())


def delete_user_account(db: Session, *, user_id: int) -> bool:
    """사용자를 삭제한다. 연결된 notes · chunks는 ON DELETE CASCADE로 함께 지워진다."""
    stmt = select(User).where(User.id == user_id)
    user = db.execute(stmt).scalar_one_or_none()
    if user is None:
        return False
    db.delete(user)
    db.commit()
    return True
