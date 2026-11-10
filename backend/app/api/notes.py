"""노트 API (F-002).

POST /api/notes/import — 마크다운 파일 여러 개를 노트 · 조각으로 저장한다(요청 한 번에 처리, Q-008).
로그인 쿠키 유무 · 요청 크기는 이 함수보다 앞에서 app/api/upload_limit.py가 먼저 거른다.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.upload_limit import TOO_LARGE_DETAIL
from app.config import MAX_IMPORT_FILE_BYTES, MAX_IMPORT_FILES, MAX_IMPORT_TOTAL_BYTES
from app.db.models import User
from app.db.session import get_db
from app.services.import_service import IncomingFile, NoteKind, import_markdown_files

router = APIRouter(prefix="/notes", tags=["notes"])


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
