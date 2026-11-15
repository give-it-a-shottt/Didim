"""자소서 초안 평가 (F-008 완료 기준 4, D-005 — 가상 공고 · 가상 카드 · 정해 둔 문항).

두 가지를 잰다(사용자 선택 2026-11-15 — D-005 심은 문장 평가 + AI 초안 평가).
- 심은 문장 평가(핵심, D-005): AI 없이 진짜 문장 7 + 일부러 지어낸 문장 3을 실제 저장 · 검사 흐름에 넣고 종류별로 잡은 수를 센다.
  판정이 들어가지 않는다. 아래 '심은 문장 평가' 구역.
- AI 초안 평가(참고): 실제 AI가 쓴 초안에서 아래를 잰다.

AI 초안 평가에서 재는 것
- 지어낸 문장을 검사가 잡은 비율: '지어냄'으로 판정한 문장 중 근거 검사를 못 넘어 '근거 없음'으로 경고된 비율.
- 근거 없이 남은 문장 수: 저장된 AI 문장 중 근거가 없는 문장(화면에서 '근거 없음' 경고가 붙는 문장).
- (진단) 검사를 통과했는데 지어낸 문장(놓친 것) · 지어내지 않았는데 근거 없음(경고만 늘림) · 문항 종류별 수 ·
  근거를 못 붙인 이유(draft_logs.drop_reasons와 같은 키) · 글자 수 제한을 넘은 초안.

'지어냄' 판정은 채점 AI 없이 한다(사용자 선택 2026-11-15 — 규칙 + 사람 확인).
- 규칙: 문장의 숫자 · 영문 낱말이 AI에 보낸 카드 글에 없으면 의심. 보낸 내용 어디에도 없으면 invented(지어냄),
  문항 · 역량 이름에만 있으면 from_question(문항 말을 옮긴 것일 수 있어 사람이 판정).
- 사람: 결과 파일의 문장마다 human(true = 지어냄, false = 아님)을 적으면 규칙보다 앞선다. 비어 있으면 규칙을 따르고,
  규칙이 지어냄으로 못 가른 문장은 '사람 확인 전'으로 센다(summary.labels_pending).

매칭은 F-007 정답지 카드로 고정한다(사용자 선택 2026-11-15 — 매칭 품질과 섞지 않게, AI는 초안 쓰기만).
초안 쓰기는 실제 서비스와 같은 함수(prepare_draft → request_draft → save_draft)를 쓴다. 평가용 임시 DB에서만 돈다.
"""

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import (
    APPLICATION_COMPANY_MAX_CHARS,
    DRAFT_MIN_QUOTE_CHARS,
    REQUIREMENT_NAME_MAX_CHARS,
)
from app.db.models import (
    Application,
    ApplicationQuestion,
    CardField,
    Draft,
    DraftSentence,
    PostingRequirement,
    RequirementMatch,
)
from app.korea_time import now_utc
from app.llm import MockLLMClient
from app.llm.base import LLMClient, LLMUsage, Message
from app.services.application_service import QuestionInput, create_application
from app.services.draft_service import (
    DraftPlan,
    DraftWriteOutcome,
    abandon,
    prepare_draft,
    save_draft,
    save_failed,
)
from app.services.draft_writing import OUTCOME_NO_SENTENCES, request_draft
from app.services.eval_retry import RetryPolicy, run_ai_step
from app.services.posting_evaluation import PostingKey, key_spans
from app.services.text_clean import visible_chars

KIND_ANSWERABLE = "answerable"  # 매칭 카드로 답할 수 있는 문항
KIND_TRAP = "trap"  # 카드에 없는 경험을 묻는 문항(AI가 지어내기 쉬운 상황)
QUESTION_KINDS = (KIND_ANSWERABLE, KIND_TRAP)

RULE_INVENTED = "invented"  # 보낸 내용 어디에도 없는 숫자 · 영문 낱말 → 지어냄
RULE_FROM_QUESTION = "from_question"  # 카드에는 없고 문항 · 역량 이름에만 있음 → 사람이 판정

