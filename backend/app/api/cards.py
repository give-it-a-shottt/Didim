"""경험 카드 API (F-006).

POST   /api/notes/{note_id}/cards/candidates — 노트 하나에서 카드 후보 찾기(AI 1번, 요청 한 번에 처리 — Q-008 전까지).
GET    /api/cards?status=candidate|saved&note_id= — 목록(빈칸 수 · 근거 수 · 수정일).
GET    /api/cards/{card_id}                   — 상세(칸마다 인용 · 근거 위치 · 빈칸 질문 · 내 답).
POST   /api/cards/{card_id}/save              — 후보 → 저장(제목 확인).
DELETE /api/cards/{card_id}                   — 후보 버리기 · 카드 삭제.
PUT    /api/cards/{card_id}/fields/{slot}     — 내 답 저장 · 인용 빼기.

후보 찾기 엔드포인트는 문제 만들기(api/quizzes.py)와 같은 구조다: 일반 함수(def)라 작업 스레드에서 DB를 다루고,
AI 호출(async, 최대 180초)만 anyio.from_thread.run으로 이벤트 루프에 맡긴다.
"""

from datetime import datetime
from typing import Literal

import anyio.from_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import (
    NOTE_NOT_FOUND_DETAIL,
    OTHER_AI_WORK_DETAIL,
    daily_limit_detail,
    llm_client_or_500,
    llm_error_status,
)
from app.config import (
    CARD_MAX_ANSWER_CHARS,
    CARD_STATUS_CANDIDATE,
    CARD_STATUS_SAVED,
    CARD_TITLE_MAX_CHARS,
    MAX_DB_ID,
)
from app.db.models import User
from app.db.session import get_db
from app.llm import LLMClient, LLMError
from app.services.card_generation import (
    CardsAlreadyFound,
    NoChunks,
    NoteNotFound,
    OtherAIWorkInProgress,
    SearchInProgress,
    abandon_search,
    mock_card_responder,
    prepare_search,
    request_card_drafts,
    save_failed_search,
    save_search,
)
from app.services.card_service import (
    CardDetail,
    CardNotFound,
    InvalidCardInput,
    delete_card,
    get_card,
    list_cards,
    save_card,
    update_field,
)
from app.services.usage_service import DailyLimitExceeded

router = APIRouter(tags=["cards"])

ALREADY_FOUND_DETAIL = "이 노트에서는 이미 카드 후보를 찾았어요."
IN_PROGRESS_DETAIL = "이 노트에서 카드 후보를 찾는 중이에요. 잠시 뒤 다시 확인해 주세요."
NO_CHUNKS_DETAIL = "이 노트에는 카드 후보를 찾을 내용이 없어요."
SAVE_FAILED_DETAIL = "찾은 후보를 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요."
INVALID_OUTPUT_DETAIL = "AI 답이 정해진 형식에 맞지 않아 후보를 찾지 못했어요. 잠시 뒤 다시 시도해 주세요."
CARD_NOT_FOUND_DETAIL = "카드를 찾을 수 없어요."

Slot = Literal["situation", "task", "action", "result"]  # app/config.py CARD_SLOTS와 같은 순서 · 이름(테스트로 확인)


def get_card_llm_client() -> LLMClient:
    """후보 찾기에 쓰는 AI(테스트에서 바꿔 끼움). LLM_PROVIDER=mock(기본)이면 조각으로 가짜 후보를 만드는 mock."""
    return llm_client_or_500(mock_card_responder)


def _llm_error_status(exc: LLMError) -> tuple[int, str]:
    return llm_error_status(exc, invalid_output_detail=INVALID_OUTPUT_DETAIL)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CARD_NOT_FOUND_DETAIL)


# --- 후보 찾기 ---


