"""자소서 초안 읽기 — 문항별 초안 · 문장 · 근거(지금 카드와 다시 비교한 상태) · 내가 고친 비율 (F-008).

draft_service.py(쓰기 흐름 · 고치기 · 완료)에서 나눴다(F-008 2차 리뷰 R1). AI를 부르지 않는다.
근거 상태는 저장하지 않고 읽을 때마다 draft_evidence.evidence_status로 계산한다. 모든 조회에 user_id 조건(D-004).
"""

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import EDITED_PERCENT_EXACT_LIMIT
from app.db.models import ApplicationQuestion, Card, Draft, DraftSentence, PostingRequirement, RequirementMatch
from app.korea_time import now_utc
from app.services.application_service import ApplicationNotFound, get_application_for_user
from app.services.draft_evidence import EVIDENCE_BY_AI, EVIDENCE_OK, CardNow, evidence_status, load_cards_now


class DraftNotFound(Exception):
    """내 초안이 아니거나 없는 초안."""


def matched_card_ids(db: Session, *, user_id: int, application_id: int) -> list[int]:
    """이 공고의 역량에 매칭된 내 카드 번호 — 매칭된 역량이 많은 카드 먼저(같으면 번호 순)."""
    rows = db.execute(
        select(RequirementMatch.card_id, func.count())
        .join(
            PostingRequirement,
            and_(PostingRequirement.id == RequirementMatch.requirement_id, PostingRequirement.user_id == user_id),
        )
        .join(Card, and_(Card.id == RequirementMatch.card_id, Card.user_id == user_id))
        .where(RequirementMatch.user_id == user_id, PostingRequirement.application_id == application_id)
        .group_by(RequirementMatch.card_id)
        .order_by(func.count().desc(), RequirementMatch.card_id)
    ).all()
    return [card_id for card_id, _ in rows]


@dataclass(frozen=True)
class EvidenceView:
    card_id: int | None  # 카드가 지워졌으면 None
    card_title: str | None  # 지금 카드 제목(지워졌으면 None)
    note_title: str | None  # 카드가 나온 노트 제목(없으면 None)
    slot: str
    quote: str
    quote_source: str  # quote(카드의 원문 인용) · answer(카드의 내 답)
    added_by: str  # ai · user([카드 연결])


@dataclass(frozen=True)
class SentenceView:
    id: int
    position: int
    text: str
    origin: str  # ai · edited · user
    original_text: str | None
    evidence_status: str  # ok · none · card_gone · changed
    evidence: EvidenceView | None


@dataclass(frozen=True)
class DraftView:
    id: int
    question_id: int
    version: int
    completed_at: datetime | None
    updated_at: datetime
    chars: int  # 지금 글자 수(문장 사이 띄어쓰기 포함)
    char_limit: int | None
    edited_percent: int  # AI 원문에서 내가 고친 비율(낱말 기준, 0~100)
    sentence_count: int
    unsupported_count: int  # 근거 상태가 ok가 아닌 문장 수
    sentences: list[SentenceView]


def edited_percent(ai_text: str, current_text: str) -> int:
    """AI 원문과 지금 글을 낱말 단위로 비교해 바뀐 비율(%)을 낸다. 글자 단위는 긴 글에서 느려서 낱말로 본다.

    아주 긴 글(낱말 수의 곱이 EDITED_PERCENT_EXACT_LIMIT 초과)은 순서를 보지 않는 빠른 근사(quick_ratio)로 낸다 —
    정확히 재면 최대 크기에서 1초 넘게 걸려 읽을 때마다 작업 스레드를 붙잡는다(F-008 1차 리뷰 R2, 실측).
    근사는 '같은 낱말이 얼마나 남았나'만 봐서 고친 비율을 조금 낮게 낼 수 있다.
    """
    before, after = ai_text.split(), current_text.split()
    if not before and not after:
        return 0
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    ratio = matcher.ratio() if len(before) * len(after) <= EDITED_PERCENT_EXACT_LIMIT else matcher.quick_ratio()
    return round((1 - ratio) * 100)


def _sentence_view(sentence: DraftSentence, cards: dict[int, CardNow]) -> SentenceView:
    status = evidence_status(sentence, cards)
    evidence = None
    if sentence.quote is not None and sentence.slot is not None and sentence.quote_source is not None:
        card = cards.get(sentence.card_id) if sentence.card_id is not None else None
        evidence = EvidenceView(
            card_id=sentence.card_id,
            card_title=card.title if card is not None else None,
            note_title=card.note_title if card is not None else None,
            slot=sentence.slot,
            quote=sentence.quote,
            quote_source=sentence.quote_source,
            added_by=sentence.evidence_origin or EVIDENCE_BY_AI,
        )
    return SentenceView(
        id=sentence.id,
        position=sentence.position,
        text=sentence.text,
        origin=sentence.origin,
        original_text=sentence.original_text,
        evidence_status=status,
        evidence=evidence,
    )


