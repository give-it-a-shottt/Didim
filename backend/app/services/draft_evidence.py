"""자소서 문장의 근거 검사 (F-008 완료 기준 2, D-003 · D-004).

검사는 함수 하나다 — '인용이 내 저장 카드의 그 칸(원문 인용 또는 내 답)에 글자 그대로 있는가'(F-007 매칭과 같은
posting_matching.find_in_field). 세 곳이 모두 이 함수를 부른다(사용자 확인 2026-11-14, F-008 2차 리뷰 R1).
- AI 초안을 저장할 때(draft_writing.check_ai_sentences): 보낸 카드 안인지 + find_in_field.
- [카드 연결]로 내가 붙일 때(draft_service._linked_evidence): 칸 글 전체를 인용으로 → find_in_card.
- 다시 검사(evidence_status → find_in_card): 초안을 읽을 때마다 저장된 인용을 지금 카드 칸과 다시 비교한다. AI는 부르지 않는다
  (사용자 확인 2026-11-14). 카드가 지워졌거나 칸 글이 바뀌어 인용이 없어졌으면 '근거 없음'이 된다.

근거 상태는 저장하지 않는다 — 카드가 바뀔 때마다 저장된 상태를 고쳐야 하는 일을 없애려고(읽을 때 계산).
"""

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.config import CARD_STATUS_SAVED
from app.db.models import Card, CardField, Draft, DraftSentence, Note
from app.services.posting_checks import QUOTE_SOURCE_ANSWER, QUOTE_SOURCE_QUOTE
from app.services.posting_matching import find_in_field

# 근거 상태(화면 · API 값)
EVIDENCE_OK = "ok"  # 인용이 지금 카드 칸에 글자 그대로 있음
EVIDENCE_NONE = "none"  # 처음부터 근거가 없음(AI가 근거를 못 붙임 · 내가 새로 넣은 문장 · 근거를 뗌)
EVIDENCE_CARD_GONE = "card_gone"  # 근거 카드가 지워졌거나 저장 카드가 아님
EVIDENCE_CHANGED = "changed"  # 카드 칸 글이 바뀌어 인용이 더는 없음

# 근거를 누가 붙였는지(draft_sentences.evidence_origin)
EVIDENCE_BY_AI = "ai"
EVIDENCE_BY_USER = "user"  # [카드 연결]

# 문장 출처(draft_sentences.origin)
ORIGIN_AI = "ai"
ORIGIN_EDITED = "edited"  # AI 문장을 내가 고침 — 근거 칩은 그대로, '내가 고침'
ORIGIN_USER = "user"  # 내가 새로 넣은 문장

QUOTE_SOURCES = (QUOTE_SOURCE_QUOTE, QUOTE_SOURCE_ANSWER)


@dataclass(frozen=True)
class CardNow:
    """지금 내 저장 카드(다시 검사 · [카드 연결] · 화면 근거 칸에 씀)."""

    id: int
    title: str
    note_title: str | None  # 카드가 나온 노트(지워졌으면 None)
    fields: dict[str, tuple[str | None, str | None]]  # slot → (원문 인용, 내 답)

    def text(self, slot: str, source: str) -> str | None:
        quote, answer = self.fields.get(slot, (None, None))
        return quote if source == QUOTE_SOURCE_QUOTE else answer


def load_cards_now(db: Session, *, user_id: int, card_ids: set[int]) -> dict[int, CardNow]:
    """내 저장 카드 중 card_ids만(사용자 조건, D-004). 없거나 남의 카드 · 후보 카드는 결과에 없다."""
    if not card_ids:
        return {}
    rows = db.execute(
        select(Card.id, Card.title, Note.title, CardField.slot, CardField.quote, CardField.answer)
        .join(CardField, and_(CardField.card_id == Card.id, CardField.user_id == user_id))
        .outerjoin(Note, and_(Note.id == Card.note_id, Note.user_id == user_id))
        .where(Card.user_id == user_id, Card.status == CARD_STATUS_SAVED, Card.id.in_(card_ids))
    ).all()
    cards: dict[int, CardNow] = {}
    for card_id, title, note_title, slot, quote, answer in rows:
        card = cards.setdefault(card_id, CardNow(id=card_id, title=title, note_title=note_title, fields={}))
        card.fields[slot] = (quote, answer)
    return cards


def find_in_card(card: CardNow, *, slot: str, source: str, quote: str) -> int | None:
    """그 카드 칸의 그 출처 글(원문 인용 또는 내 답)에서 인용의 시작 위치. 없으면 None. 기준은 find_in_field 하나."""
    text = card.text(slot, source)
    found = find_in_field(quote, (text, None) if source == QUOTE_SOURCE_QUOTE else (None, text))
    return found[1] if found is not None else None


def evidence_status(sentence: DraftSentence, cards: dict[int, CardNow]) -> str:
    """저장된 근거를 지금 카드 칸과 다시 비교한다(다시 검사 — AI 없음)."""
    if sentence.quote is None or sentence.slot is None or sentence.quote_source is None:
        return EVIDENCE_NONE
    card = cards.get(sentence.card_id) if sentence.card_id is not None else None
    if card is None:
        return EVIDENCE_CARD_GONE
    if find_in_card(card, slot=sentence.slot, source=sentence.quote_source, quote=sentence.quote) is None:
        return EVIDENCE_CHANGED
    return EVIDENCE_OK


def unsupported_counts(db: Session, *, user_id: int, application_id: int) -> dict[int, int]:
    """문항(question_id)별 근거 없는 문장 수. 초안이 없는 문항은 결과에 없다."""
    rows = db.execute(
        select(Draft.question_id, DraftSentence)
        .join(DraftSentence, and_(DraftSentence.draft_id == Draft.id, DraftSentence.user_id == user_id))
        .where(Draft.user_id == user_id, Draft.application_id == application_id)
    ).all()
    cards = load_cards_now(db, user_id=user_id, card_ids={s.card_id for _, s in rows if s.card_id is not None})
    counts: dict[int, int] = {}
    for question_id, sentence in rows:
        if evidence_status(sentence, cards) != EVIDENCE_OK:
            counts[question_id] = counts.get(question_id, 0) + 1
    return counts