FIXED_MATCH_REASON = "(평가: 정답지 매칭)"

# --- 문항 정답지 ---


@dataclass(frozen=True)
class QuestionKey:
    kind: str  # answerable · trap
    text: str
    char_limit: int | None


def parse_question_key(raw: Mapping[str, object], posting_keys: Mapping[str, PostingKey]) -> dict[str, tuple[QuestionKey, ...]]:
    """문항 파일을 읽는다. 공고 정답지와 공고 이름이 다르거나 모양이 틀리면 AI를 부르기 전에 멈춘다."""
    questions = raw.get("questions")
    if not isinstance(questions, Mapping) or not questions:
        raise ValueError("문항 파일에 questions가 없어요.")
    if set(questions) != set(posting_keys):
        raise ValueError(f"문항 파일과 공고 정답지의 공고가 달라요 — {sorted(set(questions) ^ set(posting_keys))}")
    keys: dict[str, tuple[QuestionKey, ...]] = {}
    for name, items in questions.items():
        if not isinstance(items, list) or not items:
            raise ValueError(f"{name}: 문항이 없어요.")
        keys[str(name)] = tuple(_parse_question_item(str(name), item) for item in items)
    return keys


def _parse_question_item(name: str, item: object) -> QuestionKey:
    """문항 하나. 틀린 곳을 나눠 알린다(정답지 오타를 AI 부르기 전에 고치게)."""
    if not isinstance(item, Mapping):
        raise ValueError(f"{name}: 문항은 객체여야 해요 — {item}")  # noqa: TRY004 — 정답지 오류는 모두 ValueError(스크립트가 한 번에 잡음)
    if item.get("kind") not in QUESTION_KINDS:
        raise ValueError(f"{name}: kind는 {' · '.join(QUESTION_KINDS)} 중 하나여야 해요 — {item.get('kind')}")
    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{name}: 문항 글(text)이 비었어요.")
    limit = item.get("char_limit")
    if not (limit is None or (isinstance(limit, int) and not isinstance(limit, bool) and limit > 0)):
        raise ValueError(f"{name}: char_limit은 1 이상의 정수이거나 null이어야 해요 — {limit}")
    return QuestionKey(kind=item["kind"], text=text.strip(), char_limit=limit)


# --- 평가 공고 준비: 공고 · 문항 저장, 매칭 고정 (AI 없이) ---


def seed_fixed_matches(
    db: Session,
    *,
    user_id: int,
    application_id: int,
    posting_text: str,
    key: PostingKey,
    experience_card: Mapping[str, int],
) -> None:
    """정답지 역량 줄을 요구 역량으로, 정답 카드를 매칭으로 넣고 '매칭 끝'으로 표시한다(F-007 ① · ②를 AI 없이 대신).

    매칭 인용은 그 카드의 첫 원문 인용 칸 전체(초안 쓰기는 매칭 인용을 쓰지 않고 카드 번호만 쓴다).
    """
    spans = key_spans(posting_text, key)
    answer_cards = {card for requirement in key.requirements for card in requirement.cards}
    card_ids = {experience_card[card] for card in answer_cards}
    first_fields: dict[int, CardField] = {}
    for field_row in db.scalars(
        select(CardField)
        .where(CardField.user_id == user_id, CardField.card_id.in_(card_ids), CardField.quote.is_not(None))
        .order_by(CardField.card_id, CardField.id)
    ):
        first_fields.setdefault(field_row.card_id, field_row)
    missing = sorted(card for card in answer_cards if experience_card[card] not in first_fields)
    if missing:  # 매칭 인용으로 쓸 원문 인용 칸이 없는 정답 카드 — 공고 하나만 실패로 남기도록 부르는 쪽이 잡는다
        raise ValueError(f"정답 카드에 원문 인용 칸이 없어요: {missing}")
    for position, (requirement, (start, end)) in enumerate(zip(key.requirements, spans, strict=True)):
        row = PostingRequirement(
            user_id=user_id,
            application_id=application_id,
            position=position,
            name=requirement.quote[:REQUIREMENT_NAME_MAX_CHARS],
            kind=requirement.kind,
            quote=requirement.quote,
            quote_start=start,
            quote_end=end,
        )
        db.add(row)
        db.flush()
        for card in requirement.cards:
            card_field = first_fields[experience_card[card]]
            quote = card_field.quote or ""
            db.add(
                RequirementMatch(
                    user_id=user_id,
                    requirement_id=row.id,
                    card_id=card_field.card_id,
                    slot=card_field.slot,
                    quote=quote,
                    quote_source="quote",
                    quote_start=0,
                    quote_end=len(quote),
                    reason=FIXED_MATCH_REASON,
                )
            )
    application = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user_id))
    if application is None:
        raise ValueError("평가 공고가 없어요.")
    at = now_utc()
    application.extracted_at = application.matched_at = at
    db.commit()


