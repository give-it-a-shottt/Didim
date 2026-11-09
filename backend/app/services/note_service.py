import hashlib
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Chunk, Note, User


class DuplicateNoteError(ValueError):
    """같은 사용자가 이미 같은 원문(content_hash)의 노트를 올렸을 때 발생한다."""


def compute_content_hash(content: str) -> str:
    """노트 원문의 중복 여부를 확인하기 위한 SHA-256 해시를 계산한다."""
    normalized = content.strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def create_note_for_user(
    db: Session,
    *,
    user_id: int,
    title: str,
    content: str,
    source: str = "markdown",
    kind: str = "study",
    chunk_contents: Sequence[str] | None = None,
) -> Note:
    """특정 사용자의 노트(및 조각)를 저장한다. 항상 user_id를 함께 기록한다."""
    content_hash = compute_content_hash(content)
    note = Note(
        user_id=user_id,
        title=title.strip(),
        content=content,
        source=source,
        kind=kind,
        content_hash=content_hash,
    )
    db.add(note)
    try:
        db.flush()
        if chunk_contents:
            for idx, chunk_text in enumerate(chunk_contents):
                db.add(
                    Chunk(
                        user_id=user_id,
                        note_id=note.id,
                        position=idx,
                        content=chunk_text,
                    )
                )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateNoteError("이미 같은 내용의 노트가 등록되어 있어요.") from exc

    db.refresh(note)
    return note


def list_notes_for_user(db: Session, *, user_id: int) -> list[Note]:
    """로그인한 사용자의 노트 목록만 돌려준다 (D-004 사용자 데이터 분리)."""
    stmt = (
        select(Note)
        .where(Note.user_id == user_id)
        .order_by(Note.created_at.desc(), Note.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


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


def delete_user_account(db: Session, *, user_id: int) -> bool:
    """사용자를 삭제한다. 연결된 notes · chunks는 ON DELETE CASCADE로 함께 지워진다."""
    stmt = select(User).where(User.id == user_id)
    user = db.execute(stmt).scalar_one_or_none()
    if user is None:
        return False
    db.delete(user)
    db.commit()
    return True
