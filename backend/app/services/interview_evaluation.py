"""면접 질문 평가 (F-009 완료 기준 4, D-005 — 가상 카드에서 '카드에 없는 내용을 전제로 한 질문 수').

두 가지를 잰다(사용자 선택 2026-11-16 — F-008 자소서 평가와 같은 틀).
- 심은 질문 평가(핵심, D-005): AI 없이 카드마다 진짜 질문 3 + 일부러 만든 질문 4(종류마다 1)를 실제 검사 · 저장 흐름에
  넣고 종류별로 잡은 수를 센다. 판정이 들어가지 않는다. 아래 '심은 질문 평가' 구역.
- AI 질문 평가(참고): 실제 AI가 카드에서 만든 질문 중 저장된(화면에 보이는) 질문에서 '카드에 없는 내용을 전제로 한 질문 수'.

면접 질문은 자소서 문장과 달리 근거 검사를 못 넘으면 저장하지 않는다(F-009 완료 기준 1). 그래서 '검사가 잡았다' =
'저장되지 않았다'이고, 저장된 질문은 질문 글로 짝을 맞춘다.

'전제 있음' 판정은 채점 AI 없이 한다(사용자 선택 2026-11-16 — 규칙 + 규칙으로 못 가른 질문은 모두 사람 확인).
- 규칙: 질문의 숫자 · 영문 낱말이 AI에 보낸 카드 글(제목 · 칸)에 없으면 premise(전제 있음).
- 사람: 결과 파일의 질문마다 human(true = 전제 있음, false = 없음)을 적으면 규칙보다 앞선다. 한글 전제('팀장과 갈등이 있었을 때')는
  규칙으로 못 잡으므로, 규칙이 premise로 못 가른 저장 질문은 모두 '사람 확인 전'으로 센다(summary.labels_pending).

카드는 F-006 평가 노트로 AI 없이 만든다(posting_evaluation.build_eval_cards). 질문 만들기는 실제 서비스와 같은 함수
(prepare_interview → request_interview_questions → save_interview)를 쓴다. 평가용 임시 DB에서만 돈다.
"""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session

from app.config import CARD_SLOTS, INTERVIEW_MAX_QUOTE_CHARS, INTERVIEW_MIN_QUOTE_CHARS
from app.llm import MockLLMClient
from app.llm.base import LLMClient, LLMUsage, Message
from app.services.draft_evaluation import SentText, numbers_in, sent_payload, words_in
from app.services.eval_retry import RetryPolicy, run_ai_step
from app.services.interview_service import (
    InterviewPlan,
    InterviewWriteOutcome,
    QuestionView,
    abandon,
    list_card_questions,
    prepare_interview,
    save_failed,
    save_interview,
)
from app.services.interview_writing import SentFields, request_interview_questions
from app.services.posting_checks import DROP_TOO_MANY
from app.services.text_clean import visible_chars

RULE_PREMISE = "premise"  # 질문의 숫자 · 영문 낱말이 보낸 카드 글에 없음 → 전제 있음
OUTCOME_NO_QUESTIONS = "no_questions"  # 검사를 넘은 질문이 0개(저장 안 함)

# --- 규칙 판정 (채점 AI 없이) ---


def sent_card_text(messages: Sequence[Message]) -> SentText:
    """AI에 보낸 카드 글(제목 + 칸의 원문 인용 · 내 답) — interview_writing.build_interview_messages가 만든 JSON."""
    payload = sent_payload(messages)
    parts = [str(payload.get("card_title", ""))]
    for item in payload.get("fields", []):
        parts.extend(str(item.get(part, "")) for part in ("quote", "answer"))
    return SentText.of(parts)


def rule_verdict(question: str, card: SentText) -> tuple[str | None, list[str]]:
    """(규칙 판정, 카드 글에 없는 숫자 · 영문 낱말). 판정은 premise · None(규칙으로는 못 가름 — 사람이 본다)."""
    tokens = [(token, True) for token in numbers_in(question)] + [(token, False) for token in words_in(question)]
    unknown = sorted(token for token, number in tokens if not card.has(token, number=number))
    return (RULE_PREMISE, unknown) if unknown else (None, [])


# --- 결과 ---