def create_eval_application(
    db: Session, *, user_id: int, file_name: str, posting_text: str, questions: Sequence[QuestionKey]
) -> tuple[int, list[int]]:
    """평가 공고 · 문항을 서비스 함수로 저장한다. (공고 번호, 문항 번호 목록 — 입력 순서)."""
    first_line = next((line.strip() for line in posting_text.splitlines() if line.strip()), file_name)
    application_id = create_application(
        db,
        user_id=user_id,
        company=first_line[:APPLICATION_COMPANY_MAX_CHARS],
        role="평가",
        deadline=None,
        url=None,
        posting_text=posting_text,
        questions=[QuestionInput(text=item.text, char_limit=item.char_limit) for item in questions],
    )
    question_ids = db.scalars(
        select(ApplicationQuestion.id)
        .where(ApplicationQuestion.user_id == user_id, ApplicationQuestion.application_id == application_id)
        .order_by(ApplicationQuestion.position)
    ).all()
    return application_id, list(question_ids)


# --- 규칙 판정 (채점 AI 없이) ---

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#]+")  # 두 글자 이상(C# · N+1 포함)


def numbers_in(text: str) -> set[str]:
    return {match.replace(",", "") for match in _NUMBER.findall(text)}


def words_in(text: str) -> set[str]:
    return {match.casefold() for match in _LATIN.findall(text)}


@dataclass(frozen=True)
class SentText:
    """AI에 보낸 글 한 덩어리 — 숫자는 낱개로, 영문은 글 전체(대소문자 무시)로 비교한다."""

    numbers: frozenset[str]
    text: str

    @classmethod
    def of(cls, parts: Sequence[str]) -> "SentText":
        joined = "\n".join(parts)
        return cls(numbers=frozenset(numbers_in(joined)), text=joined.casefold())

    def has(self, token: str, *, number: bool) -> bool:
        # 숫자는 정확히 같아야 한다('3'이 '30' 안에 있다고 통과시키지 않음). 영문은 글 안에 있으면 통과 —
        # 줄여 쓴 낱말(remark-gf)을 지어냄으로 세지 않게. 자동 '지어냄'은 확실한 것만 잡고 나머지는 사람이 본다.
        return token in self.numbers if number else token in self.text


def sent_payload(messages: Sequence[Message]) -> dict[str, Any]:
    """AI에 보낸 user 메시지의 JSON(draft_writing.build_draft_messages가 만든 것)."""
    return json.loads(next(message.content for message in messages if message.role == "user"))


