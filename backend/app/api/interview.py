"""면접 연습 API (F-009).

POST   /api/cards/{card_id}/interview-questions        — [면접 질문 만들기](AI 1번). 카드당 한 번, 저장 카드만.
PATCH  /api/interview-questions/{question_id}         — 내 답 메모 저장(비우면 '답하지 않음').
GET    /api/applications/{application_id}/interview   — 이 공고에 매칭된 카드별 질문 · 역량 태그 · 답한 수.
카드 상세 응답(GET /api/cards/{id})에도 그 카드의 질문이 들어 있다(api/cards.py).

AI 엔드포인트는 초안 쓰기(api/drafts.py)와 같은 구조다: 일반 함수(def)라 작업 스레드에서 DB를 다루고,
AI 호출(async, 최대 100초)만 anyio.from_thread.run으로 이벤트 루프에 맡긴다.
"""

from collections.abc import Callable
from typing import Any

import anyio.from_thread
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import (
    OTHER_AI_WORK_DETAIL,
    daily_limit_detail,
    llm_client_or_500,
    llm_error_status,
)
from app.api.schemas import RAW_INPUT_SLACK, InterviewQuestionOut, ServiceOut
from app.config import INTERVIEW_MEMO_MAX_CHARS, MAX_DB_ID
from app.db.models import User
from app.db.session import get_db
from app.llm import LLMClient, LLMError
from app.services.application_service import ApplicationNotFound
from app.services.card_service import CardNotFound
from app.services.interview_mock import mock_interview_responder
from app.services.interview_service import (
    CardNotSaved,
    InterviewQuestionNotFound,
    InterviewWriteInProgress,
    InvalidMemo,
    NoFieldText,
    QuestionsAlreadyExist,
    abandon,
    get_application_interview,
    prepare_interview,
    save_failed,
    save_interview,
    update_memo,
)
from app.services.interview_writing import request_interview_questions
from app.services.note_claim import OtherAIWorkInProgress
from app.services.usage_service import DailyLimitExceeded

router = APIRouter(tags=["interview"])

CARD_NOT_FOUND_DETAIL = "카드를 찾을 수 없어요."
APPLICATION_NOT_FOUND_DETAIL = "공고를 찾을 수 없어요."
QUESTION_NOT_FOUND_DETAIL = "면접 질문을 찾을 수 없어요."
NOT_SAVED_DETAIL = "저장한 카드에서만 면접 질문을 만들 수 있어요. 카드를 먼저 저장해 주세요."
ALREADY_EXISTS_DETAIL = "이 카드에는 이미 면접 질문이 있어요."
NO_FIELD_TEXT_DETAIL = "글이 있는 칸이 없어 질문을 만들 근거가 없어요. 빈칸에 내 답을 먼저 써 주세요."
IN_PROGRESS_DETAIL = "이 카드의 면접 질문을 만드는 중이에요. 끝난 뒤 다시 시도해 주세요."
SAVE_FAILED_DETAIL = "만든 질문을 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요."
INVALID_OUTPUT_DETAIL = "AI 답이 정해진 형식에 맞지 않아 질문을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요."


def get_interview_llm_client() -> LLMClient:
    """면접 질문에 쓰는 AI(테스트에서 바꿔 끼움). LLM_PROVIDER=mock(기본)이면 칸 글로 가짜 질문을 만드는 mock."""
    return llm_client_or_500(mock_interview_responder)


