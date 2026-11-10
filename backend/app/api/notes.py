"""노트 API (F-002 · F-003).

POST /api/notes/import — 마크다운 파일 여러 개를 노트 · 조각으로 저장한다(요청 한 번에 처리, Q-008).
로그인 쿠키 유무 · 요청 크기는 이 함수보다 앞에서 app/api/upload_limit.py가 먼저 거른다.
GET /api/notes/{note_id} — 노트 원문과 조각 위치(노트 상세 화면에서 검색 · 근거 위치를 강조할 때 씀, F-003).
"""

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.upload_limit import TOO_LARGE_DETAIL
from app.config import MAX_IMPORT_FILE_BYTES, MAX_IMPORT_FILES, MAX_IMPORT_TOTAL_BYTES
from app.db.models import User
from app.db.session import get_db
from app.services.import_service import IncomingFile, NoteKind, import_markdown_files
from app.services.note_service import get_note_for_user, list_chunks_for_note_for_user

router = APIRouter(prefix="/notes", tags=["notes"])

NOTE_NOT_FOUND_DETAIL = "노트를 찾을 수 없어요."
# notes.id는 PostgreSQL integer(32비트)다. 이보다 큰 번호로 조회하면 DB가 "범위 초과" 오류(500)를 내므로
# DB에 묻기 전에 "없는 노트"(404)로 답한다(F-003 1차 리뷰 E).
MAX_NOTE_ID = 2_147_483_647


class ImportSummary(BaseModel):
    notes: int
    chunks: int
    duplicates: int
    failed: int


class ImportedNoteOut(BaseModel):
    filename: str
    note_id: int
    title: str
    chunk_count: int


class DuplicateFileOut(BaseModel):
    filename: str
    existing_note_id: int
    existing_title: str


class FailedFileOut(BaseModel):
    filename: str
    reason: str


class ImportResponse(BaseModel):
    summary: ImportSummary
    imported: list[ImportedNoteOut]
    duplicates: list[DuplicateFileOut]
    failed: list[FailedFileOut]


class NoteChunkOut(BaseModel):
    id: int
    position: int
    heading_path: str
    # 노트 원문(content)의 파이썬 글자(코드 포인트) 위치. 화면은 Array.from(content)로 같은 단위로 자른다.
    start_offset: int
    end_offset: int


class NoteDetailOut(BaseModel):
    id: int
    title: str
    kind: str
    source: str
    created_at: datetime
    content: str
    chunks: list[NoteChunkOut]


def _read_head(upload: UploadFile) -> bytes:
    """파일 앞부분을 (상한 + 1)바이트까지만 읽는다. 큰 파일을 통째로 메모리에 올리지 않기 위해서다."""
    return upload.file.read(MAX_IMPORT_FILE_BYTES + 1)


@router.post("/import", response_model=ImportResponse)
def import_notes(
    files: list[UploadFile] | None = File(default=None),
    kind: NoteKind = Form(default="study"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportResponse:
    """마크다운 파일을 가져온다. 일부가 실패해도 200으로 성공 · 중복 · 실패 목록을 함께 돌려준다.

    400: 파일 없음 · 개수 초과 / 401: 로그인 안 함 / 413: 전체 용량 초과 / 422: 기록 종류 값이 틀림
    """
    uploads = files or []
    if not uploads:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="올릴 파일을 골라 주세요.")
    if len(uploads) > MAX_IMPORT_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"한 번에 {MAX_IMPORT_FILES}개까지 올릴 수 있어요.",
        )
    # 요청 전체(머리말 몫 포함)는 미들웨어가 막고, 여기서는 파일 내용의 합계를 본다.
    if sum(upload.size or 0 for upload in uploads) > MAX_IMPORT_TOTAL_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=TOO_LARGE_DETAIL)

    incoming = [IncomingFile(filename=upload.filename, data=_read_head(upload)) for upload in uploads]
    result = import_markdown_files(db, user_id=current_user.id, kind=kind, files=incoming)

    return ImportResponse(
        summary=ImportSummary(
            notes=len(result.imported),
            chunks=result.chunk_count,
            duplicates=len(result.duplicates),
            failed=len(result.failed),
        ),
        imported=[ImportedNoteOut(**asdict(note)) for note in result.imported],
        duplicates=[DuplicateFileOut(**asdict(dup)) for dup in result.duplicates],
        failed=[FailedFileOut(**asdict(fail)) for fail in result.failed],
    )


@router.get("/{note_id}", response_model=NoteDetailOut)
def get_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NoteDetailOut:
    """401: 로그인 안 함 / 404: 없거나 다른 사용자의 노트(있는지조차 알려 주지 않음, D-004) · 번호가 범위 밖"""
    if not 1 <= note_id <= MAX_NOTE_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOTE_NOT_FOUND_DETAIL)
    note = get_note_for_user(db, user_id=current_user.id, note_id=note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOTE_NOT_FOUND_DETAIL)
    chunks = list_chunks_for_note_for_user(db, user_id=current_user.id, note_id=note.id)
    return NoteDetailOut(
        id=note.id,
        title=note.title,
        kind=note.kind,
        source=note.source,
        created_at=note.created_at,
        content=note.content,
        chunks=[
            NoteChunkOut(
                id=chunk.id,
                position=chunk.position,
                heading_path=chunk.heading_path,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
            )
            for chunk in chunks
        ],
    )