@dataclass
class QuestionRecord:
    id: str  # 결과 파일 안에서 질문을 가리키는 이름(경험 id-q번호) — 사람 판정을 적을 때 씀
    question: str
    slot: str
    quote: str
    kept: bool  # 근거 검사를 넘어 저장됐는지(False = 검사가 버림 — 화면에 안 보임)
    planted: str | None = None  # 심은 질문 평가에서 일부러 만든 질문의 종류(PLANT_*). 진짜 질문은 None
    rule: str | None = None
    rule_tokens: list[str] = field(default_factory=list)
    human: bool | None = None  # 사람 판정(true = 카드에 없는 전제가 있음). 있으면 규칙보다 앞선다

    @property
    def premise(self) -> bool:
        return self.human if self.human is not None else self.rule == RULE_PREMISE

    @property
    def needs_human(self) -> bool:
        return self.kept and self.human is None and self.rule != RULE_PREMISE


@dataclass
class CardEvalResult:
    card: str  # 경험 id(평가 정답지)
    title: str
    fields_sent: int = 0
    received: int = 0  # AI가 준 질문 수(빈 질문 뺌)
    questions: list[QuestionRecord] = field(default_factory=list)
    drop_reasons: dict[str, int] = field(default_factory=dict)
    error: str | None = None  # AI 오류 종류 · no_questions — 이 카드는 질문 없이 센다
    error_detail: str | None = None  # 예상 못 한 오류의 메시지(앞부분만)
    seconds: float | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    retries: int = 0


def _saved_by_text(db: Session, plan: InterviewPlan) -> dict[str, QuestionView]:
    return {view.question: view for view in list_card_questions(db, user_id=plan.user_id, card_id=plan.card_id)}


def _record_outcome(result: CardEvalResult, outcome: InterviewWriteOutcome) -> None:
    result.fields_sent = outcome.fields_sent
    result.received = outcome.received
    result.drop_reasons = outcome.drop_reasons
    if not outcome.written:
        result.error = OUTCOME_NO_QUESTIONS


# --- AI 질문 평가 (참고) ---


async def evaluate_card(
    db: Session,
    *,
    user_id: int,
    card_id: int,
    experience: str,
    title: str,
    client: LLMClient,
    policy: RetryPolicy | None = None,
) -> CardEvalResult:
    """카드 하나: [면접 질문 만들기]를 실제 서비스 함수로 돌리고 저장된 질문마다 규칙 판정을 남긴다.

    AI 서버 오류(500 · 429)면 서비스처럼 save_failed로 정리한 뒤 policy대로 쉬고 다시 한다(eval_retry).
    예상 못 한 오류 · 중단은 abandon으로 선점을 풀고 올린다.
    """
    result = CardEvalResult(card=experience, title=title)
    outcome = await run_ai_step(
        prepare=lambda: prepare_interview(db, user_id=user_id, card_id=card_id),
        request=lambda plan: request_interview_questions(client, plan.messages),
        save_failed=lambda plan, exc: save_failed(db, plan, exc),
        abandon=lambda plan: abandon(db, plan),
        policy=policy or RetryPolicy(),
        usage_of=lambda reply: reply.usage,
    )
    result.seconds, result.usage, result.retries = outcome.seconds, outcome.usage, outcome.retries
    if outcome.error is not None or outcome.reply is None:
        result.error = type(outcome.error).__name__
        return result
    plan = outcome.plan
    _record_outcome(result, save_interview(db, plan, outcome.reply))
    card_text = sent_card_text(plan.messages)
    # 저장된 줄을 그대로 센다(글로 묶지 않음) — AI가 같은 글을 두 번 내도 저장된 수와 맞게(4차 리뷰 R1)
    views = list_card_questions(db, user_id=plan.user_id, card_id=plan.card_id)
    for view in views:
        rule, tokens = rule_verdict(view.question, card_text)
        result.questions.append(
            QuestionRecord(
                id=f"{experience}-q{view.position + 1}", question=view.question, slot=view.slot, quote=view.quote,
                kept=True, rule=rule, rule_tokens=tokens,
            )
        )
    return result


# --- 심은 질문 평가 (D-005 — AI 없이, 판정 없이) ---
# 실제 prepare_interview가 보낸 칸으로 '진짜 질문'(칸 글을 그대로 인용)과 '일부러 만든 질문'을 섞은 답을 만들고,
# 실제 request_interview_questions(형식 검사) → save_interview(근거 검사)에 넣는다. 어느 질문을 심었는지는 만들 때
# 정해지므로 매기는 사람의 판단이 들어가지 않는다. 검사기는 인용만 그 칸에서 글자 그대로 찾으므로, 결과는 '어떤 종류를
# 잡고 어떤 종류를 놓치는지'를 보여 준다 — 종류별로 나눠 본다.