@dataclass(frozen=True)
class SentPayload:
    """AI에 실제로 보낸 내용을 카드 글과 그 밖(회사 · 직무 · 문항 · 역량 이름)으로 나눈 것."""

    cards: SentText
    context: SentText

    @classmethod
    def from_messages(cls, messages: Sequence[Message]) -> "SentPayload":
        payload = sent_payload(messages)
        card_parts: list[str] = []
        for card in payload.get("cards", []):
            card_parts.append(str(card.get("title", "")))
            for item in card.get("fields", []):
                card_parts.extend(str(item.get(part, "")) for part in ("quote", "answer"))
        context_parts = [str(payload.get(part, "")) for part in ("company", "role", "question")]
        context_parts.extend(str(name) for name in payload.get("requirements", []))
        return cls(cards=SentText.of(card_parts), context=SentText.of(context_parts))


def rule_verdict(text: str, payload: SentPayload) -> tuple[str | None, list[str]]:
    """(규칙 판정, 카드 글에 없는 숫자 · 영문 낱말). 판정은 invented · from_question · None(규칙으로는 못 가름)."""
    tokens = [(token, True) for token in numbers_in(text)] + [(token, False) for token in words_in(text)]
    unknown = [(token, number) for token, number in tokens if not payload.cards.has(token, number=number)]
    invented = sorted(token for token, number in unknown if not payload.context.has(token, number=number))
    if invented:
        return RULE_INVENTED, invented
    if unknown:
        return RULE_FROM_QUESTION, sorted(token for token, _ in unknown)
    return None, []


# --- 문항 하나 평가 (실제 서비스 흐름) ---


@dataclass
class SentenceRecord:
    id: str  # 결과 파일 안에서 문장을 가리키는 이름(p01-q1-s3) — 사람 판정을 적을 때 씀
    text: str
    supported: bool  # 근거 검사를 넘어 근거가 붙었는지(False = 화면의 '근거 없음')
    card: str | None = None  # 근거 카드의 경험 id
    slot: str | None = None
    quote: str | None = None
    rule: str | None = None
    rule_tokens: list[str] = field(default_factory=list)
    human: bool | None = None  # 사람 판정(true = 지어냄). 있으면 규칙보다 앞선다
    planted: str | None = None  # 심은 문장 평가에서 일부러 지어 넣은 문장의 종류(PLANT_*). 진짜 문장은 None

    @property
    def fabricated(self) -> bool:
        return self.human if self.human is not None else self.rule == RULE_INVENTED

    @property
    def needs_human(self) -> bool:
        return self.human is None and self.rule != RULE_INVENTED


@dataclass
class QuestionEvalResult:
    file_name: str
    index: int  # 공고 안 문항 순서(1부터)
    kind: str
    question: str
    char_limit: int | None
    sentences: list[SentenceRecord] = field(default_factory=list)
    chars: int = 0
    cards_sent: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    error: str | None = None  # AI 오류 종류 · no_sentences(남은 문장 0개) — 이 문항은 문장 없이 센다
    error_detail: str | None = None  # 예상 못 한 오류의 메시지(앞부분만) — 원인을 결과 파일에서 볼 수 있게
    seconds: float | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    retries: int = 0

    @property
    def over_limit(self) -> bool:
        return self.char_limit is not None and self.chars > self.char_limit


def sentence_id(file_name: str, index: int, position: int) -> str:
    return f"{file_name.split('-', 1)[0]}-q{index}-s{position + 1}"


def _load_sentences(db: Session, *, user_id: int, question_id: int) -> tuple[str, list[DraftSentence]]:
    draft = db.scalar(select(Draft).where(Draft.user_id == user_id, Draft.question_id == question_id))
    if draft is None:
        return "", []
    rows = db.scalars(
        select(DraftSentence)
        .where(DraftSentence.user_id == user_id, DraftSentence.draft_id == draft.id)
        .order_by(DraftSentence.position)
    ).all()
    return draft.ai_text, list(rows)


