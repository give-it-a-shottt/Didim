"""면접 연습 — 질문 만들기(AI 1번) · 읽기(근거 다시 검사) · 메모 · 공고별 모아 보기 (F-009, 설계 원칙 1 · 2 · 3 · 4 · 5 · 6).

[면접 질문 만들기] — 카드당 한 번, AI 1번(사용자 확인 2026-11-13). 다시 만들기는 2차 후보.
1. prepare_interview (DB): 내 카드인지, 저장 카드인지(후보는 막음 — 사용자 확인 2026-11-15), 이미 질문이 있는지,
   글이 있는 칸이 있는지(빈칸만이면 막음), 하루 상한, 카드 선점(card_interview_claims — D-020, 사용자당 AI 작업 1개).
2. request_interview_questions (AI): 그 카드의 글이 있는 칸만 보낸다(원칙 6, interview_writing).
3. check_interview_questions: 칸 · 인용 검사. 못 넘은 질문은 버린다(완료 기준 1).
4. save_interview (DB): 질문 · 평가 로그 저장, 사용량, 선점 해제. 남은 질문이 0개면 아무것도 저장하지 않는다(다시 누를 수 있음).

읽기 · 메모는 AI를 부르지 않는다. 근거 상태는 읽을 때마다 지금 카드 칸과 다시 비교한다(사용자 확인 2026-11-15 —
F-008 draft_evidence와 같은 find_in_card). 모든 조회에 user_id 조건(D-004).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, exists, select, update
from sqlalchemy.orm import Session

from app.config import CARD_STATUS_SAVED, INTERVIEW_MEMO_MAX_CHARS
from app.db.models import (
    Card,
    InterviewLog,
    InterviewQuestion,
    PostingRequirement,
    RequirementMatch,
)
from app.korea_time import now_utc
from app.llm.base import LLMError, LLMUsage, Message
from app.llm.structured import StructuredReply
from app.services import note_claim
from app.services.application_service import (
    ApplicationNotFound,
    get_application_for_user,
)
from app.services.card_service import CardNotFound
from app.services.draft_evidence import (
    EVIDENCE_CARD_GONE,
    EVIDENCE_CHANGED,
    EVIDENCE_OK,
    CardNow,
    find_in_card,
    load_cards_now,
)
from app.services.draft_view import matched_card_ids
from app.services.interview_writing import (
    CheckedQuestion,
    InterviewReplyIn,
    SentFields,
    build_interview_messages,
    check_interview_questions,
    sendable_slots,
)
from app.services.note_claim import ClaimLost, ClaimRules
from app.services.posting_matching import load_saved_cards
from app.services.text_clean import has_forbidden_control
from app.services.usage_service import (
    FEATURE_INTERVIEW_WRITE,
    OUTCOME_OK,
    OUTCOME_SAVE_FAILED,
    DailyUsage,
    ensure_within_daily_limit,
    outcome_for,
    record_usage,
)

logger = logging.getLogger(__name__)

OUTCOME_NO_QUESTIONS = "no_questions"  # 검사를 넘은 질문이 0개(아무것도 저장하지 않음)


class CardNotSaved(Exception):
    """후보 카드다 — 저장한 카드에서만 질문을 만든다(사용자 확인 2026-11-15). AI를 부르지 않는다."""


class QuestionsAlreadyExist(Exception):
    """이 카드에는 이미 질문이 있다 — 카드당 한 번(다시 만들기는 2차 후보). AI를 부르지 않는다."""


class NoFieldText(Exception):
    """글(원문 인용 · 내 답)이 있는 칸이 없다 — 근거 없이 만들면 AI 창작이 된다(D-003). AI를 부르지 않는다."""


class InterviewWriteInProgress(Exception):
    """같은 카드에서 다른 요청이 질문을 만드는 중이다. AI를 부르지 않는다."""


class InterviewQuestionNotFound(Exception):
    """내 질문이 아니거나 없는 질문(카드가 지워진 경우 포함)."""


class InvalidMemo(Exception):
    """메모가 너무 길거나 쓸 수 없는 글자가 있다. 화면에 그대로 보여 줄 문구."""


_CLAIM_RULES = ClaimRules(
    table=note_claim.INTERVIEW_CLAIMS,
    in_progress=InterviewWriteInProgress,
    already_done=None,
    label="면접 질문",
)


def _has_questions(db: Session, *, user_id: int, card_id: int) -> bool:
    return bool(
        db.scalar(
            select(exists().where(InterviewQuestion.user_id == user_id, InterviewQuestion.card_id == card_id))
        )
    )


# --- [면접 질문 만들기] ---


@dataclass(frozen=True)
class InterviewPlan:
    user_id: int
    card_id: int
    usage_before: DailyUsage
    messages: list[Message]
    claimed_at: datetime
    sent: SentFields  # 보낸 칸(검사 기준)


def prepare_interview(db: Session, *, user_id: int, card_id: int, now: datetime | None = None) -> InterviewPlan:
    """CardNotFound / CardNotSaved / QuestionsAlreadyExist / NoFieldText / DailyLimitExceeded /
    InterviewWriteInProgress / OtherAIWorkInProgress. 끝나면 save_interview · save_failed · abandon 중 하나가 불려야 선점이 풀린다."""
    status = db.scalar(select(Card.status).where(Card.id == card_id, Card.user_id == user_id))
    if status is None:
        raise CardNotFound
    if status != CARD_STATUS_SAVED:
        raise CardNotSaved
    if _has_questions(db, user_id=user_id, card_id=card_id):
        raise QuestionsAlreadyExist
    cards = load_saved_cards(db, user_id=user_id, card_ids=[card_id])
    if not cards or not sendable_slots(cards[0]):
        raise NoFieldText
    usage_before = ensure_within_daily_limit(db, user_id=user_id, now=now)
    messages, sent = build_interview_messages(cards[0])
    claimed_at = note_claim.claim_target(
        db, _CLAIM_RULES, user_id=user_id, target_id=card_id, at=now if now is not None else now_utc()
    )
    # 위의 '이미 질문 있음' 확인과 선점 사이에 다른 요청이 질문을 저장하고 선점을 풀었을 수 있다 — 선점한 뒤 한 번 더 본다.
    # 안 보면 AI를 한 번 더 부르고 저장 때 유니크 제약에 걸려 500이 된다(1차 리뷰 R2 · R3).
    # 선점한 뒤 여기서 오류가 나면 선점을 풀고 올린다 — 라우터는 아직 plan이 없어 풀 수 없고, 안 풀면
    # 5분 동안 이 사용자의 모든 AI 작업이 409가 된다(D-020, 3차 리뷰 R2 · R3).
    try:
        already = _has_questions(db, user_id=user_id, card_id=card_id)
        # 위 SELECT가 연 트랜잭션을 닫고 DB 연결을 풀에 돌려준다 — 이대로 두면 AI 응답(최대 180초)을 기다리는 동안
        # 연결 하나가 'idle in transaction'으로 묶인다(2차 리뷰 R2). 읽기만 했으므로 rollback.
        db.rollback()
    except Exception:
        db.rollback()
        note_claim.release_claim(db, _CLAIM_RULES, user_id=user_id, target_id=card_id, claimed_at=claimed_at)
        raise
    if already:
        note_claim.release_claim(db, _CLAIM_RULES, user_id=user_id, target_id=card_id, claimed_at=claimed_at)
        raise QuestionsAlreadyExist
    return InterviewPlan(
        user_id=user_id, card_id=card_id, usage_before=usage_before, messages=messages, claimed_at=claimed_at, sent=sent
    )


def _log(plan: InterviewPlan, *, questions: int, kept: int, drop_reasons: dict[str, int], outcome: str, at: datetime) -> InterviewLog:
    return InterviewLog(
        user_id=plan.user_id,
        card_id=plan.card_id,
        fields_sent=len(plan.sent.slots),
        questions=questions,
        kept=kept,
        drop_reasons=drop_reasons,
        outcome=outcome,
        created_at=at,
    )


def release_claim(db: Session, plan: InterviewPlan) -> None:
    note_claim.release_claim(db, _CLAIM_RULES, user_id=plan.user_id, target_id=plan.card_id, claimed_at=plan.claimed_at)


def save_failed(db: Session, plan: InterviewPlan, error: LLMError, *, now: datetime | None = None) -> int:
    """AI 호출이 실패했을 때: 평가 로그 · 사용량을 남기고 선점을 푼다. 오늘 남은 호출 수를 돌려준다."""
    at = now if now is not None else now_utc()
    outcome = outcome_for(error)
    db.add(_log(plan, questions=0, kept=0, drop_reasons={}, outcome=outcome, at=at))
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 로그 저장이 실패해도 원래 AI 오류를 알리는 게 우선
        db.rollback()
        logger.warning("면접 질문 로그 저장 실패 user_id=%s error=%s", plan.user_id, type(exc).__name__)
    release_claim(db, plan)
    record_usage(db, user_id=plan.user_id, feature=FEATURE_INTERVIEW_WRITE, usage=error.usage, outcome=outcome, now=at)
    return max(plan.usage_before.remaining - error.usage.calls, 0)


def abandon(db: Session, plan: InterviewPlan, *, now: datetime | None = None) -> None:
    """AI 호출이 LLMError가 아닌 이유(예상 못 한 오류 · 요청 취소)로 끝났을 때. 사용량은 1회로 센다(D-018)."""
    try:
        save_failed(db, plan, LLMError("예상 못 한 오류", usage=LLMUsage(calls=1)), now=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("면접 질문 정리 실패 user_id=%s error=%s", plan.user_id, type(exc).__name__)
        release_claim(db, plan)


@dataclass(frozen=True)
class InterviewWriteOutcome:
    card_id: int
    written: bool  # False면 검사를 넘은 질문이 없어 아무것도 저장하지 않음(다시 누를 수 있음)
    questions: int  # 저장한 질문 수
    received: int  # AI가 준 질문 수(빈 질문 뺌)
    fields_sent: int
    drop_reasons: dict[str, int]
    remaining_today: int


def _rows(plan: InterviewPlan, questions: list[CheckedQuestion], at: datetime) -> list[InterviewQuestion]:
    return [
        InterviewQuestion(
            user_id=plan.user_id,
            card_id=plan.card_id,
            position=position,
            slot=item.slot,
            question=item.question,
            quote=item.quote,
            quote_source=item.quote_source,
            quote_start=item.quote_start,
            quote_end=item.quote_end,
            created_at=at,
            updated_at=at,
        )
        for position, item in enumerate(questions)
    ]


def save_interview(
    db: Session, plan: InterviewPlan, reply: StructuredReply[InterviewReplyIn], *, now: datetime | None = None
) -> InterviewWriteOutcome:
    """검사를 넘은 질문 · 평가 로그를 한 번에 저장한다. 0개면 질문은 저장하지 않는다.

    저장이 실패해도 AI는 이미 불렀으므로 사용량은 기록한 뒤 오류를 올린다. AI를 부르는 동안 카드가 지워졌거나
    저장을 취소했으면 CardNotFound(404 — 선점도 CASCADE로 사라짐).
    """
    at = now if now is not None else now_utc()
    try:
        checked = check_interview_questions(reply.value.questions, plan.sent)
        drop_reasons = dict(checked.drop_reasons)
        alive = db.scalar(
            select(Card.id).where(Card.id == plan.card_id, Card.user_id == plan.user_id, Card.status == CARD_STATUS_SAVED)
        )
        if alive is None:
            raise CardNotFound
        if checked.questions:
            db.add_all(_rows(plan, checked.questions, at))
        outcome = OUTCOME_OK if checked.questions else OUTCOME_NO_QUESTIONS
        db.add(_log(plan, questions=checked.received, kept=len(checked.questions), drop_reasons=drop_reasons, outcome=outcome, at=at))
        released = db.execute(
            note_claim.release_statement(_CLAIM_RULES, user_id=plan.user_id, target_id=plan.card_id, claimed_at=plan.claimed_at)
        ).rowcount
        if released != 1:
            raise ClaimLost
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(
            "면접 질문 저장 실패 user_id=%s card_id=%s error=%s", plan.user_id, plan.card_id, type(exc).__name__
        )
        record_usage(db, user_id=plan.user_id, feature=FEATURE_INTERVIEW_WRITE, usage=reply.usage, outcome=OUTCOME_SAVE_FAILED, now=at)
        release_claim(db, plan)
        if isinstance(exc, ClaimLost) and db.scalar(select(Card.id).where(Card.id == plan.card_id, Card.user_id == plan.user_id)) is None:
            raise CardNotFound from exc
        raise
    record_usage(db, user_id=plan.user_id, feature=FEATURE_INTERVIEW_WRITE, usage=reply.usage, outcome=OUTCOME_OK, now=at)
    logger.info(
        "면접 질문 user_id=%s card_id=%s fields=%d received=%d kept=%d dropped=%s",
        plan.user_id, plan.card_id, len(plan.sent.slots), checked.received, len(checked.questions), drop_reasons,
    )
    return InterviewWriteOutcome(
        card_id=plan.card_id,
        written=bool(checked.questions),
        questions=len(checked.questions),
        received=checked.received,
        fields_sent=len(plan.sent.slots),
        drop_reasons=drop_reasons,
        remaining_today=max(plan.usage_before.remaining - reply.usage.calls, 0),
    )


# --- 읽기 (근거 다시 검사) ---


@dataclass(frozen=True)
class QuestionView:
    id: int
    card_id: int
    position: int
    slot: str
    question: str
    quote: str
    quote_source: str
    evidence_status: str  # ok · changed(카드 칸 글이 바뀌어 인용이 없음) · card_gone(저장 카드가 아님)
    memo: str | None
    answered_at: datetime | None
    updated_at: datetime


def _evidence_status(row: InterviewQuestion, cards: dict[int, CardNow]) -> str:
    card = cards.get(row.card_id)
    if card is None:
        return EVIDENCE_CARD_GONE
    if find_in_card(card, slot=row.slot, source=row.quote_source, quote=row.quote) is None:
        return EVIDENCE_CHANGED
    return EVIDENCE_OK


def _view(row: InterviewQuestion, cards: dict[int, CardNow]) -> QuestionView:
    return QuestionView(
        id=row.id,
        card_id=row.card_id,
        position=row.position,
        slot=row.slot,
        question=row.question,
        quote=row.quote,
        quote_source=row.quote_source,
        evidence_status=_evidence_status(row, cards),
        memo=row.memo,
        answered_at=row.answered_at,
        updated_at=row.updated_at,
    )


def _questions_by_card(db: Session, *, user_id: int, card_ids: list[int]) -> dict[int, list[InterviewQuestion]]:
    if not card_ids:
        return {}
    rows = db.scalars(
        select(InterviewQuestion)
        .where(InterviewQuestion.user_id == user_id, InterviewQuestion.card_id.in_(card_ids))
        .order_by(InterviewQuestion.card_id, InterviewQuestion.position)
    ).all()
    grouped: dict[int, list[InterviewQuestion]] = {}
    for row in rows:
        grouped.setdefault(row.card_id, []).append(row)
    return grouped


def list_card_questions(db: Session, *, user_id: int, card_id: int) -> list[QuestionView]:
    """카드 상세의 '면접 질문' 칸. 질문이 없으면 빈 목록(내 카드인지는 부르는 쪽이 이미 확인)."""
    rows = _questions_by_card(db, user_id=user_id, card_ids=[card_id]).get(card_id, [])
    cards = load_cards_now(db, user_id=user_id, card_ids={card_id}) if rows else {}
    return [_view(row, cards) for row in rows]


# --- 메모 ---


def _clean_memo(memo: str | None) -> str | None:
    """앞뒤 공백만 정리한다(여러 줄 허용). 비면 None — '답하지 않음'으로 돌아간다."""
    cleaned = (memo or "").strip()
    if not cleaned:
        return None
    if has_forbidden_control(cleaned):
        raise InvalidMemo("쓸 수 없는 글자(제어 문자)가 들어 있어요.")
    if len(cleaned) > INTERVIEW_MEMO_MAX_CHARS:
        raise InvalidMemo(f"메모는 {INTERVIEW_MEMO_MAX_CHARS:,}자까지 쓸 수 있어요.")
    return cleaned


def update_memo(db: Session, *, user_id: int, question_id: int, memo: str | None, now: datetime | None = None) -> QuestionView:
    """질문의 내 답 메모를 저장한다. 비우면 answered_at도 비운다. InterviewQuestionNotFound / InvalidMemo.

    조건부 UPDATE로 한다 — 읽고 고치는 방식은 그 사이 카드가 지워지면 커밋에서 오류가 나서(F-008 3차 리뷰 R2와 같은 이유).
    """
    at = now if now is not None else now_utc()
    cleaned = _clean_memo(memo)
    changed = db.execute(
        update(InterviewQuestion)
        .where(InterviewQuestion.id == question_id, InterviewQuestion.user_id == user_id)
        .values(memo=cleaned, answered_at=at if cleaned else None, updated_at=at)
    ).rowcount
    if changed != 1:
        db.rollback()
        raise InterviewQuestionNotFound
    db.commit()
    row = db.scalar(select(InterviewQuestion).where(InterviewQuestion.id == question_id, InterviewQuestion.user_id == user_id))
    if row is None:  # 커밋 직후 카드가 지워짐
        raise InterviewQuestionNotFound
    return _view(row, load_cards_now(db, user_id=user_id, card_ids={row.card_id}))


# --- 지원 상세 [면접 연습] 탭 ---


@dataclass(frozen=True)
class CardInterviewView:
    card_id: int
    card_title: str
    note_title: str | None  # 카드가 나온 노트(지워졌으면 None) — 근거 패널의 출처
    requirement_names: list[str]  # 이 카드가 매칭된 역량 이름(공고에 나온 순서, 중복 없이) — 태그
    has_questions: bool  # 합치기 전에 질문이 있었는지 — False면 '질문 없는 카드'(카드 상세에서 만들 수 있음, 사용자 확인 2026-11-16)
    questions: list[QuestionView] = field(default_factory=list)  # 같은 글 질문을 합친 뒤(다른 카드 쪽으로 모두 합쳐지면 빈 목록)


@dataclass(frozen=True)
class ApplicationInterviewView:
    application_id: int
    analysis_done: bool  # False면 아직 공고 분석(매칭)을 안 함
    question_count: int
    answered_count: int
    cards: list[CardInterviewView]


def _requirement_names_by_card(db: Session, *, user_id: int, application_id: int) -> dict[int, list[str]]:
    rows = db.execute(
        select(RequirementMatch.card_id, PostingRequirement.name)
        .join(
            PostingRequirement,
            and_(PostingRequirement.id == RequirementMatch.requirement_id, PostingRequirement.user_id == user_id),
        )
        .where(RequirementMatch.user_id == user_id, PostingRequirement.application_id == application_id)
        .order_by(PostingRequirement.position)
    ).all()
    names: dict[int, list[str]] = {}
    for card_id, name in rows:
        card_names = names.setdefault(card_id, [])
        if name not in card_names:
            card_names.append(name)
    return names


def _merge_same_questions(grouped: dict[int, list[InterviewQuestion]], order: list[int]) -> dict[int, list[InterviewQuestion]]:
    """글이 같은 질문은 하나만 남긴다(Figma '겹치는 질문은 하나로', 사용자 확인 2026-11-15). 답한 질문이 있으면 그것을,
    없으면 카드 순서상 처음 것을 남긴다 — 질문 수 · 답한 수를 서버 한 곳에서 세려고(1차 리뷰 R1 · R4)."""
    keep: dict[str, InterviewQuestion] = {}
    for card_id in order:
        for row in grouped.get(card_id, []):
            key = " ".join(row.question.split())
            current = keep.get(key)
            if current is None or (current.answered_at is None and row.answered_at is not None):
                keep[key] = row
    kept_ids = {row.id for row in keep.values()}
    return {card_id: [row for row in rows if row.id in kept_ids] for card_id, rows in grouped.items()}


def get_application_interview(db: Session, *, user_id: int, application_id: int) -> ApplicationInterviewView:
    """이 공고에 매칭된 내 저장 카드별 질문(카드 하나는 한 번 — 역량 여러 개에 매칭돼도 태그만 여러 개). ApplicationNotFound.

    같은 글의 질문은 하나로 합친 뒤 센다(_merge_same_questions). 합쳐져 질문이 0개가 된 카드도 목록에 남는다.
    """
    application = get_application_for_user(db, user_id=user_id, application_id=application_id)
    if application is None:
        raise ApplicationNotFound
    order = matched_card_ids(db, user_id=user_id, application_id=application.id)
    cards = load_cards_now(db, user_id=user_id, card_ids=set(order))
    order = [card_id for card_id in order if card_id in cards]  # 저장 카드만
    names = _requirement_names_by_card(db, user_id=user_id, application_id=application.id)
    before_merge = _questions_by_card(db, user_id=user_id, card_ids=order)
    grouped = _merge_same_questions(before_merge, order)
    views = [
        CardInterviewView(
            card_id=card_id,
            card_title=cards[card_id].title,
            note_title=cards[card_id].note_title,
            requirement_names=names.get(card_id, []),
            has_questions=bool(before_merge.get(card_id)),
            questions=[_view(row, cards) for row in grouped.get(card_id, [])],
        )
        for card_id in order
    ]
    questions = [question for view in views for question in view.questions]
    return ApplicationInterviewView(
        application_id=application.id,
        analysis_done=application.matched_at is not None,
        question_count=len(questions),
        answered_count=sum(1 for question in questions if question.answered_at is not None),
        cards=views,
    )