PLANT_NO_EVIDENCE = "no_evidence"  # 근거 인용 없이 만든 질문
PLANT_FAKE_QUOTE = "fake_quote"  # 칸 글을 바꿔 쓴 인용(카드에 없는 말을 인용인 척)
PLANT_OTHER_SLOT = "other_slot"  # 진짜 인용을 다른 칸 이름에 붙임
PLANT_ADDED_PREMISE = "added_premise"  # 진짜 인용은 그대로, 질문에만 카드에 없는 전제(숫자 · 사람 · 기간 · 성과)
PLANT_TYPES = (PLANT_NO_EVIDENCE, PLANT_FAKE_QUOTE, PLANT_OTHER_SLOT, PLANT_ADDED_PREMISE)
PLANT_GENUINE_PER_CARD = 3  # 카드당 저장 상한(INTERVIEW_MAX_QUESTIONS 5) 안에서 진짜 3 + 심은 것 중 통과하는 1을 받게
PLANT_SNIPPET_CHARS = 80  # 진짜 인용으로 쓰는 칸 글 한 줄의 앞부분 길이(INTERVIEW_MAX_QUOTE_CHARS 안)

GENUINE_QUESTIONS = (
    "그때 가장 먼저 무엇을 확인했나요?",
    "그 방법을 고른 이유는 무엇인가요?",
    "그 경험에서 무엇을 배웠나요?",
)
PLANTED_QUESTIONS = {
    PLANT_NO_EVIDENCE: "이 프로젝트에서 팀을 이끌며 가장 힘들었던 점은 무엇인가요?",
    PLANT_FAKE_QUOTE: "그 결과로 팀에서 어떤 평가를 받았나요?",
    PLANT_OTHER_SLOT: "그 부분을 다른 단계에서는 어떻게 다뤘나요?",
    # 카드에 없는 숫자 · 사람 · 기간 · 성과를 사실처럼 깐 질문 — 프롬프트가 금지한 바로 그 모양
    PLANT_ADDED_PREMISE: "팀원 5명과 3개월 동안 진행해 매출이 20% 늘었다고 했는데, 그 과정에서 무엇이 가장 어려웠나요?",
}
FAKE_QUOTE_SUFFIX = " 덕분에 팀에서 칭찬을 받았다."


def _snippets(sent: SentFields) -> list[tuple[str, str]]:
    """보낸 칸마다 (칸, 글 한 줄의 앞부분) — 그 칸 글에 글자 그대로 있는 조각. 칸을 돌아가며 고르게 고른다."""
    per_slot: list[list[tuple[str, str]]] = []
    for slot in sent.slots:
        pieces = []
        for text in sent.card.fields[slot]:
            for line in (text or "").split("\n"):
                piece = line.strip()[:PLANT_SNIPPET_CHARS].strip()
                if visible_chars(piece) >= INTERVIEW_MIN_QUOTE_CHARS:
                    pieces.append((slot, piece))
        per_slot.append(pieces)
    ordered: list[tuple[str, str]] = []
    for depth in range(max((len(pieces) for pieces in per_slot), default=0)):
        ordered.extend(pieces[depth] for pieces in per_slot if depth < len(pieces))
    return ordered


def _other_slot(slot: str, piece: str, sent: SentFields) -> str:
    """같은 조각이 없는 다른 칸. 보낸 칸이 하나뿐이면 보내지 않은 칸 이름(검사기는 그것도 버려야 한다)."""
    for other in sent.slots:
        if other != slot and all(piece not in (text or "") for text in sent.card.fields[other]):
            return other
    unsent = [other for other in CARD_SLOTS if other not in sent.slots]
    if not unsent:
        raise ValueError(f"'{piece[:20]}…'가 모든 칸에 있어 '다른 칸 인용'을 만들 수 없어요.")
    return unsent[0]


