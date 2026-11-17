"""자소서 문장의 근거 검사 (F-008 완료 기준 2, D-003 · D-004).

검사는 함수 하나다 — '인용이 내 저장 카드의 그 칸(원문 인용 또는 내 답)에 글자 그대로 있는가'(F-007 매칭과 같은
posting_matching.find_in_field). 세 곳이 모두 이 함수를 부른다(사용자 확인 2026-11-14, F-008 2차 리뷰 R1).
- AI 초안을 저장할 때(draft_writing.check_ai_sentences): 보낸 카드 안인지 + find_in_field.
- [카드 연결]로 내가 붙일 때(draft_service._linked_evidence): 칸 글 전체를 인용으로 → find_in_card.
- 다시 검사(evidence_status → find_in_card): 초안을 읽을 때마다 저장된 인용을 지금 카드 칸과 다시 비교한다. AI는 부르지 않는다
  (사용자 확인 2026-11-14). 카드가 지워졌거나 칸 글이 바뀌어 인용이 없어졌으면 '근거 없음'이 된다.

근거 상태는 저장하지 않는다 — 카드가 바뀔 때마다 저장된 상태를 고쳐야 하는 일을 없애려고(읽을 때 계산).

'확인 필요'(D-028)도 같은 방식이다: 근거가 ok인 문장에 claim_check 규칙을 돌려 읽을 때 계산한다(AI 근거 · [카드 연결]
근거 모두). 카드에 결과 칸을 나중에 채우면 저절로 풀린다. 저장하는 것은 [확인함]을 누를 때 걸려 있던 이유(confirmed_claims)
뿐이고, 지금 이유가 그것과 같을 때만 '확인함'으로 본다 — 카드가 바뀌어 이유가 달라지면 다시 경고(Q-029).
'확인 필요'인지는 SentenceClaims.needs_check 한 곳에서만 정한다(화면 · 제출 확인창 · 평가가 같이 씀, 7차 리뷰 R1).
"""

from dataclasses import dataclass
from functools import cached_property

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.config import CARD_STATUS_SAVED
from app.db.models import Card, CardField, Draft, DraftSentence, Note
from app.services.claim_check import CardFacts, ClaimCheck, check_claims
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
RESULT_SLOT = "result"  # '확인 필요' R3가 보는 결과 칸


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

    @cached_property
    def claim_facts(self) -> CardFacts:
        """'확인 필요' 규칙이 보는 카드 글 — 한 번 읽는 동안 카드마다 한 번만 만든다(7차 리뷰 R2)."""
        texts = [self.title, *(text for pair in self.fields.values() for text in pair)]
        result_recorded = any(text and text.strip() for text in self.fields.get(RESULT_SLOT, (None, None)))
        return CardFacts.of(texts, result_recorded=result_recorded)


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


@dataclass(frozen=True)
class SentenceClaims:
    """규칙에 걸린 문장 하나(D-028). confirmed = [확인함] 때 저장한 이유가 지금 이유와 같다."""

    check: ClaimCheck
    confirmed: bool

    @property
    def needs_check(self) -> bool:
        """화면의 '확인 필요' — 규칙에 걸렸고, 지금 이유를 [확인함]으로 끄지 않았다. 이 판단은 여기 한 곳뿐이다."""
        return not self.confirmed


def sentence_claims(sentence: DraftSentence, cards: dict[int, CardNow], status: str) -> SentenceClaims | None:
    """근거가 ok인 문장의 '확인 필요' 검사. 근거가 ok가 아니거나(이미 '근거 없음') 규칙에 안 걸리면 None."""
    if status != EVIDENCE_OK or sentence.card_id is None:
        return None
    check = check_claims(sentence.text, cards[sentence.card_id].claim_facts)
    if not check.flagged:
        return None
    return SentenceClaims(check=check, confirmed=sentence.confirmed_claims == check.key)


@dataclass(frozen=True)
class WarningCounts:
    """공고 하나의 자소서 초안 전체에서 경고가 붙은 문장 수('제출'로 바꿀 때 확인창)."""

    unsupported: int  # 근거 상태가 ok가 아님('근거 없음')
    needs_check: int  # 근거는 ok인데 '확인 필요'(D-028)


def warning_counts(db: Session, *, user_id: int, application_id: int) -> WarningCounts:
    rows = db.scalars(
        select(DraftSentence)
        .join(Draft, and_(Draft.id == DraftSentence.draft_id, Draft.user_id == user_id))
        .where(DraftSentence.user_id == user_id, Draft.application_id == application_id)
    ).all()
    cards = load_cards_now(db, user_id=user_id, card_ids={row.card_id for row in rows if row.card_id is not None})
    unsupported = flagged = 0
    for sentence in rows:
        status = evidence_status(sentence, cards)
        claims = sentence_claims(sentence, cards, status)
        if status != EVIDENCE_OK:
            unsupported += 1
        elif claims is not None and claims.needs_check:
            flagged += 1
    return WarningCounts(unsupported=unsupported, needs_check=flagged)
