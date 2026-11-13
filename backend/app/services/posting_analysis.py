"""공고 분석 — ① 요구 역량 뽑기 · ② 경험 카드 매칭 (F-007 완료 기준 2 · 3 · 5 · 6, 설계 원칙 1 · 2 · 3 · 4 · 5 · 6).

분석은 요청 두 번(각각 AI 1번, 사용자 확인 2026-11-12). 한 요청에 묶으면 최대 360초라 프록시 상한 200초(T-005)를 넘는다.
화면은 ①이 끝나면 자동으로 ②를 부르고, ②만 실패하면 ① 결과는 남고 [매칭 다시].

① 역량 뽑기 — 공고당 한 번(남긴 역량이 1개 이상이면 extracted_at을 적고, 다시 부르면 409)
1. prepare_extract (DB): 내 공고인지, 이미 뽑았는지, 하루 상한, 공고 선점.
2. request_requirements (AI): 공고 본문을 보내 역량 이름 · 필수/우대 · 공고 원문 인용을 받는다(complete_json).
3. check_requirements: 인용이 공고 본문에 글자 그대로 없으면 그 역량을 버린다(지어낸 요구일 수 있음).
4. save_extract (DB): 역량 · 평가 로그 저장, 사용량 기록, 선점 해제.

② 매칭 — 몇 번이든(사용자 확인 2026-11-12 — 새 카드를 저장한 뒤 [매칭 다시]). 다시 하면 이전 매칭을 새 결과로 바꾼다
1. prepare_match (DB): 역량마다 내 저장 카드에서 키워드 점수 상위 5장을 후보로 고른다(사용자 조건, D-004).
   후보가 하나도 없으면 AI를 부르지 않는다(모든 역량이 '근거 없음').
2. request_matches (AI): 후보 카드의 제목 · 칸 글(인용 · 내 답)만 보낸다(원칙 6).
3. check_matches: '그 역량에 보낸 후보 안의 카드인지' · '인용이 그 카드 칸에 글자 그대로 있는지' 검사.
4. save_match (DB): 이전 매칭을 지우고 새 매칭 · 평가 로그 저장, matched_at, 사용량, 선점 해제.

파일 나눔(1차 리뷰 R1-3): 이 파일은 선점 · 저장 · 사용량 흐름만. 순수 부분은 posting_extraction(①) · posting_matching(②) ·
posting_checks(버린 이유 이름) · posting_mock(가짜 답).

AI가 쓴 글 중 저장하는 것: 역량 이름 · 매칭 이유(화면에 AI 글로 보여 줌). 근거는 항상 원문 인용(공고 · 카드)이다(D-003).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import CARD_STATUS_SAVED
from app.db.models import Application, Card, PostingAnalysisLog, PostingRequirement, RequirementMatch
from app.korea_time import now_utc
from app.llm.base import LLMError, LLMUsage, Message
from app.llm.structured import StructuredReply
from app.services import note_claim
from app.services.application_service import ApplicationNotFound, get_application_for_user
from app.services.note_claim import ClaimLost, ClaimRules, OtherAIWorkInProgress  # noqa: F401 — 라우터 · 테스트가 여기서 가져감
from app.services.posting_checks import DROP_CARD_GONE, OUTCOME_NO_CANDIDATES, OUTCOME_NONE_FOUND
from app.services.posting_extraction import RequirementBatchIn, build_extract_messages, check_requirements
from app.services.posting_matching import (
    CardText,
    MatchBatchIn,
    MatchCheckResult,
    RequirementForMatch,
    build_match_messages,
    check_matches,
    load_saved_cards,
    pick_candidates,
)
from app.services.usage_service import (
    FEATURE_POSTING_EXTRACT,
    FEATURE_POSTING_MATCH,
    OUTCOME_OK,
    OUTCOME_SAVE_FAILED,
    DailyUsage,
    daily_usage,
    ensure_within_daily_limit,
    outcome_for,
    record_usage,
)

logger = logging.getLogger(__name__)

STEP_EXTRACT = "extract"
STEP_MATCH = "match"


class RequirementsAlreadyExtracted(Exception):
    """이 공고는 이미 요구 역량을 뽑았다(공고당 한 번). AI를 부르지 않는다."""


class RequirementsNotExtracted(Exception):
    """매칭하려는데 아직 요구 역량을 뽑지 않았다. AI를 부르지 않는다."""


class AnalysisInProgress(Exception):
    """같은 공고를 다른 요청이 분석하는 중이다(① · ② 공통). AI를 부르지 않는다."""


_CLAIM_RULES = ClaimRules(
    table=note_claim.APPLICATION_CLAIMS,
    in_progress=AnalysisInProgress,
    already_done=None,
    label="공고 분석",
)


# --- 두 단계 공통: 계획 · 로그 · 실패 정리 ---


@dataclass(frozen=True)
class AnalysisPlan:
    user_id: int
    application_id: int
    step: str
    feature: str
    usage_before: DailyUsage
    messages: list[Message]
    claimed_at: datetime  # 이 요청이 잡은 선점의 시각(해제 때 내 선점인지 확인)
    items_sent: int  # ① 보낸 공고 글자 수 / ② 후보가 있어 보낸 역량 수
    cards_sent: int  # ② 보낸 카드 수(①은 0)


def _claim(db: Session, *, user_id: int, application_id: int, now: datetime | None) -> datetime:
    return note_claim.claim_target(
        db, _CLAIM_RULES, user_id=user_id, target_id=application_id, at=now if now is not None else now_utc()
    )


def _release_statement(plan: AnalysisPlan):  # noqa: ANN202
    return note_claim.release_statement(
        _CLAIM_RULES, user_id=plan.user_id, target_id=plan.application_id, claimed_at=plan.claimed_at
    )


def _release_owned_claim(db: Session, plan: AnalysisPlan) -> None:
    """저장 트랜잭션 안에서 내 선점을 지운다. 지운 줄이 1이 아니면 ClaimLost(다른 요청이 가져감 · 공고가 지워짐)."""
    if db.execute(_release_statement(plan)).rowcount != 1:
        raise ClaimLost


def release_claim(db: Session, plan: AnalysisPlan) -> None:
    note_claim.release_claim(
        db, _CLAIM_RULES, user_id=plan.user_id, target_id=plan.application_id, claimed_at=plan.claimed_at
    )


def _log(plan: AnalysisPlan, *, kept: int, drop_reasons: dict[str, int], outcome: str, at: datetime) -> PostingAnalysisLog:
    return PostingAnalysisLog(
        user_id=plan.user_id,
        application_id=plan.application_id,
        step=plan.step,
        items_sent=plan.items_sent,
        cards_sent=plan.cards_sent,
        kept=kept,
        drop_reasons=drop_reasons,
        outcome=outcome,
        created_at=at,
    )


def _fail_save(db: Session, plan: AnalysisPlan, usage: LLMUsage, exc: Exception, *, at: datetime) -> None:
    """저장이 실패했을 때(① · ② 공통): 되돌리고, AI는 이미 불렀으니 사용량은 기록하고, 선점을 푼다.

    부르는 쪽이 원래 오류를 다시 올린다. 다만 AI를 부르는 동안 공고가 지워졌으면(선점도 CASCADE로 사라져 ClaimLost)
    '저장 실패'(500)가 아니라 '없는 공고'(404)로 알리도록 ApplicationNotFound를 올린다(1차 리뷰 R3).
    """
    db.rollback()
    # 종류 이름만 남긴다(예외 문구에는 DB 접속 정보 · 원문이 섞일 수 있어서)
    logger.warning(
        "공고 분석 저장 실패 step=%s user_id=%s application_id=%s error=%s",
        plan.step,
        plan.user_id,
        plan.application_id,
        type(exc).__name__,
    )
    record_usage(db, user_id=plan.user_id, feature=plan.feature, usage=usage, outcome=OUTCOME_SAVE_FAILED, now=at)
    release_claim(db, plan)
    if isinstance(exc, ClaimLost) and get_application_for_user(db, user_id=plan.user_id, application_id=plan.application_id) is None:
        raise ApplicationNotFound from exc


def save_failed(db: Session, plan: AnalysisPlan, error: LLMError, *, now: datetime | None = None) -> int:
    """AI 호출이 실패했을 때: 평가 로그 · 사용량을 남기고 선점을 푼다. 오늘 남은 호출 수를 돌려준다.

    로그 저장이 실패해도 원래 AI 오류를 사용자에게 알리는 게 우선이라 여기서 오류를 올리지 않는다.
    """
    at = now if now is not None else now_utc()
    outcome = outcome_for(error)
    db.add(_log(plan, kept=0, drop_reasons={}, outcome=outcome, at=at))
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("공고 분석 로그 저장 실패 user_id=%s error=%s", plan.user_id, type(exc).__name__)
    release_claim(db, plan)
    record_usage(db, user_id=plan.user_id, feature=plan.feature, usage=error.usage, outcome=outcome, now=at)
    return max(plan.usage_before.remaining - error.usage.calls, 0)


def abandon(db: Session, plan: AnalysisPlan, *, now: datetime | None = None) -> None:
    """AI 호출이 LLMError가 아닌 이유(예상 못 한 오류 · 요청 취소)로 끝났을 때. 사용량은 1회로 센다(D-018)."""
    try:
        save_failed(db, plan, LLMError("예상 못 한 오류", usage=LLMUsage(calls=1)), now=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("공고 분석 정리 실패 user_id=%s error=%s", plan.user_id, type(exc).__name__)
        release_claim(db, plan)


# --- ① 요구 역량 뽑기 (보내는 내용 · 검사는 posting_extraction) ---


@dataclass(frozen=True)
class ExtractPlan(AnalysisPlan):
    posting_text: str = ""


def prepare_extract(db: Session, *, user_id: int, application_id: int, now: datetime | None = None) -> ExtractPlan:
    """ApplicationNotFound / RequirementsAlreadyExtracted / DailyLimitExceeded / AnalysisInProgress / OtherAIWorkInProgress.

    마지막에 공고를 선점한다. 끝나면 save_extract · save_failed · abandon 중 하나가 반드시 불려야 선점이 풀린다.
    """
    application = get_application_for_user(db, user_id=user_id, application_id=application_id)
    if application is None:
        raise ApplicationNotFound
    if application.extracted_at is not None:
        raise RequirementsAlreadyExtracted
    usage_before = ensure_within_daily_limit(db, user_id=user_id, now=now)
    claimed_at = _claim(db, user_id=user_id, application_id=application.id, now=now)
    return ExtractPlan(
        user_id=user_id,
        application_id=application.id,
        step=STEP_EXTRACT,
        feature=FEATURE_POSTING_EXTRACT,
        usage_before=usage_before,
        messages=build_extract_messages(application),
        claimed_at=claimed_at,
        items_sent=len(application.posting_text),
        cards_sent=0,
        posting_text=application.posting_text,
    )


@dataclass(frozen=True)
class ExtractOutcome:
    application_id: int
    requirement_count: int  # 0이면 '역량을 찾지 못함'(다시 누를 수 있음)
    drop_reasons: dict[str, int]
    remaining_today: int


def save_extract(
    db: Session, plan: ExtractPlan, reply: StructuredReply[RequirementBatchIn], *, now: datetime | None = None
) -> ExtractOutcome:
    """검사를 통과한 역량 · 평가 로그를 한 번에 저장하고 선점을 푼다. 남은 역량이 있으면 extracted_at을 적는다.

    저장이 실패해도 AI는 이미 불렀으므로 사용량은 기록한 뒤 오류를 올린다. 내 선점을 다른 요청이 가져갔거나
    공고가 지워졌으면(ClaimLost) 저장하지 않는다.
    """
    at = now if now is not None else now_utc()
    try:
        checked = check_requirements(reply.value.requirements, plan.posting_text)
        drop_reasons = dict(checked.drop_reasons)
        outcome = OUTCOME_OK if checked.kept else OUTCOME_NONE_FOUND
        if checked.kept:
            marked = db.execute(
                update(Application)
                .where(
                    Application.id == plan.application_id,
                    Application.user_id == plan.user_id,
                    Application.extracted_at.is_(None),
                )
                .values(extracted_at=at, updated_at=at)
            ).rowcount
            if marked != 1:
                raise ClaimLost
            db.add_all(
                PostingRequirement(
                    user_id=plan.user_id,
                    application_id=plan.application_id,
                    position=position,
                    name=item.name,
                    kind=item.kind,
                    quote=item.quote,
                    quote_start=item.quote_start,
                    quote_end=item.quote_end,
                )
                for position, item in enumerate(checked.kept)
            )
        db.add(_log(plan, kept=len(checked.kept), drop_reasons=drop_reasons, outcome=outcome, at=at))
        _release_owned_claim(db, plan)
        db.commit()
    except Exception as exc:
        _fail_save(db, plan, reply.usage, exc, at=at)
        raise
    record_usage(db, user_id=plan.user_id, feature=plan.feature, usage=reply.usage, outcome=OUTCOME_OK, now=at)
    logger.info(
        "요구 역량 뽑기 user_id=%s application_id=%s chars=%d kept=%d dropped=%s",
        plan.user_id,
        plan.application_id,
        plan.items_sent,
        len(checked.kept),
        drop_reasons,
    )
    return ExtractOutcome(
        application_id=plan.application_id,
        requirement_count=len(checked.kept),
        drop_reasons=drop_reasons,
        remaining_today=max(plan.usage_before.remaining - reply.usage.calls, 0),
    )


# --- ② 매칭 (후보 · 보내는 내용 · 검사는 posting_matching) ---


@dataclass(frozen=True)
class MatchPlan(AnalysisPlan):
    requirement_ids: tuple[int, ...] = ()  # 이 공고의 역량 전부(이전 매칭을 지울 범위)
    candidates: dict[int, list[int]] = field(default_factory=dict)
    cards: dict[int, CardText] = field(default_factory=dict)

    @property
    def needs_ai(self) -> bool:
        return bool(self.candidates)


def prepare_match(db: Session, *, user_id: int, application_id: int, now: datetime | None = None) -> MatchPlan:
    """ApplicationNotFound / RequirementsNotExtracted / DailyLimitExceeded(후보가 있을 때만) /
    AnalysisInProgress / OtherAIWorkInProgress. 후보가 없으면 needs_ai=False — AI 없이 save_match(reply=None)."""
    application = get_application_for_user(db, user_id=user_id, application_id=application_id)
    if application is None:
        raise ApplicationNotFound
    if application.extracted_at is None:
        raise RequirementsNotExtracted
    requirements = [
        RequirementForMatch(id=row.id, name=row.name, kind=row.kind, quote=row.quote)
        for row in db.scalars(
            select(PostingRequirement)
            .where(PostingRequirement.user_id == user_id, PostingRequirement.application_id == application.id)
            .order_by(PostingRequirement.position)
        ).all()
    ]
    saved_cards = load_saved_cards(db, user_id=user_id)
    candidates = pick_candidates(requirements, saved_cards)
    sent_ids = {card_id for picked in candidates.values() for card_id in picked}
    cards = {card.id: card for card in saved_cards if card.id in sent_ids}
    usage_before = (
        ensure_within_daily_limit(db, user_id=user_id, now=now) if candidates else daily_usage(db, user_id=user_id, now=now)
    )
    claimed_at = _claim(db, user_id=user_id, application_id=application.id, now=now)
    return MatchPlan(
        user_id=user_id,
        application_id=application.id,
        step=STEP_MATCH,
        feature=FEATURE_POSTING_MATCH,
        usage_before=usage_before,
        messages=build_match_messages(requirements, candidates, cards) if candidates else [],
        claimed_at=claimed_at,
        items_sent=len(candidates),
        cards_sent=len(cards),
        requirement_ids=tuple(item.id for item in requirements),
        candidates=candidates,
        cards=cards,
    )


@dataclass(frozen=True)
class MatchOutcome:
    application_id: int
    matches: int
    matched_requirements: int
    requirements_sent: int
    cards_sent: int
    drop_reasons: dict[str, int]
    remaining_today: int


def save_match(
    db: Session, plan: MatchPlan, reply: StructuredReply[MatchBatchIn] | None, *, now: datetime | None = None
) -> MatchOutcome:
    """이전 매칭을 지우고 검사를 통과한 매칭 · 평가 로그를 한 번에 저장한다. matched_at을 적고 선점을 푼다.

    reply가 None이면 후보가 없어 AI를 부르지 않은 경우다(모든 역량이 '근거 없음').
    AI를 부르는 동안 지워진 카드 · 저장을 취소한 카드는 빼고 저장한다(DROP_CARD_GONE).
    """
    at = now if now is not None else now_utc()
    usage = reply.usage if reply is not None else LLMUsage(calls=0)
    try:
        checked = check_matches(reply.value.matches, plan.candidates, plan.cards) if reply is not None else MatchCheckResult()
        still_saved = set(
            db.scalars(
                select(Card.id).where(
                    Card.user_id == plan.user_id,
                    Card.status == CARD_STATUS_SAVED,
                    Card.id.in_({item.card_id for item in checked.kept}),
                )
            ).all()
        ) if checked.kept else set()
        kept = [item for item in checked.kept if item.card_id in still_saved]
        if len(kept) < len(checked.kept):
            checked.drop_reasons[DROP_CARD_GONE] += len(checked.kept) - len(kept)
        drop_reasons = dict(checked.drop_reasons)
        if reply is None:
            outcome = OUTCOME_NO_CANDIDATES
        else:
            outcome = OUTCOME_OK if kept else OUTCOME_NONE_FOUND
        if plan.requirement_ids:
            db.execute(
                delete(RequirementMatch).where(
                    RequirementMatch.user_id == plan.user_id,
                    RequirementMatch.requirement_id.in_(plan.requirement_ids),
                )
            )
        db.add_all(
            RequirementMatch(
                user_id=plan.user_id,
                requirement_id=item.requirement_id,
                card_id=item.card_id,
                slot=item.slot,
                quote=item.quote,
                quote_source=item.quote_source,
                quote_start=item.quote_start,
                quote_end=item.quote_end,
                reason=item.reason,
                created_at=at,
            )
            for item in kept
        )
        db.execute(
            update(Application)
            .where(Application.id == plan.application_id, Application.user_id == plan.user_id)
            .values(matched_at=at, updated_at=at)
        )
        db.add(_log(plan, kept=len(kept), drop_reasons=drop_reasons, outcome=outcome, at=at))
        _release_owned_claim(db, plan)
        db.commit()
    except Exception as exc:
        _fail_save(db, plan, usage, exc, at=at)
        raise
    record_usage(db, user_id=plan.user_id, feature=plan.feature, usage=usage, outcome=OUTCOME_OK, now=at)
    logger.info(
        "매칭 user_id=%s application_id=%s requirements=%d cards=%d kept=%d dropped=%s",
        plan.user_id,
        plan.application_id,
        plan.items_sent,
        plan.cards_sent,
        len(kept),
        drop_reasons,
    )
    return MatchOutcome(
        application_id=plan.application_id,
        matches=len(kept),
        matched_requirements=len({item.requirement_id for item in kept}),
        requirements_sent=plan.items_sent,
        cards_sent=plan.cards_sent,
        drop_reasons=drop_reasons,
        remaining_today=max(plan.usage_before.remaining - usage.calls, 0),
    )