class FindCandidatesResponse(BaseModel):
    note_id: int
    card_ids: list[int]  # 저장한 후보 카드(0개면 '경험을 찾지 못했어요' — 다시 누를 수 있음)
    quoted_fields: int  # 원문 인용이 들어간 칸 수
    emptied_fields: int  # 인용 검사에서 빈칸이 된 칸 수
    drop_reasons: dict[str, int]
    chunks_sent: int  # AI에 보낸 조각 수(원칙 6 — 앞부분만 보냈으면 화면이 알려 줌)
    chunks_total: int
    remaining_today: int


@router.post(
    "/notes/{note_id}/cards/candidates",
    response_model=FindCandidatesResponse,
    status_code=status.HTTP_201_CREATED,
)
def find_card_candidates(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client: LLMClient = Depends(get_card_llm_client),
) -> FindCandidatesResponse:
    """401 / 404 내 노트 아님 / 409 이미 찾음 · 이 노트에서 찾는 중 · 다른 AI 작업 진행 중 / 422 내용 없음 / 429 하루 상한
    502 AI 답 형식 오류 / 503 AI 연결 안 됨 · AI 서버 한도 / 500 AI 설정 오류 · 저장 실패. 화면은 detail을 그대로 보여 준다."""
    if not 1 <= note_id <= MAX_DB_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOTE_NOT_FOUND_DETAIL)
    try:
        plan = prepare_search(db, user_id=current_user.id, note_id=note_id)
    except NoteNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOTE_NOT_FOUND_DETAIL) from exc
    except CardsAlreadyFound as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ALREADY_FOUND_DETAIL) from exc
    except SearchInProgress as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=IN_PROGRESS_DETAIL) from exc
    except OtherAIWorkInProgress as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=OTHER_AI_WORK_DETAIL) from exc
    except NoChunks as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=NO_CHUNKS_DETAIL) from exc
    except DailyLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=daily_limit_detail(exc.usage.limit)
        ) from exc

    try:
        reply = anyio.from_thread.run(request_card_drafts, client, plan.messages)
    except LLMError as exc:
        save_failed_search(db, plan, exc)
        raise HTTPException(*_llm_error_status(exc)) from exc
    except BaseException:  # 예상 못 한 오류 · 요청 취소 — 사용량 1회 · 로그를 남기고 선점을 풀어 다시 누를 수 있게
        abandon_search(db, plan)
        raise

    try:
        outcome = save_search(db, plan, reply)  # 실패해도 사용량 기록 · 선점 해제는 save_search가 한다
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=SAVE_FAILED_DETAIL) from exc
    return FindCandidatesResponse(
        note_id=outcome.note_id,
        card_ids=outcome.card_ids,
        quoted_fields=outcome.quoted_fields,
        emptied_fields=outcome.emptied_fields,
        drop_reasons=outcome.drop_reasons,
        chunks_sent=outcome.chunks_sent,
        chunks_total=outcome.chunks_total,
        remaining_today=outcome.remaining_today,
    )


# --- 목록 · 상세 ---


class CardSummaryOut(BaseModel):
    id: int
    title: str
    status: str
    note_id: int | None
    note_title: str | None  # None = 노트가 지워짐('원문 없음')
    blank_count: int
    evidence_count: int
    updated_at: datetime
    blank_slots: list[str]  # 빈칸인 칸(situation · task · action · result 순서)


class CardListResponse(BaseModel):
    total: int  # 조건에 맞는 카드 수 전체. 목록은 최대 MAX_CARD_LIST개
    cards: list[CardSummaryOut]
    note_searched: bool | None  # note_id로 걸렀을 때만: 이 노트에서 후보 찾기를 끝냈는가


class CardFieldOut(BaseModel):
    slot: str
    quote: str | None
    quote_start: int | None
    quote_end: int | None
    chunk_id: int | None
    question: str | None
    answer: str | None


class CardDetailOut(BaseModel):
    id: int
    title: str
    status: str
    note_id: int | None
    note_title: str | None
    created_at: datetime
    updated_at: datetime
    blank_count: int
    evidence_count: int
    fields: list[CardFieldOut]