def _planted_item(kind: str, snippet: tuple[str, str], sent: SentFields) -> dict[str, str]:
    slot, piece = snippet
    question = PLANTED_QUESTIONS[kind]
    if kind == PLANT_NO_EVIDENCE:
        return {"slot": slot, "question": question, "quote": ""}
    if kind == PLANT_FAKE_QUOTE:
        room = INTERVIEW_MAX_QUOTE_CHARS - len(FAKE_QUOTE_SUFFIX)
        return {"slot": slot, "question": question, "quote": piece[:room] + FAKE_QUOTE_SUFFIX}
    if kind == PLANT_OTHER_SLOT:
        return {"slot": _other_slot(slot, piece, sent), "question": question, "quote": piece}
    if kind == PLANT_ADDED_PREMISE:
        return {"slot": slot, "question": question, "quote": piece}
    raise ValueError(f"모르는 심은 질문 종류: {kind}")


def planted_questions(sent: SentFields) -> tuple[list[dict[str, str]], list[str | None]]:
    """(AI 답 질문 목록, 질문마다 심은 종류 — 진짜 질문은 None). 진짜 3 사이사이에 종류마다 하나씩 끼운다."""
    snippets = _snippets(sent)
    if not snippets:
        raise ValueError("보낸 칸에 인용으로 쓸 글이 없어요.")
    picked = [snippets[index % len(snippets)] for index in range(PLANT_GENUINE_PER_CARD)]  # 조각이 적으면 돌려 씀
    genuine: list[tuple[dict[str, str], str | None]] = [
        ({"slot": slot, "question": text, "quote": piece}, None)
        for text, (slot, piece) in zip(GENUINE_QUESTIONS, picked, strict=True)
    ]
    fakes = [(_planted_item(kind, snippets[index % len(snippets)], sent), kind) for index, kind in enumerate(PLANT_TYPES)]
    mixed: list[tuple[dict[str, str], str | None]] = []
    for index, item in enumerate(genuine):  # 진 · 심 · 진 · 심 · 진 · 심 · 심
        mixed.append(item)
        if index < len(fakes):
            mixed.append(fakes[index])
    mixed.extend(fakes[len(genuine):])
    return [item for item, _ in mixed], [label for _, label in mixed]


async def evaluate_planted_card(db: Session, *, user_id: int, card_id: int, experience: str, title: str) -> CardEvalResult:
    """카드 하나: 실제 prepare_interview → (심은 답) request_interview_questions → save_interview. AI는 부르지 않는다."""
    result = CardEvalResult(card=experience, title=title)
    plan = prepare_interview(db, user_id=user_id, card_id=card_id)
    try:
        items, labels = planted_questions(plan.sent)
        planted_ai = MockLLMClient([json.dumps({"questions": items}, ensure_ascii=False)])
        reply = await request_interview_questions(planted_ai, plan.messages)
    except BaseException:
        abandon(db, plan)
        raise
    _record_outcome(result, save_interview(db, plan, reply))
    if result.drop_reasons.get(DROP_TOO_MANY):  # 상한에 걸려 버린 질문은 '잡음'과 구별할 수 없다
        raise ValueError(f"{experience}: 저장 상한을 넘어 버린 질문이 있어요 — 심은 질문 수를 줄여야 해요.")
    saved = _saved_by_text(db, plan)
    for index, (item, label) in enumerate(zip(items, labels, strict=True), start=1):
        view = saved.get(item["question"])
        result.questions.append(
            QuestionRecord(
                id=f"{experience}-p{index}", question=item["question"], slot=item["slot"], quote=item["quote"],
                kept=view is not None, planted=label,
            )
        )
    if sum(1 for record in result.questions if record.kept) != len(saved):  # 짝이 안 맞으면 종류를 붙일 수 없다
        raise ValueError(f"{experience}: 저장된 질문 {len(saved)}개를 심은 질문과 짝지을 수 없어요.")
    return result


def summarize_planted(results: Sequence[CardEvalResult]) -> dict[str, object]:
    records = [record for result in results for record in result.questions]
    fakes = [record for record in records if record.planted is not None]
    genuine = [record for record in records if record.planted is None]
    caught = sum(1 for record in fakes if not record.kept)
    by_type: dict[str, dict[str, object]] = {}
    for kind in PLANT_TYPES:
        planted = [record for record in fakes if record.planted == kind]
        kind_caught = sum(1 for record in planted if not record.kept)
        by_type[kind] = {"planted": len(planted), "caught": kind_caught, "catch_rate": _rate(kind_caught, len(planted))}
    return {
        "cards": len(results),
        "questions": len(records),
        # 핵심 수치
        "planted": len(fakes),
        "planted_caught": caught,
        "catch_rate": _rate(caught, len(fakes)),
        "by_type": by_type,
        # 진단: 진짜 질문(칸 글을 그대로 인용)을 검사가 버린 수 — 0이어야 한다
        "genuine": len(genuine),
        "genuine_dropped": sum(1 for record in genuine if not record.kept),
        "drop_reasons": dict(_drops(results)),
        "failures": sum(1 for result in results if result.error),
    }