async def evaluate_question(
    db: Session,
    *,
    user_id: int,
    application_id: int,
    question_id: int,
    file_name: str,
    index: int,
    key: QuestionKey,
    card_experience: Mapping[int, str],
    client: LLMClient,
    policy: RetryPolicy | None = None,
) -> QuestionEvalResult:
    """문항 하나: [초안 쓰기]를 실제 서비스 함수로 돌리고 저장된 문장마다 근거 여부 · 규칙 판정을 남긴다.

    AI 서버 오류(500 · 429)면 서비스처럼 save_failed로 정리한 뒤 policy대로 쉬고 처음부터 다시 한다(eval_retry).
    예상 못 한 오류 · 중단은 abandon으로 선점을 풀고 올린다.
    """
    result = QuestionEvalResult(file_name=file_name, index=index, kind=key.kind, question=key.text, char_limit=key.char_limit)
    outcome = await run_ai_step(
        prepare=lambda: prepare_draft(
            db, user_id=user_id, application_id=application_id, question_id=question_id, overwrite=True
        ),
        request=lambda plan: request_draft(client, plan.messages),
        save_failed=lambda plan, exc: save_failed(db, plan, exc),
        abandon=lambda plan: abandon(db, plan),
        policy=policy or RetryPolicy(),
        usage_of=lambda reply: reply.usage,
    )
    result.seconds, result.usage, result.retries = outcome.seconds, outcome.usage, outcome.retries
    if outcome.error is not None or outcome.reply is None:
        result.error = type(outcome.error).__name__
        return result
    _record_saved(db, result, outcome.plan, save_draft(db, outcome.plan, outcome.reply), card_experience)
    return result


def _record_saved(
    db: Session,
    result: QuestionEvalResult,
    plan: DraftPlan,
    outcome: DraftWriteOutcome,
    card_experience: Mapping[int, str],
) -> None:
    """save_draft가 저장한 문장을 읽어 문장마다 근거 여부 · 규칙 판정을 result에 남긴다(두 평가가 같이 씀)."""
    result.cards_sent = outcome.cards_sent
    result.drop_reasons = outcome.drop_reasons
    if not outcome.written:
        result.error = OUTCOME_NO_SENTENCES
        return
    payload = SentPayload.from_messages(plan.messages)
    text, rows = _load_sentences(db, user_id=plan.user_id, question_id=plan.question_id)
    result.chars = len(text)
    for row in rows:
        rule, tokens = rule_verdict(row.text, payload)
        result.sentences.append(
            SentenceRecord(
                id=sentence_id(result.file_name, result.index, row.position),
                text=row.text,
                supported=row.card_id is not None,
                card=card_experience.get(row.card_id, f"card-{row.card_id}") if row.card_id is not None else None,
                slot=row.slot,
                quote=row.quote,
                rule=rule,
                rule_tokens=tokens,
            )
        )


# --- 심은 문장 평가 (D-005 — AI 없이, 판정 없이) ---
# 실제 prepare_draft가 고른 카드로 '진짜 문장'(카드 인용을 그대로 쓴 문장)과 '일부러 지어낸 문장'을 섞은 답을 만들고,
# 실제 request_draft(형식 검사) → save_draft(근거 검사)에 넣는다. 어느 문장을 심었는지는 만들 때 정해지므로
# 매기는 사람의 판단이 들어가지 않는다. 검사기는 인용만 글자 그대로 비교하므로 결과는 '어떤 종류를 잡고 어떤 종류를
# 놓치는지'를 보여 준다 — 종류별로 나눠 본다(전체 비율은 종류를 섞은 비율에 따라 달라짐).

