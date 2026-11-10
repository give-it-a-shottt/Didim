"""기록 가져오기 (F-002, 1주차: 읽기 · 나누기).

파일마다 따로 처리하고 따로 저장한다(완료 기준 4: 일부가 실패해도 성공한 파일은 남는다).
한 파일의 순서: 파일 이름 정리 → 읽기(어댑터) → 중복 확인 → 나누기 → 조각 수 확인 → 저장.
'만들기'(퀴즈 · 카드 후보)는 3 · 4주차에 이 뒤에 붙인다.
"""

import logging
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import MAX_CHUNKS_PER_NOTE
from app.importers.base import ImportedDocument, UnreadableFileError
from app.importers.markdown import clean_filename, read_markdown_file
from app.services.chunking import TooManyChunksError, split_markdown
from app.services.note_service import (
    ChunkLocationError,
    DuplicateNoteError,
    compute_content_hash,
    create_note_for_user,
    find_note_by_content_hash_for_user,
)

logger = logging.getLogger(__name__)

NoteKind = Literal["study", "project"]  # 학습 노트 / 프로젝트 · 경험. '자동'은 AI 단계 때 추가(F-002 설계 의도)
SAVE_FAILED_REASON = "저장하지 못했어요. 잠시 후 다시 시도해 주세요."
NO_BODY_REASON = "나눌 본문이 없어요. 제목만 있는 파일은 저장하지 않아요."
TOO_MANY_CHUNKS_REASON = f"조각이 너무 많아요({MAX_CHUNKS_PER_NOTE:,}개 초과). 파일을 나눠서 올려 주세요."


@dataclass(frozen=True)
class IncomingFile:
    """올라온 파일 하나. filename은 브라우저가 보낸 그대로, data는 앞부분 최대 (파일 상한 + 1)바이트."""

    filename: str | None
    data: bytes


@dataclass(frozen=True)
class ImportedNote:
    filename: str
    note_id: int
    title: str
    chunk_count: int


@dataclass(frozen=True)
class DuplicateFile:
    filename: str
    existing_note_id: int
    existing_title: str


@dataclass(frozen=True)
class FailedFile:
    filename: str
    reason: str


@dataclass
class ImportResult:
    imported: list[ImportedNote] = field(default_factory=list)
    duplicates: list[DuplicateFile] = field(default_factory=list)
    failed: list[FailedFile] = field(default_factory=list)

    @property
    def chunk_count(self) -> int:
        return sum(note.chunk_count for note in self.imported)


def import_markdown_files(
    db: Session,
    *,
    user_id: int,
    kind: NoteKind,
    files: list[IncomingFile],
) -> ImportResult:
    """로그인한 사용자(user_id)의 노트로 마크다운 파일들을 가져온다. user_id는 서버가 세션에서 꺼낸 값만 쓴다(D-004)."""
    result = ImportResult()
    for incoming in files:
        _import_one(db, user_id=user_id, kind=kind, incoming=incoming, result=result)
    return result


def _existing_duplicate(db: Session, *, user_id: int, filename: str, document: ImportedDocument) -> DuplicateFile | None:
    """같은 사용자가 같은 원문을 이미 올렸으면 그 노트를 알려 준다. 다른 사용자의 노트는 보지 않는다(D-004)."""
    existing = find_note_by_content_hash_for_user(
        db, user_id=user_id, content_hash=compute_content_hash(document.content)
    )
    if existing is None:
        return None
    return DuplicateFile(filename=filename, existing_note_id=existing.id, existing_title=existing.title)


def _import_one(db: Session, *, user_id: int, kind: NoteKind, incoming: IncomingFile, result: ImportResult) -> None:
    filename = clean_filename(incoming.filename)
    try:
        document = read_markdown_file(filename, incoming.data)
    except UnreadableFileError as exc:
        result.failed.append(FailedFile(filename=filename, reason=str(exc)))
        return

    # 같은 요청 안에서 먼저 저장한 파일도 DB에서 찾힌다(파일마다 저장하므로).
    duplicate = _existing_duplicate(db, user_id=user_id, filename=filename, document=document)
    if duplicate is not None:
        result.duplicates.append(duplicate)
        return

    try:
        chunks = split_markdown(document.content, max_chunks=MAX_CHUNKS_PER_NOTE)
    except TooManyChunksError:
        result.failed.append(FailedFile(filename=filename, reason=TOO_MANY_CHUNKS_REASON))
        return
    if not chunks:
        result.failed.append(FailedFile(filename=filename, reason=NO_BODY_REASON))
        return

    try:
        note = create_note_for_user(
            db,
            user_id=user_id,
            title=document.title,
            content=document.content,
            source=document.source,
            kind=kind,
            chunks=chunks,
        )
    except DuplicateNoteError:
        # 위에서 확인한 뒤 같은 원문이 먼저 저장된 경우(동시에 두 번 올림). 그 노트를 중복 대상으로 알려 준다.
        duplicate = _existing_duplicate(db, user_id=user_id, filename=filename, document=document)
        if duplicate is not None:
            result.duplicates.append(duplicate)
        else:
            result.failed.append(FailedFile(filename=filename, reason=SAVE_FAILED_REASON))
        return
    except (SQLAlchemyError, ChunkLocationError) as exc:
        # ChunkLocationError는 나누기 쪽 버그(조각이 원문 구간과 다름)라 저장하지 않고 그 파일만 실패로 돌린다.
        db.rollback()
        # 원문 · 제목 · 파일 이름은 남기지 않는다(개인 기록). 엔진도 hide_parameters로 SQL 값을 가린다.
        logger.error("노트 저장 실패 (user_id=%s, %s)", user_id, type(exc).__name__)
        result.failed.append(FailedFile(filename=filename, reason=SAVE_FAILED_REASON))
        return

    result.imported.append(
        ImportedNote(filename=filename, note_id=note.id, title=note.title, chunk_count=len(chunks))
    )
