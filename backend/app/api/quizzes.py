"""퀴즈 · 복습 API (F-004).

POST /api/notes/{note_id}/quizzes — 노트 하나에서 문제를 만든다(AI 1번, 요청 한 번에 처리 — Q-008 전까지).
GET  /api/notes/{note_id}/quizzes — 그 노트의 문제([이 노트 풀기]).
GET  /api/reviews/today          — 모든 노트에서 오늘 차례인 문제('오늘 복습').
POST /api/quizzes/{quiz_id}/answer — 답 제출 → 채점 · 해설 · 근거 · 다음 복습일.
GET  /api/wrong-answers          — 오답노트.
목록에는 정답 · 해설 · 인용을 넣지 않는다(답을 낸 뒤에만 보여 줌).

엔드포인트는 일반 함수(def)라 FastAPI가 작업 스레드에서 돌린다. DB 작업은 그 스레드에서 하고, AI 호출(async, 최대 180초)만
anyio.from_thread.run으로 이벤트 루프에 맡긴다. 동기 DB 세션이 이벤트 루프를 막지 않게 하려는 구조다.
"""

from dataclasses import asdict
from datetime import date

import anyio.from_thread
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import (
    NOTE_NOT_FOUND_DETAIL,
    OTHER_AI_WORK_DETAIL,
    daily_limit_detail,
    llm_client_or_500,
    llm_error_status,
)
from app.config import MAX_DB_ID
from app.db.models import User
from app.db.session import get_db
from app.llm import LLMClient, LLMError
from app.services.quiz_generation import (
    GenerationInProgress,
    NoEligibleChunks,
    NoteNotFound,
    OtherAIWorkInProgress,
    QuizzesAlreadyExist,
    abandon_generation,
    mock_quiz_responder,
    prepare_generation,
    request_quiz_drafts,
    save_failed_generation,
    save_generation,
)
from app.services.quiz_review import (
    AnswerResult,
    InvalidChoice,
    QuizCard,
    QuizNotFound,
    answer_quiz,
    list_note_quizzes,
    list_today_reviews,
    list_wrong_answers,
)
from app.services.usage_service import DailyLimitExceeded

router = APIRouter(tags=["quizzes"])

ALREADY_EXISTS_DETAIL = "이 노트에는 이미 문제가 있어요."
IN_PROGRESS_DETAIL = "이 노트의 문제를 만드는 중이에요. 잠시 뒤 다시 확인해 주세요."
SAVE_FAILED_DETAIL = "만든 문제를 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요."
NO_ELIGIBLE_CHUNKS_DETAIL = "문제를 만들 만큼 내용이 긴 부분이 없어요."
INVALID_OUTPUT_DETAIL = "AI 답이 정해진 형식에 맞지 않아 문제를 만들지 못했어요. 잠시 뒤 다시 시도해 주세요."
QUIZ_NOT_FOUND_DETAIL = "문제를 찾을 수 없어요."
INVALID_CHOICE_DETAIL = "보기 중에서 골라 주세요."
# 노트 · 문제 번호 상한(PostgreSQL integer). 넘는 번호는 DB에 묻기 전에 404(app/config.py MAX_DB_ID)


def get_quiz_llm_client() -> LLMClient:
    """문제 만들기에 쓰는 AI(테스트에서 바꿔 끼움). LLM_PROVIDER=mock(기본)이면 조각으로 가짜 문제를 만드는 mock
    (키 없이 화면 확인용). 설정이 틀리면 500 — 화면에는 설정 내용을 보여 주지 않는다."""
    return llm_client_or_500(mock_quiz_responder)


class GenerateQuizzesResponse(BaseModel):
    note_id: int
    created: int  # 근거 검사를 통과해 저장한 문제 수
    dropped: int  # 버린 문제 수(이유별은 drop_reasons)
    drop_reasons: dict[str, int]
    remaining_today: int  # 오늘 남은 AI 호출 수