def _detail(card: CardDetail) -> CardDetailOut:
    return CardDetailOut(
        id=card.id,
        title=card.title,
        status=card.status,
        note_id=card.note_id,
        note_title=card.note_title,
        created_at=card.created_at,
        updated_at=card.updated_at,
        blank_count=card.blank_count,
        evidence_count=card.evidence_count,
        fields=[CardFieldOut(**vars(item)) for item in card.fields],
    )


@router.get("/cards", response_model=CardListResponse)
def get_cards(
    status_: Literal["candidate", "saved"] = Query(default=CARD_STATUS_SAVED, alias="status"),
    note_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CardListResponse:
    """401 / 422 status 값 틀림. note_id가 내 노트가 아니면 빈 목록(남의 노트가 있는지 알려 주지 않음)."""
    if note_id is not None and not 1 <= note_id <= MAX_DB_ID:
        return CardListResponse(total=0, cards=[], note_searched=False)
    result = list_cards(db, user_id=current_user.id, status=status_, note_id=note_id)
    return CardListResponse(
        total=result.total,
        cards=[CardSummaryOut(**vars(card)) for card in result.cards],
        note_searched=result.note_searched,
    )


@router.get("/cards/{card_id}", response_model=CardDetailOut)
def get_card_detail(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CardDetailOut:
    """401 / 404 내 카드 아님."""
    if not 1 <= card_id <= MAX_DB_ID:
        raise _not_found()
    try:
        return _detail(get_card(db, user_id=current_user.id, card_id=card_id))
    except CardNotFound as exc:
        raise _not_found() from exc


# --- 저장 · 버리기 · 내 답 ---


# 본문 크기 상한(F-006 1차 리뷰 R2): 길이 검사(제목 100자 · 답 2,000자)는 공백을 정리한 뒤 서비스에서 하지만,
# 터무니없이 큰 본문은 서비스까지 가기 전에 422로 막는다. 공백 정리 전 길이라 여유를 둔다.
TITLE_BODY_MAX_CHARS = CARD_TITLE_MAX_CHARS * 10
ANSWER_BODY_MAX_CHARS = CARD_MAX_ANSWER_CHARS * 5


class SaveCardIn(BaseModel):
    title: str = Field(max_length=TITLE_BODY_MAX_CHARS)


@router.post("/cards/{card_id}/save", response_model=CardDetailOut)
def save_card_endpoint(
    card_id: int,
    body: SaveCardIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CardDetailOut:
    """401 / 404 내 카드 아님 / 422 제목이 비었거나 김. 이미 저장한 카드면 제목만 바꾼다."""
    if not 1 <= card_id <= MAX_DB_ID:
        raise _not_found()
    try:
        return _detail(save_card(db, user_id=current_user.id, card_id=card_id, title=body.title))
    except CardNotFound as exc:
        raise _not_found() from exc
    except InvalidCardInput as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card_endpoint(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """401 / 404 내 카드 아님."""
    if not 1 <= card_id <= MAX_DB_ID:
        raise _not_found()
    try:
        delete_card(db, user_id=current_user.id, card_id=card_id)
    except CardNotFound as exc:
        raise _not_found() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class UpdateFieldIn(BaseModel):
    answer: str | None = Field(default=None, max_length=ANSWER_BODY_MAX_CHARS)  # 비우면 답을 지움
    remove_quote: bool = False  # [인용 빼기]


@router.put("/cards/{card_id}/fields/{slot}", response_model=CardDetailOut)
def update_field_endpoint(
    card_id: int,
    slot: Slot,
    body: UpdateFieldIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CardDetailOut:
    """401 / 404 내 카드 아님 / 422 칸 이름 틀림 · 답이 너무 김."""
    if not 1 <= card_id <= MAX_DB_ID:
        raise _not_found()
    try:
        card = update_field(
            db,
            user_id=current_user.id,
            card_id=card_id,
            slot=slot,
            answer=body.answer,
            remove_quote=body.remove_quote,
        )
    except CardNotFound as exc:
        raise _not_found() from exc
    except InvalidCardInput as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _detail(card)