PLANT_NO_EVIDENCE = "no_evidence"  # 근거 없이 지어낸 문장
PLANT_FAKE_QUOTE = "fake_quote"  # 카드 글을 바꿔 쓴 인용(카드에 없는 말을 인용인 척)
PLANT_OTHER_CARD = "other_card"  # 진짜 인용을 다른 카드 번호에 붙임
PLANT_ADDED_FACT = "added_fact"  # 진짜 인용은 그대로 두고 문장에만 없는 사실을 덧붙임(검사기가 보지 않는 곳)
PLANT_TYPES = (PLANT_NO_EVIDENCE, PLANT_FAKE_QUOTE, PLANT_OTHER_CARD, PLANT_ADDED_FACT)
PLANT_GENUINE_PER_DRAFT = 7  # D-005 '문장 10개 중 3개 정도를 지어낸 문장으로'
PLANT_FAKE_PER_DRAFT = 3
PLANT_SNIPPET_CHARS = 120  # 진짜 인용으로 쓰는 카드 글 앞부분 길이(DRAFT_MAX_QUOTE_CHARS 안)
PLANT_UNSENT_CARD_OFFSET = 1000  # 카드가 1장뿐일 때 '다른 카드'로 쓸 번호 — 보낸 카드 번호와 겹치지 않게
PLANT_AFTER_GENUINE = (1, 3, 5)  # 진짜 문장 몇 번째(0부터) 뒤에 심을지 — 앞 · 가운데 · 뒤에 고르게


def _snippets(payload: Mapping[str, Any]) -> list[tuple[int, str, str]]:
    """보낸 카드 칸마다 (카드 번호, 칸, 그 칸 글의 첫 줄 앞부분). 카드 글에 글자 그대로 있는 조각이다."""
    found = []
    for card in payload.get("cards", []):
        for item in card.get("fields", []):
            for part in ("quote", "answer"):
                text = str(item.get(part) or "").split("\n")[0].strip()[:PLANT_SNIPPET_CHARS].strip()
                if visible_chars(text) >= DRAFT_MIN_QUOTE_CHARS:
                    found.append((int(card["card_id"]), str(item["slot"]), text))
                    break
    return found


def _planted_sentence(kind: str, snippet: tuple[int, str, str], card_ids: Sequence[int]) -> dict[str, object]:
    card_id, slot, text = snippet
    if kind == PLANT_NO_EVIDENCE:
        return {"text": "이 경험으로 팀의 배포 시간을 절반으로 줄였습니다.", "card_id": None, "slot": None, "quote": None}
    if kind == PLANT_FAKE_QUOTE:
        return {
            "text": f"{text} 덕분에 팀에서 칭찬을 받았습니다.",
            "card_id": card_id,
            "slot": slot,
            "quote": f"{text} 덕분에 팀에서 칭찬을 받았다.",
        }
    if kind == PLANT_OTHER_CARD:
        other = next((other_id for other_id in card_ids if other_id != card_id), max(card_ids) + PLANT_UNSENT_CARD_OFFSET)
        return {"text": text, "card_id": other, "slot": slot, "quote": text}
    if kind == PLANT_ADDED_FACT:
        return {"text": f"{text} 그 결과 처리 속도가 37% 빨라졌습니다.", "card_id": card_id, "slot": slot, "quote": text}
    raise ValueError(f"모르는 심은 문장 종류: {kind}")


def planted_sentences(payload: Mapping[str, Any], *, rotation: int) -> tuple[list[dict[str, object]], list[str | None]]:
    """(AI 답 문장 목록, 문장마다 심은 종류 — 진짜 문장은 None).

    종류는 rotation부터 PLANT_TYPES를 돌아가며 고른다 — 문항 순서를 넘기면 4문항마다 종류별로 같은 수가 심어진다.
    """
    snippets = _snippets(payload)
    if not snippets:
        raise ValueError("보낸 카드에 인용으로 쓸 글이 없어요.")
    card_ids = [int(card["card_id"]) for card in payload.get("cards", [])]
    kinds = [PLANT_TYPES[(rotation + offset) % len(PLANT_TYPES)] for offset in range(PLANT_FAKE_PER_DRAFT)]
    fakes = [(kind, _planted_sentence(kind, snippets[offset % len(snippets)], card_ids)) for offset, kind in enumerate(kinds)]
    items: list[dict[str, object]] = []
    labels: list[str | None] = []

    def add(item: dict[str, object], label: str | None) -> None:
        items.append(item)
        labels.append(label)

    for position, (card_id, slot, text) in enumerate(snippets[:PLANT_GENUINE_PER_DRAFT]):
        add({"text": text, "card_id": card_id, "slot": slot, "quote": text}, None)
        if position in PLANT_AFTER_GENUINE and fakes:
            kind, item = fakes.pop(0)
            add(item, kind)
    for kind, item in fakes:  # 진짜 문장이 적어 못 끼운 것은 끝에
        add(item, kind)
    return items, labels


