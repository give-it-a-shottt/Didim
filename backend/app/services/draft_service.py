"""근거 달린 자소서 초안 — 쓰기(AI 1번) · 읽기(다시 검사) · 고치기 · 완료 (F-008, 설계 원칙 1 · 2 · 3 · 4 · 5 · 6).

[초안 쓰기] — 문항당 AI 1번(사용자 확인 2026-11-13). 다시 쓰면 확인창 뒤 덮어쓴다(overwrite). AI가 실패하면 이전 초안을 그대로 둔다.
1. prepare_draft (DB): 내 공고 · 문항인지, 이미 초안이 있는데 덮어쓰기가 아닌지, 이 공고에 매칭된 내 저장 카드가 있는지
   (0장이면 막음 — D-003 예외 7), 하루 상한, 공고 선점(F-007과 같은 application_claims — 분석과 초안 쓰기가 동시에 돌지 않음).
2. request_draft (AI): 매칭 카드의 칸 글만 보낸다(원칙 6, draft_writing).
3. check_ai_sentences: 문장마다 '보낸 카드 안인지' · '인용이 그 칸에 글자 그대로 있는지'. 못 넘으면 근거 없이 남긴다.
4. save_draft (DB): 이전 초안을 지우고 새 초안 · 문장 · 평가 로그 저장, 사용량, 선점 해제.

읽기 · 고치기는 AI를 부르지 않는다. 근거 상태는 읽을 때마다 지금 카드 칸과 비교해 계산한다(draft_evidence — 다시 검사).
- update_draft: 문장 단위로 고친 목록을 통째로 저장(고침 · 지우기 · 사이에 새 문장 · [카드 연결] · 근거 떼기). version이 다르면 409.
- set_draft_completed: [이 문항 완료]. 문장을 고치면 다시 '작성 중'(completed_at을 비움).
모든 조회에 user_id 조건(D-004).
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import (
    CARD_SLOTS,
    CARD_STATUS_SAVED,
    DRAFT_MAX_CARDS_SENT,
    DRAFT_MAX_SENTENCES,
    DRAFT_SENTENCE_MAX_CHARS,
)
from app.db.models import (
    ApplicationQuestion,
    Card,
    Draft,
    DraftLog,
    DraftSentence,
    PostingRequirement,
    RequirementMatch,
)
from app.korea_time import now_utc
from app.llm.base import LLMError, LLMUsage, Message
from app.llm.structured import StructuredReply
from app.services import note_claim
from app.services.application_service import ApplicationNotFound, get_application_for_user
from app.services.draft_evidence import (
    EVIDENCE_BY_AI,
    EVIDENCE_BY_USER,
    ORIGIN_AI,
    ORIGIN_EDITED,
    ORIGIN_USER,
    QUOTE_SOURCES,
    CardNow,
    find_in_card,
    load_cards_now,
)
from app.services.draft_view import (
    DraftNotFound,
    DraftView,
    build_draft_view,
    get_draft,
    load_draft_with_question,
    matched_card_ids,
    sentences_of_drafts,
)
from app.services.draft_writing import (
    OUTCOME_NO_SENTENCES,
    CheckedSentence,
    DraftReplyIn,
    DraftRequest,
    build_draft_messages,
    check_ai_sentences,
)
from app.services.note_claim import ClaimLost, ClaimRules
from app.services.posting_checks import DROP_CARD_GONE
from app.services.posting_matching import CardText, load_saved_cards
from app.services.text_clean import has_forbidden_control
from app.services.usage_service import (
    FEATURE_DRAFT_WRITE,
    OUTCOME_OK,
    OUTCOME_SAVE_FAILED,
    DailyUsage,
    ensure_within_daily_limit,
    outcome_for,
    record_usage,
)

logger = logging.getLogger(__name__)


class QuestionNotFound(Exception):
    """내 공고의 문항이 아니거나 없는 문항(AI를 부르는 동안 지워진 경우 포함)."""


class DraftAlreadyExists(Exception):
    """이 문항에 초안이 있는데 덮어쓰기(overwrite)가 아니다 — 화면이 확인창을 띄운 뒤 다시 보낸다. AI를 부르지 않는다."""


class NoMatchedCards(Exception):
    """이 공고에 매칭된 내 저장 카드가 없다 — 근거 없이 쓰면 AI 창작이 되므로 막는다(D-003 예외 7). AI를 부르지 않는다."""

    def __init__(self, *, analysis_done: bool) -> None:
        super().__init__()
        self.analysis_done = analysis_done  # False면 아직 공고 분석(매칭)을 안 함


class DraftWriteInProgress(Exception):
    """같은 공고에서 다른 요청이 초안을 쓰거나 공고를 분석하는 중이다(선점 표를 같이 씀). AI를 부르지 않는다."""


class DraftConflict(Exception):
    """화면이 보낸 version이 지금 초안과 다르다(다른 탭이 먼저 저장했거나 다시 쓰기로 바뀜) — 저장하지 않는다."""


class InvalidDraftInput(Exception):
    """고친 문장 목록이 틀림(빈 문장 · 너무 김 · 없는 문장 번호 · 쓸 수 없는 카드). 화면에 그대로 보여 줄 문구."""


_CLAIM_RULES = ClaimRules(
    table=note_claim.APPLICATION_CLAIMS,
    in_progress=DraftWriteInProgress,
    already_done=None,
    label="자소서 초안",
)


# --- 매칭 카드 ---


def _requirement_names(db: Session, *, user_id: int, application_id: int, card_ids: list[int]) -> list[str]:
    """보내는 카드와 이어진 역량 이름(공고에 나온 순서, 중복 없이)."""
    if not card_ids:
        return []
    rows = db.execute(
        select(PostingRequirement.name)
        .join(
            RequirementMatch,
            and_(RequirementMatch.requirement_id == PostingRequirement.id, RequirementMatch.user_id == user_id),
        )
        .where(
            PostingRequirement.user_id == user_id,
            PostingRequirement.application_id == application_id,
            RequirementMatch.card_id.in_(card_ids),
        )
        .order_by(PostingRequirement.position)
    ).all()
    return list(dict.fromkeys(name for (name,) in rows))


def _get_question(db: Session, *, user_id: int, application_id: int, question_id: int) -> ApplicationQuestion:
    question = db.scalar(
        select(ApplicationQuestion).where(
            ApplicationQuestion.id == question_id,
            ApplicationQuestion.user_id == user_id,
            ApplicationQuestion.application_id == application_id,
        )
    )
    if question is None:
        raise QuestionNotFound
    return question


def _draft_for_question(db: Session, *, user_id: int, question_id: int) -> Draft | None:
    return db.scalar(select(Draft).where(Draft.user_id == user_id, Draft.question_id == question_id))


# --- [초안 쓰기] ---


@dataclass(frozen=True)
class DraftPlan:
    user_id: int
    application_id: int
    question_id: int
    char_limit: int | None
    usage_before: DailyUsage
    messages: list[Message]
    claimed_at: datetime
    cards: dict[int, CardText] = field(default_factory=dict)  # 보낸 카드(검사 기준)


def prepare_draft(
    db: Session, *, user_id: int, application_id: int, question_id: int, overwrite: bool, now: datetime | None = None
) -> DraftPlan:
    """ApplicationNotFound / QuestionNotFound / DraftAlreadyExists / NoMatchedCards / DailyLimitExceeded /
    DraftWriteInProgress / OtherAIWorkInProgress. 끝나면 save_draft · save_failed · abandon 중 하나가 불려야 선점이 풀린다."""
    application = get_application_for_user(db, user_id=user_id, application_id=application_id)
    if application is None:
        raise ApplicationNotFound
    question = _get_question(db, user_id=user_id, application_id=application.id, question_id=question_id)
    if not overwrite and _draft_for_question(db, user_id=user_id, question_id=question.id) is not None:
        raise DraftAlreadyExists
    order = matched_card_ids(db, user_id=user_id, application_id=application.id)[:DRAFT_MAX_CARDS_SENT]
    saved = {card.id: card for card in load_saved_cards(db, user_id=user_id, card_ids=order)}
    sent = [saved[card_id] for card_id in order if card_id in saved]
    if not sent:
        raise NoMatchedCards(analysis_done=application.matched_at is not None)
    usage_before = ensure_within_daily_limit(db, user_id=user_id, now=now)
    request = DraftRequest(
        company=application.company,
        role=application.role,
        question=question.text,
        char_limit=question.char_limit,
        requirement_names=_requirement_names(
            db, user_id=user_id, application_id=application.id, card_ids=[card.id for card in sent]
        ),
    )
    claimed_at = note_claim.claim_target(
        db, _CLAIM_RULES, user_id=user_id, target_id=application.id, at=now if now is not None else now_utc()
    )
    return DraftPlan(
        user_id=user_id,
        application_id=application.id,
        question_id=question.id,
        char_limit=question.char_limit,
        usage_before=usage_before,
        messages=build_draft_messages(request, sent),
        claimed_at=claimed_at,
        cards={card.id: card for card in sent},
    )


def _log(
    plan: DraftPlan, *, sentences: int, supported: int, drop_reasons: dict[str, int], chars: int, outcome: str, at: datetime
) -> DraftLog:
    return DraftLog(
        user_id=plan.user_id,
        application_id=plan.application_id,
        question_id=plan.question_id,
        cards_sent=len(plan.cards),
        sentences=sentences,
        supported=supported,
        drop_reasons=drop_reasons,
        chars=chars,
        char_limit=plan.char_limit,
        outcome=outcome,
        created_at=at,
    )


def release_claim(db: Session, plan: DraftPlan) -> None:
    note_claim.release_claim(
        db, _CLAIM_RULES, user_id=plan.user_id, target_id=plan.application_id, claimed_at=plan.claimed_at
    )


def save_failed(db: Session, plan: DraftPlan, error: LLMError, *, now: datetime | None = None) -> int:
    """AI 호출이 실패했을 때: 평가 로그 · 사용량을 남기고 선점을 푼다. 이전 초안은 그대로다. 오늘 남은 호출 수를 돌려준다."""
    at = now if now is not None else now_utc()
    outcome = outcome_for(error)
    db.add(_log(plan, sentences=0, supported=0, drop_reasons={}, chars=0, outcome=outcome, at=at))
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 로그 저장이 실패해도 원래 AI 오류를 알리는 게 우선
        db.rollback()
        logger.warning("자소서 초안 로그 저장 실패 user_id=%s error=%s", plan.user_id, type(exc).__name__)
    release_claim(db, plan)
    record_usage(db, user_id=plan.user_id, feature=FEATURE_DRAFT_WRITE, usage=error.usage, outcome=outcome, now=at)
    return max(plan.usage_before.remaining - error.usage.calls, 0)


def abandon(db: Session, plan: DraftPlan, *, now: datetime | None = None) -> None:
    """AI 호출이 LLMError가 아닌 이유(예상 못 한 오류 · 요청 취소)로 끝났을 때. 사용량은 1회로 센다(D-018)."""
    try:
        save_failed(db, plan, LLMError("예상 못 한 오류", usage=LLMUsage(calls=1)), now=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("자소서 초안 정리 실패 user_id=%s error=%s", plan.user_id, type(exc).__name__)
        release_claim(db, plan)


@dataclass(frozen=True)
class DraftWriteOutcome:
    question_id: int
    written: bool  # False면 AI가 쓸 만한 문장을 주지 않아 초안을 바꾸지 않음
    sentences: int
    supported: int
    cards_sent: int
    drop_reasons: dict[str, int]
    remaining_today: int


def _drop_gone_cards(db: Session, plan: DraftPlan, checked: list[CheckedSentence], reasons: Counter[str]) -> list[CheckedSentence]:
    """AI를 부르는 동안 지워진 카드 · 저장을 취소한 카드의 근거는 떼고 문장만 남긴다(외래키가 없는 카드를 가리키지 않게)."""
    card_ids = {item.card_id for item in checked if item.card_id is not None}
    if not card_ids:
        return checked
    alive = set(
        db.scalars(
            select(Card.id).where(Card.user_id == plan.user_id, Card.id.in_(card_ids), Card.status == CARD_STATUS_SAVED)
        ).all()
    )
    result: list[CheckedSentence] = []
    for item in checked:
        if item.card_id is not None and item.card_id not in alive:
            reasons[DROP_CARD_GONE] += 1
            result.append(CheckedSentence(text=item.text))
        else:
            result.append(item)
    return result


def _replace_draft(db: Session, plan: DraftPlan, sentences: list[CheckedSentence], *, text: str, at: datetime) -> None:
    """이 문항의 이전 초안을 지우고 새 초안 · 문장을 넣는다(커밋은 부르는 쪽). 문항이 지워졌으면 QuestionNotFound."""
    _get_question(db, user_id=plan.user_id, application_id=plan.application_id, question_id=plan.question_id)
    old = _draft_for_question(db, user_id=plan.user_id, question_id=plan.question_id)
    version = 1
    if old is not None:
        version = old.version + 1  # 열려 있던 다른 탭의 저장이 409가 되게
        db.execute(delete(Draft).where(Draft.id == old.id, Draft.user_id == plan.user_id))
    draft = Draft(
        user_id=plan.user_id,
        application_id=plan.application_id,
        question_id=plan.question_id,
        ai_text=text,
        version=version,
        completed_at=None,
        created_at=at,
        updated_at=at,
    )
    db.add(draft)
    db.flush()
    db.add_all(
        DraftSentence(
            user_id=plan.user_id,
            draft_id=draft.id,
            position=position,
            text=item.text,
            origin=ORIGIN_AI,
            original_text=item.text,
            card_id=item.card_id,
            slot=item.slot,
            quote=item.quote,
            quote_source=item.quote_source,
            quote_start=item.quote_start,
            quote_end=item.quote_end,
            evidence_origin=EVIDENCE_BY_AI if item.supported else None,
        )
        for position, item in enumerate(sentences)
    )


def save_draft(
    db: Session, plan: DraftPlan, reply: StructuredReply[DraftReplyIn], *, now: datetime | None = None
) -> DraftWriteOutcome:
    """이전 초안을 지우고 새 초안 · 문장 · 평가 로그를 한 번에 저장한다. 문장이 0개면 이전 초안을 그대로 둔다.

    저장이 실패해도 AI는 이미 불렀으므로 사용량은 기록한 뒤 오류를 올린다. AI를 부르는 동안 공고가 지워졌으면
    ApplicationNotFound, 문항이 지워졌으면 QuestionNotFound(둘 다 404).
    """
    at = now if now is not None else now_utc()
    try:
        checked = check_ai_sentences(reply.value.sentences, plan.cards)
        sentences = _drop_gone_cards(db, plan, checked.sentences, checked.drop_reasons)
        supported = sum(1 for item in sentences if item.supported)
        drop_reasons = dict(checked.drop_reasons)
        text = " ".join(item.text for item in sentences)
        if sentences:
            _replace_draft(db, plan, sentences, text=text, at=at)
        outcome = OUTCOME_OK if sentences else OUTCOME_NO_SENTENCES
        db.add(
            _log(
                plan,
                sentences=len(sentences),
                supported=supported,
                drop_reasons=drop_reasons,
                chars=len(text),
                outcome=outcome,
                at=at,
            )
        )
        released = db.execute(
            note_claim.release_statement(
                _CLAIM_RULES, user_id=plan.user_id, target_id=plan.application_id, claimed_at=plan.claimed_at
            )
        ).rowcount
        if released != 1:
            raise ClaimLost
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(
            "자소서 초안 저장 실패 user_id=%s application_id=%s question_id=%s error=%s",
            plan.user_id,
            plan.application_id,
            plan.question_id,
            type(exc).__name__,
        )
        record_usage(db, user_id=plan.user_id, feature=FEATURE_DRAFT_WRITE, usage=reply.usage, outcome=OUTCOME_SAVE_FAILED, now=at)
        release_claim(db, plan)
        # 공고가 지워졌으면(문항 · 선점도 CASCADE로 사라짐) '문항 없음'보다 '공고 없음'으로 알린다
        gone = get_application_for_user(db, user_id=plan.user_id, application_id=plan.application_id) is None
        if isinstance(exc, (ClaimLost, QuestionNotFound)) and gone:
            raise ApplicationNotFound from exc
        raise
    record_usage(db, user_id=plan.user_id, feature=FEATURE_DRAFT_WRITE, usage=reply.usage, outcome=OUTCOME_OK, now=at)
    logger.info(
        "자소서 초안 user_id=%s application_id=%s question_id=%s cards=%d sentences=%d supported=%d dropped=%s",
        plan.user_id,
        plan.application_id,
        plan.question_id,
        len(plan.cards),
        len(sentences),
        supported,
        drop_reasons,
    )
    return DraftWriteOutcome(
        question_id=plan.question_id,
        written=bool(sentences),
        sentences=len(sentences),
        supported=supported,
        cards_sent=len(plan.cards),
        drop_reasons=drop_reasons,
        remaining_today=max(plan.usage_before.remaining - reply.usage.calls, 0),
    )


# --- 고치기 · 완료 ---


@dataclass(frozen=True)
class EvidenceLink:
    """[카드 연결]: 내 저장 카드의 칸 하나에서 원문 인용(quote) 또는 내 답(answer)을 통째로 근거로 붙인다(사용자 확인 2026-11-14)."""

    card_id: int
    slot: str
    quote_source: str


@dataclass(frozen=True)
class SentenceEdit:
    """고친 목록의 문장 하나. id가 있으면 기존 문장(근거 유지), 없으면 새 문장(근거 없음)."""

    id: int | None
    text: str
    link: EvidenceLink | None = None  # 붙일 근거([카드 연결])
    unlink: bool = False  # 근거 떼기


def _clean_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    if has_forbidden_control(cleaned):
        raise InvalidDraftInput("쓸 수 없는 글자(제어 문자)가 들어 있어요.")
    if not cleaned:
        raise InvalidDraftInput("빈 문장은 저장할 수 없어요. 지우려면 [지우기]를 눌러 주세요.")
    if len(cleaned) > DRAFT_SENTENCE_MAX_CHARS:
        raise InvalidDraftInput(f"문장 하나는 {DRAFT_SENTENCE_MAX_CHARS}자까지 쓸 수 있어요.")
    return cleaned


def _linked_evidence(link: EvidenceLink, cards: dict[int, CardNow]) -> tuple[int, str, str, str, int]:
    """(카드 번호, 칸, 인용, 인용 출처, 위치). 내 저장 카드의 그 칸에 글이 있어야 한다 — 검사는 다시 검사와 같은 find_in_card."""
    slot = link.slot.strip().lower()
    if slot not in CARD_SLOTS or link.quote_source not in QUOTE_SOURCES:
        raise InvalidDraftInput("근거로 고른 칸이 틀렸어요.")
    card = cards.get(link.card_id)
    if card is None:
        raise InvalidDraftInput("근거로 고른 카드를 찾을 수 없어요. 저장한 내 카드만 연결할 수 있어요.")
    text = card.text(slot, link.quote_source)
    start = find_in_card(card, slot=slot, source=link.quote_source, quote=text) if text and text.strip() else None
    if text is None or start is None:
        raise InvalidDraftInput("고른 칸에 글이 없어요. 다른 칸을 골라 주세요.")
    return card.id, slot, text, link.quote_source, start


def _origin_after_edit(old: DraftSentence, text: str) -> str:
    """고친 뒤의 출처: 내가 넣은 문장은 계속 user, AI 문장은 원래 글과 다르면 edited · 같아지면 ai."""
    if old.origin == ORIGIN_USER:
        return ORIGIN_USER
    return ORIGIN_AI if text == old.original_text else ORIGIN_EDITED


def _row_for_edit(
    item: SentenceEdit,
    *,
    position: int,
    existing: dict[int, DraftSentence],
    link_cards: dict[int, CardNow],
    user_id: int,
    draft_id: int,
) -> DraftSentence:
    """고친 목록의 한 줄 → 새로 넣을 문장. 기존 문장은 근거를 옮겨 오고, 근거 떼기 · [카드 연결]을 적용한다."""
    text = _clean_sentence(item.text)
    old = existing.get(item.id) if item.id is not None else None
    if old is None:
        row = DraftSentence(user_id=user_id, draft_id=draft_id, origin=ORIGIN_USER, original_text=None)
    else:
        row = DraftSentence(
            user_id=user_id,
            draft_id=draft_id,
            origin=_origin_after_edit(old, text),
            original_text=old.original_text,
            card_id=old.card_id,
            slot=old.slot,
            quote=old.quote,
            quote_source=old.quote_source,
            quote_start=old.quote_start,
            quote_end=old.quote_end,
            evidence_origin=old.evidence_origin,
        )
    row.position = position
    row.text = text
    if item.unlink:
        row.card_id = row.slot = row.quote = row.quote_source = row.evidence_origin = None
        row.quote_start = row.quote_end = None
    if item.link is not None:
        card_id, slot, quote, source, start = _linked_evidence(item.link, link_cards)
        row.card_id, row.slot, row.quote, row.quote_source = card_id, slot, quote, source
        row.quote_start, row.quote_end = start, start + len(quote)
        row.evidence_origin = EVIDENCE_BY_USER
    return row


def update_draft(
    db: Session, *, user_id: int, draft_id: int, version: int, sentences: list[SentenceEdit], now: datetime | None = None
) -> DraftView:
    """고친 문장 목록을 통째로 저장한다(순서 = 목록 순서, 목록에 없는 문장은 지움).

    - 기존 문장: 근거를 그대로 두고, 글이 AI 원래 문장과 다르면 origin=edited('내가 고침'), 같아지면 ai로 돌아간다.
    - 새 문장: origin=user, 근거 없음. [카드 연결](link)로 근거를 붙일 수 있다(evidence_origin=user).
    - 고치면 완료 표시를 지운다(다시 '작성 중'). version이 다르면 DraftConflict(저장 안 함).
    DraftNotFound / DraftConflict / InvalidDraftInput.
    """
    at = now if now is not None else now_utc()
    draft, question = load_draft_with_question(db, user_id=user_id, draft_id=draft_id)
    if draft.version != version:
        raise DraftConflict
    if not sentences:
        raise InvalidDraftInput("문장이 하나는 있어야 해요. 다시 쓰려면 [다시 쓰기]를 눌러 주세요.")
    if len(sentences) > DRAFT_MAX_SENTENCES:
        raise InvalidDraftInput(f"문장은 {DRAFT_MAX_SENTENCES}개까지 저장할 수 있어요.")
    existing = {row.id: row for row in sentences_of_drafts(db, user_id=user_id, draft_ids=[draft.id]).get(draft.id, [])}
    given_ids = [item.id for item in sentences if item.id is not None]
    if len(given_ids) != len(set(given_ids)) or any(sentence_id not in existing for sentence_id in given_ids):
        raise InvalidDraftInput("고친 문장 목록이 지금 초안과 맞지 않아요. 새로고침한 뒤 다시 시도해 주세요.")
    link_cards = load_cards_now(db, user_id=user_id, card_ids={item.link.card_id for item in sentences if item.link})

    rows = [
        _row_for_edit(item, position=position, existing=existing, link_cards=link_cards, user_id=user_id, draft_id=draft.id)
        for position, item in enumerate(sentences)
    ]

    # version을 '화면이 읽은 값일 때만' 올린다(1차 리뷰 R2 · R3). 위의 비교만으로는 두 탭이 동시에 보내면 둘 다 통과한다.
    # PostgreSQL은 이 UPDATE가 줄을 잠가 두 번째 요청이 기다렸다가 바뀐 version을 보고 0줄 → 409가 된다.
    bumped = db.execute(
        update(Draft)
        .where(Draft.id == draft.id, Draft.user_id == user_id, Draft.version == version)
        .values(version=version + 1, completed_at=None, updated_at=at)
    ).rowcount
    if bumped != 1:
        db.rollback()
        raise DraftConflict
    # 순서 유니크(draft_id, position)와 부딪히지 않게 지우고 새로 넣는다. 문장 번호는 바뀐다(응답으로 다시 받음).
    db.execute(delete(DraftSentence).where(DraftSentence.draft_id == draft.id, DraftSentence.user_id == user_id))
    db.add_all(rows)
    try:
        db.commit()
    except IntegrityError as exc:  # 그 사이 [다시 쓰기]로 초안이 지워짐(외래키) 등 — 저장하지 않고 '먼저 바뀜'으로 알린다
        db.rollback()
        raise DraftConflict from exc
    db.refresh(draft)
    cards = load_cards_now(db, user_id=user_id, card_ids={row.card_id for row in rows if row.card_id is not None})
    return build_draft_view(draft, rows, cards, question.char_limit)


def set_draft_completed(
    db: Session, *, user_id: int, draft_id: int, completed: bool, now: datetime | None = None
) -> DraftView:
    """[이 문항 완료] · 완료 풀기. 내용이 바뀌지 않으므로 version은 그대로 둔다. DraftNotFound.

    조건부 UPDATE로 한다 — 읽고 고치는 ORM 방식은 그 사이 [다시 쓰기]가 초안을 지우면 커밋에서 StaleDataError(500)가
    난다(F-008 3차 리뷰 R2). 0줄이면 '없는 초안'(404) → 화면이 새로 받는다.
    """
    at = now if now is not None else now_utc()
    changed = db.execute(
        update(Draft)
        .where(Draft.id == draft_id, Draft.user_id == user_id)
        .values(completed_at=at if completed else None)
    ).rowcount
    if changed != 1:
        db.rollback()
        raise DraftNotFound
    db.commit()
    return get_draft(db, user_id=user_id, draft_id=draft_id)
