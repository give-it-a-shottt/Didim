"""지원(공고) API (F-007).

POST   /api/applications                         — 공고 추가(붙여 넣은 본문 · 문항). URL은 링크로 저장만(D-002).
GET    /api/applications                         — 목록(D-day 순 · 상태 · 분석 진행).
GET    /api/applications/{id}                    — 상세(공고 본문 · 문항 · 요구 역량 · 역량별 매칭 카드).
PATCH  /api/applications/{id}                    — 상태 · 마감일 바꾸기.
DELETE /api/applications/{id}                    — 삭제.
POST   /api/applications/{id}/requirements       — ① 요구 역량 뽑기(AI 1번, 공고당 한 번).
POST   /api/applications/{id}/matches            — ② 매칭(AI 1번, 몇 번이든 — 이전 매칭을 바꿈). 후보 카드가 없으면 AI 없이 끝.

AI 엔드포인트는 문제 만들기 · 카드 후보 찾기(api/cards.py)와 같은 구조다: 일반 함수(def)라 작업 스레드에서 DB를 다루고,
AI 호출(async, 최대 180초)만 anyio.from_thread.run으로 이벤트 루프에 맡긴다.
"""

from datetime import date, datetime
from typing import Literal

import anyio.from_thread
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import OTHER_AI_WORK_DETAIL, daily_limit_detail, llm_client_or_500, llm_error_status
from app.api.schemas import RAW_INPUT_SLACK, ServiceOut
from app.config import (
    APPLICATION_COMPANY_MAX_CHARS,
    APPLICATION_MAX_QUESTIONS,
    APPLICATION_QUESTION_MAX_CHARS,
    APPLICATION_ROLE_MAX_CHARS,
    APPLICATION_URL_MAX_CHARS,
    MAX_DB_ID,
    POSTING_TEXT_MAX_CHARS,
)
from app.db.models import User
from app.db.session import get_db
from app.llm import LLMClient, LLMError
from app.services.application_service import (
    ApplicationNotFound,
    InvalidApplicationInput,
    QuestionInput,
    create_application,
    delete_application,
    get_application_detail,
    list_applications,
    update_application,
)
from app.services.draft_evidence import unsupported_counts
from app.services.posting_analysis import (
    AnalysisInProgress,
    OtherAIWorkInProgress,
    RequirementsAlreadyExtracted,
    RequirementsNotExtracted,
    abandon,
    prepare_extract,
    prepare_match,
    save_extract,
    save_failed,
    save_match,
)
from app.services.posting_extraction import request_requirements
from app.services.posting_matching import request_matches
from app.services.posting_mock import mock_analysis_responder
from app.services.usage_service import DailyLimitExceeded

router = APIRouter(tags=["applications"])

APPLICATION_NOT_FOUND_DETAIL = "공고를 찾을 수 없어요."
ALREADY_EXTRACTED_DETAIL = "이 공고는 이미 요구 역량을 뽑았어요."
NOT_EXTRACTED_DETAIL = "먼저 공고에서 요구 역량을 뽑아 주세요."
IN_PROGRESS_DETAIL = "이 공고를 분석하는 중이에요. 잠시 뒤 다시 확인해 주세요."
EXTRACT_SAVE_FAILED_DETAIL = "뽑은 요구 역량을 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요."
MATCH_SAVE_FAILED_DETAIL = "매칭 결과를 저장하지 못했어요. 잠시 뒤 [매칭 다시]를 눌러 주세요."
EXTRACT_INVALID_OUTPUT_DETAIL = "AI 답이 정해진 형식에 맞지 않아 요구 역량을 뽑지 못했어요. 잠시 뒤 다시 시도해 주세요."
MATCH_INVALID_OUTPUT_DETAIL = "AI 답이 정해진 형식에 맞지 않아 매칭하지 못했어요. 잠시 뒤 [매칭 다시]를 눌러 주세요."