@router.post("/notes/{note_id}/quizzes", response_model=GenerateQuizzesResponse, status_code=status.HTTP_201_CREATED)
def generate_quizzes(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client: LLMClient = Depends(get_quiz_llm_client),
) -> GenerateQuizzesResponse:
    """401: 로그인 안 함 / 404: 내 노트가 아님 / 409: 이미 문제가 있음 · 이 노트를 만드는 중 · 다른 AI 작업 진행 중 / 422: 긴 조각이 없음
    429: 오늘 AI 사용량을 다 씀 / 502: AI 답 형식 오류(재시도 후) / 503: AI 연결 안 됨 · AI 서버 한도
    500: 서버 AI 설정 오류 · 만든 문제 저장 실패. 화면은 detail 문구를 그대로 보여 준다.
    """
    if not 1 <= note_id <= MAX_DB_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOTE_NOT_FOUND_DETAIL)
    try:
        plan = prepare_generation(db, user_id=current_user.id, note_id=note_id)
    except NoteNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOTE_NOT_FOUND_DETAIL) from exc
    except QuizzesAlreadyExist as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ALREADY_EXISTS_DETAIL) from exc
    except GenerationInProgress as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=IN_PROGRESS_DETAIL) from exc
    except OtherAIWorkInProgress as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=OTHER_AI_WORK_DETAIL) from exc
    except NoEligibleChunks as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=NO_ELIGIBLE_CHUNKS_DETAIL) from exc
    except DailyLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=daily_limit_detail(exc.usage.limit)
        ) from exc

    try:
        reply = anyio.from_thread.run(request_quiz_drafts, client, plan.messages)
    except LLMError as exc:
        save_failed_generation(db, plan, exc)
        raise HTTPException(*_llm_error_status(exc)) from exc
    except BaseException:  # 예상 못 한 오류 · 요청 취소 — 사용량 1회 · 로그를 남기고 선점을 풀어 다시 누를 수 있게
        abandon_generation(db, plan)
        raise

    try:
        outcome = save_generation(db, plan, reply)  # 실패해도 사용량 기록 · 선점 해제는 save_generation이 한다
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=SAVE_FAILED_DETAIL) from exc
    return GenerateQuizzesResponse(
        note_id=outcome.note_id,
        created=outcome.kept,
        dropped=outcome.dropped,
        drop_reasons=outcome.drop_reasons,
        remaining_today=outcome.remaining_today,
    )


def _llm_error_status(exc: LLMError) -> tuple[int, str]:
    return llm_error_status(exc, invalid_output_detail=INVALID_OUTPUT_DETAIL)


# --- 풀기 · 복습 ---


class QuizCardOut(BaseModel):
    id: int
    note_id: int
    note_title: str
    kind: str
    question: str
    choices: list[str]
    next_review_on: date
    in_wrong_notes: bool


class QuizListResponse(BaseModel):
    quizzes: list[QuizCardOut]


class ReviewListResponse(BaseModel):
    total: int  # 조건에 맞는 문제 수 전체('오늘 복습 N' · 오답노트 개수). 목록은 최대 MAX_REVIEW_SESSION_QUIZZES개
    quizzes: list[QuizCardOut]


class AnswerIn(BaseModel):
    chosen_index: int


class AnswerOut(BaseModel):
    correct: bool
    answer_index: int
    explanation: str
    note_id: int
    note_title: str
    chunk_id: int
    quote: str
    quote_start: int  # 노트 원문 기준 글자 위치 — 근거 칩 → 노트 상세 강조
    quote_end: int
    next_review_on: date
    in_wrong_notes: bool


def _cards(cards: list[QuizCard]) -> list[QuizCardOut]:
    return [QuizCardOut(**asdict(card)) for card in cards]


@router.get("/notes/{note_id}/quizzes", response_model=QuizListResponse)
def get_note_quizzes(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuizListResponse:
    """401 / 404: 내 노트가 아님. 문제가 없으면 빈 목록."""
    if not 1 <= note_id <= MAX_DB_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOTE_NOT_FOUND_DETAIL)
    cards = list_note_quizzes(db, user_id=current_user.id, note_id=note_id)
    if cards is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOTE_NOT_FOUND_DETAIL)
    return QuizListResponse(quizzes=_cards(cards))


@router.get("/reviews/today", response_model=ReviewListResponse)
def get_today_reviews(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewListResponse:
    today = list_today_reviews(db, user_id=current_user.id)
    return ReviewListResponse(total=today.total, quizzes=_cards(today.quizzes))


@router.get("/wrong-answers", response_model=ReviewListResponse)
def get_wrong_answers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewListResponse:
    wrong = list_wrong_answers(db, user_id=current_user.id)
    return ReviewListResponse(total=wrong.total, quizzes=_cards(wrong.quizzes))


@router.post("/quizzes/{quiz_id}/answer", response_model=AnswerOut)
def post_answer(
    body: AnswerIn,
    quiz_id: int = Path(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnswerOut:
    """401 / 404: 내 문제가 아님 / 422: 보기 범위 밖."""
    if not 1 <= quiz_id <= MAX_DB_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=QUIZ_NOT_FOUND_DETAIL)
    try:
        result: AnswerResult = answer_quiz(db, user_id=current_user.id, quiz_id=quiz_id, chosen_index=body.chosen_index)
    except QuizNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=QUIZ_NOT_FOUND_DETAIL) from exc
    except InvalidChoice as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=INVALID_CHOICE_DETAIL) from exc
    return AnswerOut(**asdict(result))
