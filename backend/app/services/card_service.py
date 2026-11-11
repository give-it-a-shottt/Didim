"""경험 카드 목록 · 상세 · 저장 · 버리기 · 내 답 (F-006 완료 기준 2 · 3 · 4 · 5 · 6).

카드에 저장하는 글은 원문 인용(후보 찾기가 검사한 것) · 사용자 답 · 근거 링크뿐이다(D-003).
- 인용은 고칠 수 없고 [인용 빼기]로 지울 수만 있다(사용자 확인 2026-11-11 — 인용은 고정 + 내 답 덧붙이기).
- 빈칸 = 인용도 답도 없는 칸. 근거 수 = 인용이 있는 칸 수. 빈칸 0개 = 완성.
- 답은 앞뒤 공백을 걷고, 비면 None으로 둔다 — 빈칸 판정을 DB에서 'answer IS NULL' 하나로 하려고.
모든 조회에 user_id 조건을 건다(D-004). 남의 카드는 '없음'과 똑같이 답한다.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.config import (
    CARD_DEFAULT_QUESTIONS,
    CARD_MAX_ANSWER_CHARS,
    CARD_SLOTS,
    CARD_STATUS_SAVED,
    CARD_TITLE_MAX_CHARS,
    MAX_CARD_LIST,
)
from app.db.models import Card, CardField, Note, NoteCardClaim
from app.korea_time import now_utc
from app.services.text_clean import has_forbidden_control


class CardNotFound(Exception):
    """내 카드가 아니거나 없는 카드."""


CONTROL_CHAR_MESSAGE = "쓸 수 없는 글자(제어 문자)가 들어 있어요."


class InvalidCardInput(Exception):
    """제목 · 답이 비었거나 너무 김. 화면에 그대로 보여 줄 문구를 담는다."""


# --- 목록 ---


@dataclass(frozen=True)
class CardSummary:
    id: int
    title: str
    status: str
    note_id: int | None
    note_title: str | None  # 노트가 지워졌으면 None('원문 없음')
    blank_count: int
    evidence_count: int
    updated_at: datetime
    blank_slots: list[str]  # 빈칸인 칸 이름(CARD_SLOTS 순서) — 목록에서 어느 칸이 비었는지 표시


@dataclass(frozen=True)
class CardList:
    total: int
    cards: list[CardSummary]
    note_searched: bool | None  # note_id로 걸렀을 때만: 이 노트에서 후보 찾기를 끝냈는가(후보를 다 버렸어도 True)


# '빈칸'의 정의는 여기 한 곳(_is_blank)이 기준이다: 인용도 내 답도 없는 칸. 빈칸 수 · 빈칸 이름(SQL)과
# CardDetail.blank_count(파이썬), 화면의 isBlank(frontend/src/lib/cards.ts)가 모두 같은 정의를 따른다.
def _is_blank():  # noqa: ANN202
    return and_(CardField.quote.is_(None), CardField.answer.is_(None))


def _blank_count():  # noqa: ANN202
    return func.sum(case((_is_blank(), 1), else_=0))


def _evidence_count():  # noqa: ANN202
    return func.sum(case((CardField.quote.is_not(None), 1), else_=0))


def _blank_slots(db: Session, *, user_id: int, card_ids: list[int]) -> dict[int, list[str]]:
    """카드별 빈칸 칸 이름. 목록에 실린 카드(최대 MAX_CARD_LIST개)만 한 번에 읽는다."""
    if not card_ids:
        return {}
    rows = db.execute(
        select(CardField.card_id, CardField.slot).where(
            CardField.user_id == user_id,
            CardField.card_id.in_(card_ids),
            _is_blank(),
        )
    ).all()
    found: dict[int, set[str]] = {}
    for card_id, slot in rows:
        found.setdefault(card_id, set()).add(slot)
    return {card_id: [slot for slot in CARD_SLOTS if slot in slots] for card_id, slots in found.items()}


def list_cards(db: Session, *, user_id: int, status: str, note_id: int | None = None) -> CardList:
    """상태(candidate · saved)별 카드, 최근 고친 것부터 최대 MAX_CARD_LIST개. 빈칸 수 · 근거 수는 DB에서 센다."""
    conditions = [Card.user_id == user_id, Card.status == status]
    if note_id is not None:
        conditions.append(Card.note_id == note_id)
    total = db.scalar(select(func.count()).select_from(Card).where(*conditions)) or 0
    # 칸과 INNER JOIN — 카드는 만들 때 항상 네 칸이 같이 생기므로(card_generation._card_rows) 빠지는 카드가 없다.
    rows = db.execute(
        select(
            Card.id,
            Card.title,
            Card.status,
            Card.note_id,
            Note.title.label("note_title"),
            _blank_count().label("blank_count"),
            _evidence_count().label("evidence_count"),
            Card.updated_at,
        )
        .join(CardField, and_(CardField.card_id == Card.id, CardField.user_id == user_id))
        .outerjoin(Note, and_(Note.id == Card.note_id, Note.user_id == user_id))
        .where(*conditions)
        .group_by(Card.id, Card.title, Card.status, Card.note_id, Note.title, Card.updated_at)
        .order_by(Card.updated_at.desc(), Card.id.desc())
        .limit(MAX_CARD_LIST)
    ).all()
    blank_by_card = _blank_slots(db, user_id=user_id, card_ids=[row.id for row in rows])
    note_searched = None
    if note_id is not None:
        note_searched = bool(
            db.scalar(
                select(func.count())
                .select_from(NoteCardClaim)
                .where(
                    NoteCardClaim.user_id == user_id,
                    NoteCardClaim.note_id == note_id,
                    NoteCardClaim.finished_at.is_not(None),
                )
            )
        )
    return CardList(
        total=total,
        cards=[
            CardSummary(
                id=row.id,
                title=row.title,
                status=row.status,
                note_id=row.note_id,
                note_title=row.note_title,
                blank_count=int(row.blank_count or 0),
                evidence_count=int(row.evidence_count or 0),
                updated_at=row.updated_at,
                blank_slots=blank_by_card.get(row.id, []),
            )
            for row in rows
        ],
        note_searched=note_searched,
    )


# --- 상세 ---


@dataclass(frozen=True)
class FieldDetail:
    slot: str
    quote: str | None
    quote_start: int | None  # 노트 원문 기준 글자 위치 — 근거 칩 → 노트 상세 강조
    quote_end: int | None
    chunk_id: int | None
    question: str | None  # 빈칸 질문(AI) — 카드 내용이 아니라 안내
    answer: str | None


@dataclass(frozen=True)
class CardDetail:
    id: int
    title: str
    status: str
    note_id: int | None
    note_title: str | None
    created_at: datetime
    updated_at: datetime
    fields: list[FieldDetail]

    @property
    def blank_count(self) -> int:  # 빈칸 정의는 _is_blank와 같다
        return sum(1 for item in self.fields if item.quote is None and item.answer is None)

    @property
    def evidence_count(self) -> int:
        return sum(1 for item in self.fields if item.quote is not None)


def _get_card(db: Session, *, user_id: int, card_id: int) -> Card:
    card = db.scalar(select(Card).where(Card.id == card_id, Card.user_id == user_id))
    if card is None:
        raise CardNotFound
    return card


def _fields_by_slot(db: Session, *, user_id: int, card_id: int) -> dict[str, CardField]:
    rows = db.scalars(select(CardField).where(CardField.card_id == card_id, CardField.user_id == user_id)).all()
    return {row.slot: row for row in rows}


def get_card(db: Session, *, user_id: int, card_id: int) -> CardDetail:
    card = _get_card(db, user_id=user_id, card_id=card_id)
    note_title = None
    if card.note_id is not None:
        note_title = db.scalar(select(Note.title).where(Note.id == card.note_id, Note.user_id == user_id))
    by_slot = _fields_by_slot(db, user_id=user_id, card_id=card.id)
    fields = [
        FieldDetail(
            slot=slot,
            quote=row.quote,
            quote_start=row.quote_start,
            quote_end=row.quote_end,
            chunk_id=row.chunk_id,
            question=row.question,
            answer=row.answer,
        )
        for slot in CARD_SLOTS
        if (row := by_slot.get(slot)) is not None
    ]
    return CardDetail(
        id=card.id,
        title=card.title,
        status=card.status,
        note_id=card.note_id,
        note_title=note_title,
        created_at=card.created_at,
        updated_at=card.updated_at,
        fields=fields,
    )


# --- 저장 · 버리기 · 내 답 ---


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if has_forbidden_control(cleaned):
        raise InvalidCardInput(CONTROL_CHAR_MESSAGE)
    if not cleaned:
        raise InvalidCardInput("카드 제목을 적어 주세요.")
    if len(cleaned) > CARD_TITLE_MAX_CHARS:
        raise InvalidCardInput(f"카드 제목은 {CARD_TITLE_MAX_CHARS}자까지 쓸 수 있어요.")
    return cleaned


def save_card(db: Session, *, user_id: int, card_id: int, title: str, now: datetime | None = None) -> CardDetail:
    """후보 → 저장. 제목은 사용자가 확인한 값으로 바꾼다(AI 제안 그대로여도 사용자가 [저장]을 누른 것).

    이미 저장한 카드에 다시 보내면 제목만 바꾼다(두 번 눌러도 같은 결과).
    """
    cleaned = _clean_title(title)
    card = _get_card(db, user_id=user_id, card_id=card_id)
    card.title = cleaned
    card.status = CARD_STATUS_SAVED
    card.updated_at = now if now is not None else now_utc()
    db.commit()
    return get_card(db, user_id=user_id, card_id=card_id)


def delete_card(db: Session, *, user_id: int, card_id: int) -> None:
    """후보 버리기 · 카드 삭제. 칸은 DB 외래키(ON DELETE CASCADE)로 같이 지워진다.

    노트의 '이미 찾음' 표시(note_card_claims.finished_at)는 그대로 둔다 — 버린 뒤 AI를 다시 부르지 않게(사용자 확인).
    """
    card = _get_card(db, user_id=user_id, card_id=card_id)
    db.delete(card)
    db.commit()


def update_field(
    db: Session,
    *,
    user_id: int,
    card_id: int,
    slot: str,
    answer: str | None,
    remove_quote: bool = False,
    now: datetime | None = None,
) -> CardDetail:
    """칸의 내 답을 바꾸고, remove_quote면 인용을 뺀다(빈칸이 되면 기본 질문을 붙임). 인용 글 자체는 고칠 수 없다."""
    if slot not in CARD_SLOTS:  # 라우터가 먼저 거르지만, 서비스만 불러도 같은 결과(422)가 되게
        raise InvalidCardInput("칸 이름이 틀렸어요.")
    cleaned = (answer or "").strip() or None
    if cleaned is not None and has_forbidden_control(cleaned):
        raise InvalidCardInput(CONTROL_CHAR_MESSAGE)
    if cleaned is not None and len(cleaned) > CARD_MAX_ANSWER_CHARS:
        raise InvalidCardInput(f"한 칸에는 {CARD_MAX_ANSWER_CHARS}자까지 쓸 수 있어요.")
    card = _get_card(db, user_id=user_id, card_id=card_id)
    row = _fields_by_slot(db, user_id=user_id, card_id=card.id).get(slot)
    if row is None:
        raise CardNotFound
    at = now if now is not None else now_utc()
    row.answer = cleaned
    if remove_quote and row.quote is not None:
        row.quote = None
        row.quote_start = None
        row.quote_end = None
        row.chunk_id = None
        row.question = row.question or CARD_DEFAULT_QUESTIONS[slot]
    row.updated_at = at
    card.updated_at = at
    db.commit()
    return get_card(db, user_id=user_id, card_id=card_id)