ApplicationStatus = Literal["ready", "writing", "submitted"]  # app/config.py APPLICATION_STATUSES와 같은 값(테스트로 확인)


def get_analysis_llm_client() -> LLMClient:
    """공고 분석에 쓰는 AI(테스트에서 바꿔 끼움). LLM_PROVIDER=mock(기본)이면 공고 줄 · 카드 글로 가짜 답을 만드는 mock."""
    return llm_client_or_500(mock_analysis_responder)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=APPLICATION_NOT_FOUND_DETAIL)


def _check_id(application_id: int) -> None:
    if not 1 <= application_id <= MAX_DB_ID:
        raise _not_found()


def _invalid(exc: InvalidApplicationInput) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


# --- 만들기 ---


class QuestionIn(BaseModel):
    text: str = Field(max_length=APPLICATION_QUESTION_MAX_CHARS * RAW_INPUT_SLACK)
    char_limit: int | None = None


class CreateApplicationIn(BaseModel):
    company: str = Field(max_length=APPLICATION_COMPANY_MAX_CHARS * RAW_INPUT_SLACK)
    role: str = Field(max_length=APPLICATION_ROLE_MAX_CHARS * RAW_INPUT_SLACK)
    deadline: date | None = None
    url: str | None = Field(default=None, max_length=APPLICATION_URL_MAX_CHARS * RAW_INPUT_SLACK)
    posting_text: str = Field(max_length=POSTING_TEXT_MAX_CHARS * RAW_INPUT_SLACK)
    questions: list[QuestionIn] = Field(default_factory=list, max_length=APPLICATION_MAX_QUESTIONS * RAW_INPUT_SLACK)


class QuestionOut(ServiceOut):
    id: int
    position: int
    text: str
    char_limit: int | None


class MatchOut(ServiceOut):
    id: int
    card_id: int
    card_title: str
    slot: str
    quote: str
    quote_source: str  # quote(카드의 원문 인용) · answer(카드의 내 답)
    quote_start: int
    quote_end: int
    reason: str  # AI가 쓴 맞는 이유


class RequirementOut(ServiceOut):
    id: int
    position: int
    name: str
    kind: str
    quote: str
    quote_start: int
    quote_end: int
    matches: list[MatchOut]


class ApplicationDetailOut(ServiceOut):
    id: int
    company: str
    role: str
    deadline: date | None
    days_left: int | None
    url: str | None
    posting_text: str
    status: str
    extracted_at: datetime | None
    matched_at: datetime | None
    created_at: datetime
    updated_at: datetime
    questions: list[QuestionOut]
    requirements: list[RequirementOut]
    # 자소서 초안 전체에서 근거 없는 문장 수(F-008 — '제출'로 바꿀 때 확인창). 공고 서비스가 초안을 몰라도 되게 라우터가 채운다(_detail_out)
    unsupported_sentence_count: int = 0


def _detail_out(db: Session, *, user_id: int, application_id: int) -> ApplicationDetailOut:
    """공고 상세 + 자소서의 근거 없는 문장 수. 두 서비스를 라우터가 조합한다(공고 서비스 → 초안 의존을 없앰, F-008 3차 리뷰 R1)."""
    detail = ApplicationDetailOut.model_validate(get_application_detail(db, user_id=user_id, application_id=application_id))
    unsupported = sum(unsupported_counts(db, user_id=user_id, application_id=application_id).values())
    return detail.model_copy(update={"unsupported_sentence_count": unsupported})


