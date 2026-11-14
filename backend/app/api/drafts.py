"""자소서 초안 API (F-008).

GET    /api/applications/{id}/drafts                    — 문항별 초안 · 문장 · 근거(지금 카드와 다시 비교한 상태), 매칭 카드.
POST   /api/applications/{id}/questions/{qid}/draft     — [초안 쓰기](AI 1번). 이미 초안이 있으면 overwrite=true일 때만 덮어씀.
PUT    /api/applications/{id}/questions                 — 문항 목록 저장(추가 · 수정 · 삭제, 지운 문항의 초안도 지움).
PUT    /api/drafts/{draft_id}                           — 문장 단위로 고친 목록 저장(고침 · 지우기 · 새 문장 · [카드 연결]).
PATCH  /api/drafts/{draft_id}                           — [이 문항 완료] · 완료 풀기.

AI 엔드포인트는 공고 분석(api/applications.py)과 같은 구조다: 일반 함수(def)라 작업 스레드에서 DB를 다루고,
AI 호출(async, 최대 180초)만 anyio.from_thread.run으로 이벤트 루프에 맡긴다.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

import anyio.from_thread
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import OTHER_AI_WORK_DETAIL, daily_limit_detail, llm_client_or_500, llm_error_status
from app.api.schemas import RAW_INPUT_SLACK, ServiceOut
from app.config import (
    APPLICATION_MAX_QUESTIONS,
    APPLICATION_QUESTION_MAX_CHARS,
    DRAFT_MAX_SENTENCES,
    DRAFT_SENTENCE_MAX_CHARS,
    MAX_DB_ID,
)
from app.db.models import User
from app.db.session import get_db
from app.llm import LLMClient, LLMError
from app.services.application_service import (
    ApplicationNotFound,
    InvalidApplicationInput,
    QuestionEdit,
    QuestionsConflict,
    replace_questions,
)
from app.services.draft_mock import mock_draft_responder
from app.services.draft_service import (
    DraftAlreadyExists,
    DraftConflict,
    DraftWriteInProgress,
    EvidenceLink,
    InvalidDraftInput,
    NoMatchedCards,
    QuestionNotFound,
    SentenceEdit,
    abandon,
    prepare_draft,
    save_draft,
    save_failed,
    set_draft_completed,
    update_draft,
)
from app.services.draft_view import DraftNotFound, get_application_drafts
from app.services.draft_writing import request_draft
from app.services.note_claim import OtherAIWorkInProgress
from app.services.usage_service import DailyLimitExceeded

router = APIRouter(tags=["drafts"])

APPLICATION_NOT_FOUND_DETAIL = "공고를 찾을 수 없어요."
QUESTION_NOT_FOUND_DETAIL = "자소서 문항을 찾을 수 없어요."
DRAFT_NOT_FOUND_DETAIL = "초안을 찾을 수 없어요."
DRAFT_EXISTS_DETAIL = "이 문항에는 이미 초안이 있어요. 다시 쓰면 지금 초안을 덮어써요."
NO_CARDS_DETAIL = "이 공고에 매칭된 경험 카드가 없어요. 근거 없이 쓰면 AI가 지어낸 문장이 돼요. 카드를 만든 뒤 공고 분석에서 [매칭 다시]를 눌러 주세요."
NOT_ANALYZED_DETAIL = "먼저 공고 분석에서 내 카드를 매칭해 주세요. 매칭된 카드로만 초안을 써요."
IN_PROGRESS_DETAIL = "이 공고에서 AI 작업(초안 쓰기 · 공고 분석)이 진행 중이에요. 끝난 뒤 다시 시도해 주세요."
CONFLICT_DETAIL = "다른 곳에서 이 초안이 먼저 바뀌었어요. 새로고침한 뒤 다시 고쳐 주세요."
QUESTIONS_CONFLICT_DETAIL = "다른 곳에서 문항이 먼저 바뀌었어요. 새로 불러온 목록을 확인하고 다시 고쳐 주세요."
SAVE_FAILED_DETAIL = "쓴 초안을 저장하지 못했어요. 이전 초안은 그대로예요. 잠시 뒤 다시 시도해 주세요."
INVALID_OUTPUT_DETAIL = "AI 답이 정해진 형식에 맞지 않아 초안을 쓰지 못했어요. 이전 초안은 그대로예요. 잠시 뒤 다시 시도해 주세요."


def get_draft_llm_client() -> LLMClient:
    """초안 쓰기에 쓰는 AI(테스트에서 바꿔 끼움). LLM_PROVIDER=mock(기본)이면 카드 글로 가짜 문장을 만드는 mock."""
    return llm_client_or_500(mock_draft_responder)


def _http(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _check_ids(*ids: int, detail: str = APPLICATION_NOT_FOUND_DETAIL) -> None:
    if any(not 1 <= value <= MAX_DB_ID for value in ids):
        raise _http(status.HTTP_404_NOT_FOUND, detail)


class EvidenceOut(ServiceOut):
    card_id: int | None  # 카드가 지워졌으면 null
    card_title: str | None
    note_title: str | None
    slot: str
    quote: str
    quote_source: str  # quote(카드의 원문 인용) · answer(카드의 내 답)
    added_by: str  # ai · user([카드 연결])


class SentenceOut(ServiceOut):
    id: int
    position: int
    text: str
    origin: str  # ai · edited('내가 고침') · user(내가 넣은 문장)
    original_text: str | None
    evidence_status: str  # ok · none · card_gone · changed
    evidence: EvidenceOut | None


class DraftOut(ServiceOut):
    id: int
    question_id: int
    version: int
    completed_at: datetime | None
    updated_at: datetime
    chars: int
    char_limit: int | None
    edited_percent: int
    sentence_count: int
    unsupported_count: int
    sentences: list[SentenceOut]


class QuestionDraftOut(ServiceOut):
    id: int
    position: int
    text: str
    char_limit: int | None
    draft: DraftOut | None


class ApplicationDraftsOut(ServiceOut):
    application_id: int
    analysis_done: bool
    matched_card_ids: list[int]
    checked_at: datetime
    questions: list[QuestionDraftOut]


@router.get("/applications/{application_id}/drafts", response_model=ApplicationDraftsOut)
def get_drafts_endpoint(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationDraftsOut:
    """401 / 404 내 공고 아님. 근거 상태는 지금 카드 칸과 다시 비교한 값이다(AI 없음)."""
    _check_ids(application_id)
    try:
        return ApplicationDraftsOut.model_validate(
            get_application_drafts(db, user_id=current_user.id, application_id=application_id)
        )
    except ApplicationNotFound as exc:
        raise _http(status.HTTP_404_NOT_FOUND, APPLICATION_NOT_FOUND_DETAIL) from exc


# --- [초안 쓰기] ---


class WriteDraftIn(BaseModel):
    overwrite: bool = False  # 이미 초안이 있을 때 덮어쓰기(화면이 확인창을 띄운 뒤 true로 보냄)


class WriteDraftOut(ServiceOut):
    question_id: int
    written: bool  # false면 AI가 쓸 만한 문장을 주지 않아 초안을 바꾸지 않음
    sentences: int
    supported: int
    cards_sent: int
    drop_reasons: dict[str, int]
    remaining_today: int


# [초안 쓰기] '부르기 전' 오류 → HTTP. 예외 하나를 더할 때 이 표 한 곳만 고친다(4차 리뷰 R1 — 전에는 튜플과 분기 두 곳).
_PREPARE_ERRORS: dict[type[Exception], Callable[[Any], HTTPException]] = {
    ApplicationNotFound: lambda _exc: _http(status.HTTP_404_NOT_FOUND, APPLICATION_NOT_FOUND_DETAIL),
    QuestionNotFound: lambda _exc: _http(status.HTTP_404_NOT_FOUND, QUESTION_NOT_FOUND_DETAIL),
    DraftAlreadyExists: lambda _exc: _http(status.HTTP_409_CONFLICT, DRAFT_EXISTS_DETAIL),
    NoMatchedCards: lambda exc: _http(status.HTTP_409_CONFLICT, NO_CARDS_DETAIL if exc.analysis_done else NOT_ANALYZED_DETAIL),
    DraftWriteInProgress: lambda _exc: _http(status.HTTP_409_CONFLICT, IN_PROGRESS_DETAIL),
    OtherAIWorkInProgress: lambda _exc: _http(status.HTTP_409_CONFLICT, OTHER_AI_WORK_DETAIL),
    DailyLimitExceeded: lambda exc: _http(status.HTTP_429_TOO_MANY_REQUESTS, daily_limit_detail(exc.usage.limit)),
}


@router.post(
    "/applications/{application_id}/questions/{question_id}/draft",
    response_model=WriteDraftOut,
    status_code=status.HTTP_201_CREATED,
)
def write_draft_endpoint(
    application_id: int,
    question_id: int,
    body: WriteDraftIn | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client: LLMClient = Depends(get_draft_llm_client),
) -> WriteDraftOut:
    """401 / 404 공고 · 문항 / 409 초안 있음(overwrite 아님) · 매칭 카드 없음 · 진행 중 · 다른 AI 작업 / 429 하루 상한 /
    502 AI 답 형식 오류 / 503 AI 연결 안 됨 · AI 서버 한도 / 500 AI 설정 오류 · 저장 실패.
    실패하면 이전 초안은 그대로다. 화면은 detail을 그대로 보여 준다."""
    _check_ids(application_id)
    _check_ids(question_id, detail=QUESTION_NOT_FOUND_DETAIL)
    overwrite = body.overwrite if body is not None else False
    try:
        plan = prepare_draft(
            db, user_id=current_user.id, application_id=application_id, question_id=question_id, overwrite=overwrite
        )
    except tuple(_PREPARE_ERRORS) as exc:
        raise _PREPARE_ERRORS[type(exc)](exc) from exc

    try:
        reply = anyio.from_thread.run(request_draft, client, plan.messages)
    except LLMError as exc:
        save_failed(db, plan, exc)
        raise HTTPException(*llm_error_status(exc, invalid_output_detail=INVALID_OUTPUT_DETAIL)) from exc
    except BaseException:  # 예상 못 한 오류 · 요청 취소 — 사용량 1회 · 로그를 남기고 선점을 풀어 다시 누를 수 있게
        abandon(db, plan)
        raise

    try:
        outcome = save_draft(db, plan, reply)
    except ApplicationNotFound as exc:  # AI를 부르는 동안 공고가 지워짐
        raise _http(status.HTTP_404_NOT_FOUND, APPLICATION_NOT_FOUND_DETAIL) from exc
    except QuestionNotFound as exc:  # AI를 부르는 동안 문항이 지워짐
        raise _http(status.HTTP_404_NOT_FOUND, QUESTION_NOT_FOUND_DETAIL) from exc
    except Exception as exc:
        raise _http(status.HTTP_500_INTERNAL_SERVER_ERROR, SAVE_FAILED_DETAIL) from exc
    return WriteDraftOut.model_validate(outcome)


# --- 문항 목록 ---


# 본문에 든 번호 · version도 DB에 묻기 전에 범위를 본다 — 2^31 이상이면 PostgreSQL이 500을 낸다(F-008 1차 리뷰 R2)
DbId = Annotated[int, Field(ge=1, le=MAX_DB_ID)]


class QuestionEditIn(BaseModel):
    id: DbId | None = None  # 기존 문항이면 번호, 새 문항이면 비움
    text: str = Field(max_length=APPLICATION_QUESTION_MAX_CHARS * RAW_INPUT_SLACK)
    char_limit: int | None = None


class ReplaceQuestionsIn(BaseModel):
    questions: list[QuestionEditIn] = Field(max_length=APPLICATION_MAX_QUESTIONS * RAW_INPUT_SLACK)
    # 지울 기존 문항(화면이 확인창을 띄운 것). '보낸 문항 + 지울 문항'이 지금 목록과 다르면 409
    removed_ids: list[DbId] = Field(default_factory=list, max_length=APPLICATION_MAX_QUESTIONS * RAW_INPUT_SLACK)


@router.put("/applications/{application_id}/questions", response_model=ApplicationDraftsOut)
def replace_questions_endpoint(
    application_id: int,
    body: ReplaceQuestionsIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationDraftsOut:
    """401 / 404 내 공고 아님 / 409 다른 곳에서 문항이 먼저 바뀜(보낸 + 지울 문항 ≠ 지금 목록) /
    422 빈 문항 · 너무 김 · 개수 · 같은 문항 두 번. removed_ids의 문항은 초안과 같이 지운다."""
    _check_ids(application_id)
    try:
        replace_questions(
            db,
            user_id=current_user.id,
            application_id=application_id,
            questions=[QuestionEdit(id=item.id, text=item.text, char_limit=item.char_limit) for item in body.questions],
            removed_ids=body.removed_ids,
        )
        return ApplicationDraftsOut.model_validate(
            get_application_drafts(db, user_id=current_user.id, application_id=application_id)
        )
    except ApplicationNotFound as exc:
        raise _http(status.HTTP_404_NOT_FOUND, APPLICATION_NOT_FOUND_DETAIL) from exc
    except QuestionsConflict as exc:
        raise _http(status.HTTP_409_CONFLICT, QUESTIONS_CONFLICT_DETAIL) from exc
    except InvalidApplicationInput as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


# --- 고치기 · 완료 ---


class EvidenceLinkIn(BaseModel):
    card_id: DbId
    slot: str = Field(max_length=16)
    quote_source: Literal["quote", "answer"]


class SentenceEditIn(BaseModel):
    id: DbId | None = None  # 기존 문장이면 번호(근거 유지), 새 문장이면 비움
    text: str = Field(max_length=DRAFT_SENTENCE_MAX_CHARS * RAW_INPUT_SLACK)
    link: EvidenceLinkIn | None = None  # [카드 연결]
    unlink: bool = False  # 근거 떼기


class UpdateDraftIn(BaseModel):
    version: DbId  # 화면이 읽은 초안 version. 다르면 409
    sentences: list[SentenceEditIn] = Field(max_length=DRAFT_MAX_SENTENCES * RAW_INPUT_SLACK)


@router.put("/drafts/{draft_id}", response_model=DraftOut)
def update_draft_endpoint(
    draft_id: int,
    body: UpdateDraftIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftOut:
    """401 / 404 내 초안 아님 / 409 다른 곳에서 먼저 바뀜(version) / 422 빈 문장 · 너무 김 · 없는 문장 · 쓸 수 없는 카드 칸."""
    _check_ids(draft_id, detail=DRAFT_NOT_FOUND_DETAIL)
    edits = [
        SentenceEdit(
            id=item.id,
            text=item.text,
            link=EvidenceLink(card_id=item.link.card_id, slot=item.link.slot, quote_source=item.link.quote_source)
            if item.link is not None
            else None,
            unlink=item.unlink,
        )
        for item in body.sentences
    ]
    try:
        return DraftOut.model_validate(
            update_draft(db, user_id=current_user.id, draft_id=draft_id, version=body.version, sentences=edits)
        )
    except DraftNotFound as exc:
        raise _http(status.HTTP_404_NOT_FOUND, DRAFT_NOT_FOUND_DETAIL) from exc
    except DraftConflict as exc:
        raise _http(status.HTTP_409_CONFLICT, CONFLICT_DETAIL) from exc
    except InvalidDraftInput as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


class CompleteDraftIn(BaseModel):
    completed: bool


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
def complete_draft_endpoint(
    draft_id: int,
    body: CompleteDraftIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftOut:
    """401 / 404 내 초안 아님. [이 문항 완료] · 완료 풀기."""
    _check_ids(draft_id, detail=DRAFT_NOT_FOUND_DETAIL)
    try:
        return DraftOut.model_validate(
            set_draft_completed(db, user_id=current_user.id, draft_id=draft_id, completed=body.completed)
        )
    except DraftNotFound as exc:
        raise _http(status.HTTP_404_NOT_FOUND, DRAFT_NOT_FOUND_DETAIL) from exc