async def evaluate_planted_question(
    db: Session,
    *,
    user_id: int,
    application_id: int,
    question_id: int,
    file_name: str,
    index: int,
    key: QuestionKey,
    card_experience: Mapping[int, str],
    rotation: int,
) -> QuestionEvalResult:
    """문항 하나: 실제 prepare_draft → (심은 답) request_draft → save_draft. 문장마다 심은 종류를 붙인다. AI는 부르지 않는다."""
    result = QuestionEvalResult(file_name=file_name, index=index, kind=key.kind, question=key.text, char_limit=key.char_limit)
    plan = prepare_draft(db, user_id=user_id, application_id=application_id, question_id=question_id, overwrite=True)
    try:
        items, labels = planted_sentences(sent_payload(plan.messages), rotation=rotation)
        planted_ai = MockLLMClient([json.dumps({"sentences": items}, ensure_ascii=False)])
        reply = await request_draft(planted_ai, plan.messages)
    except BaseException:
        abandon(db, plan)
        raise
    _record_saved(db, result, plan, save_draft(db, plan, reply), card_experience)
    if len(result.sentences) != len(labels):  # 문장이 빠지면 위치로 정답을 붙일 수 없다
        raise ValueError(f"{file_name} 문항 {index}: 심은 답 {len(labels)}문장 중 {len(result.sentences)}문장만 저장됐어요.")
    for record, label in zip(result.sentences, labels, strict=True):
        record.planted = label
    return result


def summarize_planted(results: Sequence[QuestionEvalResult]) -> dict[str, object]:
    records = [record for result in results for record in result.sentences]
    fakes = [record for record in records if record.planted is not None]
    genuine = [record for record in records if record.planted is None]
    caught = sum(1 for record in fakes if not record.supported)
    drops: Counter[str] = Counter()
    for result in results:
        drops.update(result.drop_reasons)
    by_type: dict[str, dict[str, object]] = {}
    for kind in PLANT_TYPES:
        planted = [record for record in fakes if record.planted == kind]
        kind_caught = sum(1 for record in planted if not record.supported)
        by_type[kind] = {"planted": len(planted), "caught": kind_caught, "catch_rate": _rate(kind_caught, len(planted))}
    return {
        "questions": len(results),
        "sentences": len(records),
        # 핵심 수치
        "planted": len(fakes),
        "planted_caught": caught,
        "catch_rate": _rate(caught, len(fakes)),
        "by_type": by_type,
        # 진단: 진짜 문장(카드 인용을 그대로 쓴 문장)을 '근거 없음'으로 잘못 경고한 수 — 0이어야 한다
        "genuine": len(genuine),
        "genuine_flagged": sum(1 for record in genuine if not record.supported),
        "drop_reasons": dict(drops),
        "failures": sum(1 for result in results if result.error),
    }


# --- 요약 ---


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _counts(records: Sequence[SentenceRecord]) -> dict[str, object]:
    fabricated = [record for record in records if record.fabricated]
    caught = sum(1 for record in fabricated if not record.supported)
    return {
        "sentences": len(records),
        "unsupported": sum(1 for record in records if not record.supported),
        "fabricated": len(fabricated),
        "caught": caught,
        "catch_rate": _rate(caught, len(fabricated)),
    }