@router.post("/applications", response_model=ApplicationDetailOut, status_code=status.HTTP_201_CREATED)
def create_application_endpoint(
    body: CreateApplicationIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationDetailOut:
    """401 / 422 입력이 비었거나 김 · 링크 형식 · 제어 문자. 상태는 '준비'로 시작한다."""
    try:
        application_id = create_application(
            db,
            user_id=current_user.id,
            company=body.company,
            role=body.role,
            deadline=body.deadline,
            url=body.url,
            posting_text=body.posting_text,
            questions=[QuestionInput(text=item.text, char_limit=item.char_limit) for item in body.questions],
        )
    except InvalidApplicationInput as exc:
        raise _invalid(exc) from exc
    return _detail_out(db, user_id=current_user.id, application_id=application_id)


# --- 목록 · 상세 ---


class ApplicationSummaryOut(ServiceOut):
    id: int
    company: str
    role: str
    deadline: date | None
    days_left: int | None
    status: str
    url: str | None
    requirement_count: int
    matched_requirement_count: int
    extracted: bool
    matched: bool
    created_at: datetime
    updated_at: datetime


class ApplicationListResponse(BaseModel):
    total: int
    applications: list[ApplicationSummaryOut]


@router.get("/applications", response_model=ApplicationListResponse)
def get_applications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationListResponse:
    """401. D-day 순(마감 남음 → 지남 → 마감일 없음), 최대 MAX_APPLICATION_LIST개."""
    result = list_applications(db, user_id=current_user.id)
    return ApplicationListResponse(
        total=result.total,
        applications=[ApplicationSummaryOut.model_validate(item) for item in result.applications],
    )


@router.get("/applications/{application_id}", response_model=ApplicationDetailOut)
def get_application_endpoint(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationDetailOut:
    """401 / 404 내 공고 아님."""
    _check_id(application_id)
    try:
        return _detail_out(db, user_id=current_user.id, application_id=application_id)
    except ApplicationNotFound as exc:
        raise _not_found() from exc


# --- 바꾸기 · 지우기 ---


class UpdateApplicationIn(BaseModel):
    status: ApplicationStatus | None = None
    deadline: date | None = None  # 보낸 경우에만 바꾼다(null = 마감일 지움)


@router.patch("/applications/{application_id}", response_model=ApplicationDetailOut)
def update_application_endpoint(
    application_id: int,
    body: UpdateApplicationIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationDetailOut:
    """401 / 404 내 공고 아님 / 422 상태 값 틀림. 공고 본문 · 회사 · 직무는 바꾸지 않는다."""
    _check_id(application_id)
    changes: dict[str, object] = {}
    if body.status is not None:
        changes["status"] = body.status
    if "deadline" in body.model_fields_set:
        changes["deadline"] = body.deadline
    try:
        update_application(db, user_id=current_user.id, application_id=application_id, **changes)  # type: ignore[arg-type]
    except ApplicationNotFound as exc:
        raise _not_found() from exc
    except InvalidApplicationInput as exc:
        raise _invalid(exc) from exc
    return _detail_out(db, user_id=current_user.id, application_id=application_id)


@router.delete("/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application_endpoint(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """401 / 404 내 공고 아님. 문항 · 역량 · 매칭도 같이 지운다(카드는 그대로)."""
    _check_id(application_id)
    try:
        delete_application(db, user_id=current_user.id, application_id=application_id)
    except ApplicationNotFound as exc:
        raise _not_found() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- ① 요구 역량 뽑기 · ② 매칭 ---


def _prepare_errors(exc: Exception) -> HTTPException | None:
    """두 AI 엔드포인트가 같이 쓰는 '부르기 전' 오류 → HTTP."""
    if isinstance(exc, ApplicationNotFound):
        return _not_found()
    if isinstance(exc, RequirementsAlreadyExtracted):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ALREADY_EXTRACTED_DETAIL)
    if isinstance(exc, RequirementsNotExtracted):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOT_EXTRACTED_DETAIL)
    if isinstance(exc, AnalysisInProgress):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=IN_PROGRESS_DETAIL)
    if isinstance(exc, OtherAIWorkInProgress):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=OTHER_AI_WORK_DETAIL)
    if isinstance(exc, DailyLimitExceeded):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=daily_limit_detail(exc.usage.limit))
    return None


_PREPARE_ERRORS = (
    ApplicationNotFound,
    RequirementsAlreadyExtracted,
    RequirementsNotExtracted,
    AnalysisInProgress,
    OtherAIWorkInProgress,
    DailyLimitExceeded,
)


class ExtractResponse(ServiceOut):
    application_id: int
    requirement_count: int  # 0이면 '역량을 찾지 못함'(다시 누를 수 있음)
    drop_reasons: dict[str, int]
    remaining_today: int


@router.post(
    "/applications/{application_id}/requirements",
    response_model=ExtractResponse,
    status_code=status.HTTP_201_CREATED,
)
def extract_requirements_endpoint(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client: LLMClient = Depends(get_analysis_llm_client),
) -> ExtractResponse:
    """401 / 404 / 409 이미 뽑음 · 분석 중 · 다른 AI 작업 진행 중 / 429 하루 상한 / 502 AI 답 형식 오류 /
    503 AI 연결 안 됨 · AI 서버 한도 / 500 AI 설정 오류 · 저장 실패. 화면은 detail을 그대로 보여 준다."""
    _check_id(application_id)
    try:
        plan = prepare_extract(db, user_id=current_user.id, application_id=application_id)
    except _PREPARE_ERRORS as exc:
        raise _prepare_errors(exc) from exc  # type: ignore[misc]

    try:
        reply = anyio.from_thread.run(request_requirements, client, plan.messages)
    except LLMError as exc:
        save_failed(db, plan, exc)
        raise HTTPException(*llm_error_status(exc, invalid_output_detail=EXTRACT_INVALID_OUTPUT_DETAIL)) from exc
    except BaseException:  # 예상 못 한 오류 · 요청 취소 — 사용량 1회 · 로그를 남기고 선점을 풀어 다시 누를 수 있게
        abandon(db, plan)
        raise

    try:
        outcome = save_extract(db, plan, reply)
    except ApplicationNotFound as exc:  # AI를 부르는 동안 공고가 지워짐
        raise _not_found() from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=EXTRACT_SAVE_FAILED_DETAIL) from exc
    return ExtractResponse.model_validate(outcome)


class MatchResponse(ServiceOut):
    application_id: int
    matches: int
    matched_requirements: int  # 매칭 카드가 1장 이상인 역량 수
    requirements_sent: int  # 후보 카드가 있어 AI에 보낸 역량 수(0이면 AI를 부르지 않음)
    cards_sent: int
    drop_reasons: dict[str, int]
    remaining_today: int


@router.post(
    "/applications/{application_id}/matches",
    response_model=MatchResponse,
    status_code=status.HTTP_201_CREATED,
)
def match_requirements_endpoint(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client: LLMClient = Depends(get_analysis_llm_client),
) -> MatchResponse:
    """401 / 404 / 409 아직 역량을 안 뽑음 · 분석 중 · 다른 AI 작업 진행 중 / 429 하루 상한 / 502 / 503 / 500.
    다시 부르면 이전 매칭을 새 결과로 바꾼다."""
    _check_id(application_id)
    try:
        plan = prepare_match(db, user_id=current_user.id, application_id=application_id)
    except _PREPARE_ERRORS as exc:
        raise _prepare_errors(exc) from exc  # type: ignore[misc]

    reply = None
    if plan.needs_ai:
        try:
            reply = anyio.from_thread.run(request_matches, client, plan.messages)
        except LLMError as exc:
            save_failed(db, plan, exc)
            raise HTTPException(*llm_error_status(exc, invalid_output_detail=MATCH_INVALID_OUTPUT_DETAIL)) from exc
        except BaseException:
            abandon(db, plan)
            raise

    try:
        outcome = save_match(db, plan, reply)
    except ApplicationNotFound as exc:  # AI를 부르는 동안 공고가 지워짐
        raise _not_found() from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=MATCH_SAVE_FAILED_DETAIL) from exc
    return MatchResponse.model_validate(outcome)