# --- 요약 ---


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _drops(results: Sequence[CardEvalResult]) -> Counter[str]:
    drops: Counter[str] = Counter()
    for result in results:
        drops.update(result.drop_reasons)
    return drops


def summarize(results: Sequence[CardEvalResult]) -> dict[str, object]:
    records = [record for result in results for record in result.questions if record.kept]
    written = [result for result in results if any(record.kept for record in result.questions)]
    premise = [record for record in records if record.premise]
    usage = LLMUsage()
    for result in results:
        usage = usage + result.usage
    seconds = [result.seconds for result in results if result.seconds is not None]
    return {
        "cards": len(results),
        "cards_written": len(written),
        "received": sum(result.received for result in results),
        "saved": len(records),
        # 핵심 수치: 저장된(화면에 보이는) 질문 중 카드에 없는 내용을 전제로 한 질문
        "premise": len(premise),
        "premise_rate": _rate(len(premise), len(records)),
        "premise_per_card": round(len(premise) / len(written), 2) if written else None,
        "labels_pending": sum(1 for record in records if record.needs_human),
        # 진단
        "premise_by_rule": sum(1 for record in records if record.rule == RULE_PREMISE),
        "drop_reasons": dict(_drops(results)),
        "failures": sum(1 for result in results if result.error),
        "retries": sum(result.retries for result in results),
        "seconds_avg": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "seconds_max": round(max(seconds), 1) if seconds else None,
        "usage": asdict(usage),
    }


def result_to_dict(result: CardEvalResult) -> dict[str, object]:
    return {
        "card": result.card,
        "title": result.title,
        "fields_sent": result.fields_sent,
        "received": result.received,
        "drop_reasons": result.drop_reasons,
        "error": result.error,
        "error_detail": result.error_detail,
        "retries": result.retries,
        "seconds": round(result.seconds, 1) if result.seconds is not None else None,
        "usage": asdict(result.usage),
        "questions": [asdict(record) for record in result.questions],
    }


def result_from_dict(raw: object) -> CardEvalResult:
    """결과 파일 → 결과(사람 판정을 적은 뒤 다시 채점할 때). human은 true · false · null만 받는다.

    손으로 고친 파일이라 모양이 틀릴 수 있다 — 틀리면 TypeError(다시 채점이 트레이스백 대신 이유를 알리게, 4차 리뷰 R3).
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("questions", []), list):
        raise TypeError("카드 결과는 {...} 모양이고 questions는 목록이어야 해요.")
    questions = []
    for item in raw.get("questions", []):
        if not isinstance(item, dict):
            raise TypeError(f"{raw.get('card')}: 질문은 {{...}} 모양이어야 해요.")
        human = item.get("human")
        if human not in (True, False, None):
            raise ValueError(f"{item.get('id')}: human은 true · false · null만 쓸 수 있어요.")
        questions.append(
            QuestionRecord(
                id=str(item["id"]),
                question=str(item["question"]),
                slot=str(item.get("slot") or ""),
                quote=str(item.get("quote") or ""),
                kept=bool(item["kept"]),
                planted=item.get("planted"),
                rule=item.get("rule"),
                rule_tokens=list(item.get("rule_tokens") or []),
                human=human,
            )
        )
    usage = raw.get("usage") or {}
    return CardEvalResult(
        card=str(raw["card"]),
        title=str(raw.get("title") or ""),
        fields_sent=int(raw.get("fields_sent") or 0),
        received=int(raw.get("received") or 0),
        questions=questions,
        drop_reasons=dict(raw.get("drop_reasons") or {}),
        error=raw.get("error"),
        error_detail=raw.get("error_detail"),
        seconds=raw.get("seconds"),
        usage=LLMUsage(**usage),
        retries=int(raw.get("retries") or 0),
    )