def build_draft_view(draft: Draft, sentences: list[DraftSentence], cards: dict[int, CardNow], char_limit: int | None) -> DraftView:
    views = [_sentence_view(item, cards) for item in sorted(sentences, key=lambda row: row.position)]
    text = " ".join(item.text for item in views)
    return DraftView(
        id=draft.id,
        question_id=draft.question_id,
        version=draft.version,
        completed_at=draft.completed_at,
        updated_at=draft.updated_at,
        chars=len(text),
        char_limit=char_limit,
        edited_percent=edited_percent(draft.ai_text, text),
        sentence_count=len(views),
        unsupported_count=sum(1 for item in views if item.evidence_status != EVIDENCE_OK),
        sentences=views,
    )


def sentences_of_drafts(db: Session, *, user_id: int, draft_ids: list[int]) -> dict[int, list[DraftSentence]]:
    if not draft_ids:
        return {}
    rows = db.scalars(
        select(DraftSentence)
        .where(DraftSentence.user_id == user_id, DraftSentence.draft_id.in_(draft_ids))
        .order_by(DraftSentence.draft_id, DraftSentence.position)
    ).all()
    result: dict[int, list[DraftSentence]] = {}
    for row in rows:
        result.setdefault(row.draft_id, []).append(row)
    return result


@dataclass(frozen=True)
class QuestionDraftView:
    id: int
    position: int
    text: str
    char_limit: int | None
    draft: DraftView | None


@dataclass(frozen=True)
class ApplicationDraftsView:
    application_id: int
    analysis_done: bool  # 공고 분석 ② 매칭을 한 번이라도 끝냈는가(아니면 화면이 공고 분석으로 안내)
    matched_card_ids: list[int]  # 이 공고에 매칭된 내 저장 카드(초안 쓰기에 보낼 수 있는 카드, 많이 매칭된 순)
    checked_at: datetime  # 근거를 다시 검사한 시각(= 이 응답을 만든 시각)
    questions: list[QuestionDraftView]


def get_application_drafts(
    db: Session, *, user_id: int, application_id: int, now: datetime | None = None
) -> ApplicationDraftsView:
    """문항마다 초안 · 문장 · 근거(지금 카드와 다시 비교한 상태). ApplicationNotFound."""
    application = get_application_for_user(db, user_id=user_id, application_id=application_id)
    if application is None:
        raise ApplicationNotFound
    questions = db.scalars(
        select(ApplicationQuestion)
        .where(ApplicationQuestion.user_id == user_id, ApplicationQuestion.application_id == application.id)
        .order_by(ApplicationQuestion.position)
    ).all()
    drafts = {
        draft.question_id: draft
        for draft in db.scalars(
            select(Draft).where(Draft.user_id == user_id, Draft.application_id == application.id)
        ).all()
    }
    sentences = sentences_of_drafts(db, user_id=user_id, draft_ids=[draft.id for draft in drafts.values()])
    matched = matched_card_ids(db, user_id=user_id, application_id=application.id)
    referenced = {row.card_id for rows in sentences.values() for row in rows if row.card_id is not None}
    cards = load_cards_now(db, user_id=user_id, card_ids=referenced | set(matched))
    return ApplicationDraftsView(
        application_id=application.id,
        analysis_done=application.matched_at is not None,
        matched_card_ids=[card_id for card_id in matched if card_id in cards],
        checked_at=now if now is not None else now_utc(),
        questions=[
            QuestionDraftView(
                id=question.id,
                position=question.position,
                text=question.text,
                char_limit=question.char_limit,
                draft=(
                    build_draft_view(drafts[question.id], sentences.get(drafts[question.id].id, []), cards, question.char_limit)
                    if question.id in drafts
                    else None
                ),
            )
            for question in questions
        ],
    )


def load_draft_with_question(db: Session, *, user_id: int, draft_id: int) -> tuple[Draft, ApplicationQuestion]:
    row = db.execute(
        select(Draft, ApplicationQuestion)
        .join(
            ApplicationQuestion,
            and_(ApplicationQuestion.id == Draft.question_id, ApplicationQuestion.user_id == user_id),
        )
        .where(Draft.id == draft_id, Draft.user_id == user_id)
    ).first()
    if row is None:
        raise DraftNotFound
    return row[0], row[1]


def get_draft(db: Session, *, user_id: int, draft_id: int) -> DraftView:
    draft, question = load_draft_with_question(db, user_id=user_id, draft_id=draft_id)
    rows = sentences_of_drafts(db, user_id=user_id, draft_ids=[draft.id]).get(draft.id, [])
    cards = load_cards_now(db, user_id=user_id, card_ids={row.card_id for row in rows if row.card_id is not None})
    return build_draft_view(draft, rows, cards, question.char_limit)