def _http(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _check_id(value: int, detail: str) -> None:
    """2^31 이상이면 PostgreSQL이 500을 내므로 DB에 묻기 전에 404(F-008 1차 리뷰 R2와 같음)."""
    if not 1 <= value <= MAX_DB_ID:
        raise _http(status.HTTP_404_NOT_FOUND, detail)


# --- [면접 질문 만들기] ---


class WriteInterviewOut(ServiceOut):
    card_id: int
    written: bool  # false면 검사를 넘은 질문이 없어 아무것도 저장하지 않음(다시 누를 수 있음)
    questions: int
    received: int
    fields_sent: int
    drop_reasons: dict[str, int]
    remaining_today: int


# '부르기 전' 오류 → HTTP. 예외 하나를 더할 때 이 표 한 곳만 고친다(F-008 4차 리뷰 R1과 같은 모양).
_PREPARE_ERRORS: dict[type[Exception], Callable[[Any], HTTPException]] = {
    CardNotFound: lambda _exc: _http(status.HTTP_404_NOT_FOUND, CARD_NOT_FOUND_DETAIL),
    CardNotSaved: lambda _exc: _http(status.HTTP_409_CONFLICT, NOT_SAVED_DETAIL),
    QuestionsAlreadyExist: lambda _exc: _http(status.HTTP_409_CONFLICT, ALREADY_EXISTS_DETAIL),
    NoFieldText: lambda _exc: _http(status.HTTP_409_CONFLICT, NO_FIELD_TEXT_DETAIL),
    InterviewWriteInProgress: lambda _exc: _http(status.HTTP_409_CONFLICT, IN_PROGRESS_DETAIL),
    OtherAIWorkInProgress: lambda _exc: _http(status.HTTP_409_CONFLICT, OTHER_AI_WORK_DETAIL),
    DailyLimitExceeded: lambda exc: _http(status.HTTP_429_TOO_MANY_REQUESTS, daily_limit_detail(exc.usage.limit)),
}


@router.post("/cards/{card_id}/interview-questions", response_model=WriteInterviewOut, status_code=status.HTTP_201_CREATED)
def write_interview_endpoint(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client: LLMClient = Depends(get_interview_llm_client),
) -> WriteInterviewOut:
    """401 / 404 내 카드 아님 / 409 후보 카드 · 이미 질문 있음 · 글 있는 칸 없음 · 진행 중 · 다른 AI 작업 / 429 하루 상한 /
    502 AI 답 형식 오류 / 503 AI 연결 안 됨 · AI 서버 한도 / 500 AI 설정 오류 · 저장 실패. 화면은 detail을 그대로 보여 준다."""
    _check_id(card_id, CARD_NOT_FOUND_DETAIL)
    try:
        plan = prepare_interview(db, user_id=current_user.id, card_id=card_id)
    except tuple(_PREPARE_ERRORS) as exc:
        raise _PREPARE_ERRORS[type(exc)](exc) from exc

    try:
        reply = anyio.from_thread.run(request_interview_questions, client, plan.messages)
    except LLMError as exc:
        save_failed(db, plan, exc)
        raise HTTPException(*llm_error_status(exc, invalid_output_detail=INVALID_OUTPUT_DETAIL)) from exc
    except BaseException:  # 예상 못 한 오류 · 요청 취소 — 사용량 1회 · 로그를 남기고 선점을 풀어 다시 누를 수 있게
        abandon(db, plan)
        raise

    try:
        outcome = save_interview(db, plan, reply)
    except CardNotFound as exc:  # AI를 부르는 동안 카드가 지워졌거나 저장을 취소함
        raise _http(status.HTTP_404_NOT_FOUND, CARD_NOT_FOUND_DETAIL) from exc
    except Exception as exc:
        raise _http(status.HTTP_500_INTERNAL_SERVER_ERROR, SAVE_FAILED_DETAIL) from exc
    return WriteInterviewOut.model_validate(outcome)


# --- 메모 ---


class MemoIn(BaseModel):
    memo: str | None = Field(default=None, max_length=INTERVIEW_MEMO_MAX_CHARS * RAW_INPUT_SLACK)


@router.patch("/interview-questions/{question_id}", response_model=InterviewQuestionOut)
def update_memo_endpoint(
    question_id: int,
    body: MemoIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InterviewQuestionOut:
    """401 / 404 내 질문 아님 / 422 메모가 너무 김 · 쓸 수 없는 글자. 비우면(null · 공백) '답하지 않음'."""
    _check_id(question_id, QUESTION_NOT_FOUND_DETAIL)
    try:
        view = update_memo(db, user_id=current_user.id, question_id=question_id, memo=body.memo)
    except InterviewQuestionNotFound as exc:
        raise _http(status.HTTP_404_NOT_FOUND, QUESTION_NOT_FOUND_DETAIL) from exc
    except InvalidMemo as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return InterviewQuestionOut.model_validate(view)


# --- 지원 상세 [면접 연습] 탭 ---


class CardInterviewOut(ServiceOut):
    card_id: int
    card_title: str
    note_title: str | None
    requirement_names: list[str]
    has_questions: bool  # 합치기 전에 질문이 있었는지(false = 질문 없는 카드)
    questions: list[InterviewQuestionOut]


class ApplicationInterviewOut(ServiceOut):
    application_id: int
    analysis_done: bool
    question_count: int
    answered_count: int
    cards: list[CardInterviewOut]


@router.get("/applications/{application_id}/interview", response_model=ApplicationInterviewOut)
def get_interview_endpoint(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationInterviewOut:
    """401 / 404 내 공고 아님. 근거 상태는 지금 카드 칸과 다시 비교한 값이다(AI 없음)."""
    _check_id(application_id, APPLICATION_NOT_FOUND_DETAIL)
    try:
        return ApplicationInterviewOut.model_validate(
            get_application_interview(db, user_id=current_user.id, application_id=application_id)
        )
    except ApplicationNotFound as exc:
        raise _http(status.HTTP_404_NOT_FOUND, APPLICATION_NOT_FOUND_DETAIL) from exc