def summarize(results: Sequence[QuestionEvalResult]) -> dict[str, object]:
    records = [record for result in results for record in result.sentences]
    written = [result for result in results if result.sentences]
    fabricated = [record for record in records if record.fabricated]
    by_rule = [record for record in records if record.rule == RULE_INVENTED]
    drops: Counter[str] = Counter()
    usage = LLMUsage()
    for result in results:
        drops.update(result.drop_reasons)
        usage = usage + result.usage
    seconds = [result.seconds for result in results if result.seconds is not None]
    unsupported = sum(1 for record in records if not record.supported)
    return {
        "questions": len(results),
        "drafts_written": len(written),
        "sentences": len(records),
        # 핵심 수치
        "unsupported_sentences": unsupported,
        "unsupported_per_draft": round(unsupported / len(written), 2) if written else None,
        "fabricated": len(fabricated),
        "fabricated_caught": sum(1 for record in fabricated if not record.supported),
        "catch_rate": _rate(sum(1 for record in fabricated if not record.supported), len(fabricated)),
        "labels_pending": sum(1 for record in records if record.needs_human),
        # 진단
        "fabricated_missed": sum(1 for record in fabricated if record.supported),  # 검사를 통과한 지어낸 문장
        "unsupported_not_fabricated": sum(1 for record in records if not record.supported and not record.fabricated),
        "rule_only": {
            "fabricated": len(by_rule),
            "caught": sum(1 for record in by_rule if not record.supported),
            "catch_rate": _rate(sum(1 for record in by_rule if not record.supported), len(by_rule)),
            "from_question": sum(1 for record in records if record.rule == RULE_FROM_QUESTION),
        },
        "by_kind": {
            kind: _counts([record for result in results if result.kind == kind for record in result.sentences])
            for kind in QUESTION_KINDS
        },
        "drop_reasons": dict(drops),
        "over_limit": sum(1 for result in results if result.over_limit),
        "failures": sum(1 for result in results if result.error),
        "retries": sum(result.retries for result in results),
        "seconds_avg": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "seconds_max": round(max(seconds), 1) if seconds else None,
        "usage": asdict(usage),
    }


def result_to_dict(result: QuestionEvalResult) -> dict[str, object]:
    return {
        "file": result.file_name,
        "index": result.index,
        "kind": result.kind,
        "question": result.question,
        "char_limit": result.char_limit,
        "chars": result.chars,
        "cards_sent": result.cards_sent,
        "drop_reasons": result.drop_reasons,
        "error": result.error,
        "error_detail": result.error_detail,
        "retries": result.retries,
        "seconds": round(result.seconds, 1) if result.seconds is not None else None,
        "usage": asdict(result.usage),
        "sentences": [asdict(record) for record in result.sentences],
    }


def result_from_dict(raw: Mapping[str, Any]) -> QuestionEvalResult:
    """결과 파일 → 결과(사람 판정을 적은 뒤 다시 채점할 때). human은 true · false · null만 받는다."""
    sentences = []
    for item in raw.get("sentences", []):
        human = item.get("human")
        if human not in (True, False, None):
            raise ValueError(f"{item.get('id')}: human은 true · false · null만 쓸 수 있어요.")
        sentences.append(
            SentenceRecord(
                id=str(item["id"]),
                text=str(item["text"]),
                supported=bool(item["supported"]),
                card=item.get("card"),
                slot=item.get("slot"),
                quote=item.get("quote"),
                rule=item.get("rule"),
                rule_tokens=list(item.get("rule_tokens") or []),
                human=human,
                planted=item.get("planted"),
            )
        )
    usage = raw.get("usage") or {}
    return QuestionEvalResult(
        file_name=str(raw["file"]),
        index=int(raw["index"]),
        kind=str(raw["kind"]),
        question=str(raw["question"]),
        char_limit=raw.get("char_limit"),
        sentences=sentences,
        chars=int(raw.get("chars") or 0),
        cards_sent=int(raw.get("cards_sent") or 0),
        drop_reasons=dict(raw.get("drop_reasons") or {}),
        error=raw.get("error"),
        error_detail=raw.get("error_detail"),
        seconds=raw.get("seconds"),
        usage=LLMUsage(**usage),
        retries=int(raw.get("retries") or 0),
    )
