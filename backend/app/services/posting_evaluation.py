"""공고 분석 평가 (F-007 완료 기준 6, D-005 — 정답을 미리 정해 둔 가상 공고 · 가상 카드).

재는 것
- 매칭 적중률: 근거 카드가 있어야 하는 역량 중, 정답 카드가 하나라도 매칭된 역량의 비율(역량을 못 뽑았으면 놓친 것으로 셈).
- 없는 근거로 만든 매칭 수: 정답 목록에 없는 카드가 매칭된 수. 근거가 없어야 하는 역량(함정)에 붙은 매칭과
  근거가 있는 역량에 엉뚱한 카드가 붙은 매칭을 나눠 센다.
- (진단) 역량 뽑기 적중: 정답지 역량 줄을 뽑은 비율, 필수/우대를 맞힌 비율, 정답지에 없는 역량 수.
- (진단) 키워드 후보에 정답 카드가 들어간 비율 — 적중률이 낮을 때 키워드 후보(D-016 한계) 탓인지 AI 판정 탓인지 가른다.
- 인용 검사로 버린 수(공고 인용 · 카드 칸 인용) — 서버가 막은 '지어낸 근거'.

판정은 채점 AI 없이 한다(카드 평가와 같은 방식 — 매기는 사람 · AI의 판단이 섞이지 않게).
- 뽑은 역량은 공고 인용 위치가 정답지 역량 줄과 가장 많이 겹치는 줄로 잇는다. 어느 줄과도 안 겹치면 '정답지에 없는 역량'.
- 매칭은 카드 번호 → 경험 id로 바꿔 정답 목록과 비교한다.

카드는 F-006 평가 노트에 심은 경험 구간으로 AI 없이 만든다(build_eval_cards) — 카드 찾기 품질과 섞지 않고 매칭만 재려고.
공고 분석은 실제 서비스와 같은 함수(prepare_* → request_* → save_*)를 그대로 쓴다. 평가용 임시 DB에서만 돈다.
"""

import asyncio
import dataclasses
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from sqlalchemy.orm import Session

from app.config import APPLICATION_COMPANY_MAX_CHARS, CARD_STATUS_SAVED
from app.db.models import Card, CardField
from app.llm.base import LLMClient, LLMError, LLMUsage, Message
from app.llm.structured import StructuredReply
from app.services.application_service import create_application, get_application_detail
from app.services.card_evaluation import NoteKey, section_spans
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user
from app.services.posting_analysis import (
    AnalysisPlan,
    abandon,
    prepare_extract,
    prepare_match,
    save_extract,
    save_failed,
    save_match,
)
from app.services.posting_extraction import request_requirements
from app.services.posting_matching import request_matches
from app.services.quiz_evaluation import RETRYABLE_ERRORS

# --- 정답지 ---


@dataclass(frozen=True)
class RequirementKey:
    quote: str  # 공고 본문의 한 줄(글자 그대로)
    kind: str  # required · preferred
    cards: tuple[str, ...]  # 근거로 인정하는 경험 id. 비면 근거가 없어야 하는 역량(함정)


@dataclass(frozen=True)
class PostingKey:
    requirements: tuple[RequirementKey, ...]


def parse_posting_key(raw: Mapping[str, object]) -> dict[str, PostingKey]:
    postings = raw.get("postings")
    if not isinstance(postings, Mapping) or not postings:
        raise ValueError("정답지에 postings가 없어요.")
    keys: dict[str, PostingKey] = {}
    for name, item in postings.items():
        if not isinstance(item, Mapping) or not isinstance(item.get("requirements"), list) or not item["requirements"]:
            raise ValueError(f"{name}: requirements가 없어요.")
        requirements = []
        for entry in item["requirements"]:
            if (
                not isinstance(entry, Mapping)
                or not isinstance(entry.get("quote"), str)
                or entry.get("kind") not in ("required", "preferred")
                or not isinstance(entry.get("cards"), list)
                or not all(isinstance(card, str) for card in entry["cards"])
            ):
                raise ValueError(f"{name}: 요구 역량 모양이 틀렸어요 — {entry}")
            requirements.append(RequirementKey(quote=entry["quote"], kind=entry["kind"], cards=tuple(entry["cards"])))
        keys[str(name)] = PostingKey(requirements=tuple(requirements))
    return keys


def key_spans(posting_text: str, key: PostingKey) -> list[tuple[int, int]]:
    """정답지 역량 줄의 공고 위치. 공고에 글자 그대로 없거나 두 번 나오면 평가 전에 멈춘다(정답지 오타)."""
    spans = []
    for requirement in key.requirements:
        start = posting_text.find(requirement.quote)
        if start < 0 or posting_text.find(requirement.quote, start + 1) >= 0:
            raise ValueError(f"정답지 역량 줄이 공고에 한 번만 있어야 해요: {requirement.quote}")
        spans.append((start, start + len(requirement.quote)))
    return spans


def all_experience_ids(card_keys: Mapping[str, NoteKey]) -> set[str]:
    return {experience.id for key in card_keys.values() for experience in key.experiences}


def check_card_references(posting_keys: Mapping[str, PostingKey], card_keys: Mapping[str, NoteKey]) -> None:
    """공고 정답지가 없는 경험 id를 가리키면 평가 전에 멈춘다."""
    known = all_experience_ids(card_keys)
    unknown = sorted(
        {card for key in posting_keys.values() for requirement in key.requirements for card in requirement.cards} - known
    )
    if unknown:
        raise ValueError(f"카드 정답지에 없는 경험 id: {unknown}")


# --- 평가용 카드 (AI 없이) ---


def _paragraphs(body: str, offset: int) -> list[tuple[str, int]]:
    """구간 본문을 빈 줄로 나눈 문단(글, 원문 위치). 목록 · 빈 문단은 그대로 문단 하나."""
    found: list[tuple[str, int]] = []
    position = 0
    for block in body.split("\n\n"):
        text = block.strip()
        if text:
            found.append((text, offset + position + block.index(text)))
        position += len(block) + 2
    return found


def build_eval_cards(
    db: Session, *, user_id: int, notes_dir: Path, card_keys: Mapping[str, NoteKey]
) -> dict[int, str]:
    """경험마다 저장 카드 1장을 만든다. 칸 인용 = 경험 구간 문단(첫 문단 상황, 마지막 결과, 사이는 행동). 카드 번호 → 경험 id."""
    card_experience: dict[int, str] = {}
    for file_name, key in card_keys.items():
        content = (notes_dir / file_name).read_text(encoding="utf-8")
        title = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), file_name)
        note = create_note_for_user(db, user_id=user_id, title=title, content=content, chunks=split_markdown(content))
        spans = section_spans(content)
        for experience in key.experiences:
            paragraphs: list[tuple[str, int]] = []
            for section in experience.sections:
                start, end = spans[section]
                heading_end = content.index("\n", start) + 1
                paragraphs.extend(_paragraphs(content[heading_end:end], heading_end))
            if not paragraphs:
                raise ValueError(f"{file_name}: 경험 {experience.id}의 구간이 비었어요.")
            slots: dict[str, list[tuple[str, int]]] = {"situation": paragraphs[:1]}
            if len(paragraphs) >= 3:
                slots["action"] = paragraphs[1:-1]
                slots["result"] = paragraphs[-1:]
            elif len(paragraphs) == 2:
                slots["action"] = paragraphs[1:]
            card = Card(user_id=user_id, note_id=note.id, title=experience.sections[0], status=CARD_STATUS_SAVED)
            for slot in ("situation", "task", "action", "result"):
                parts = slots.get(slot)
                if parts:
                    # 사이 문단이 여럿이면 첫 문단만 원문 위치를 두고 이어 붙인다(평가 카드라 위치는 참고용)
                    quote = "\n\n".join(text for text, _ in parts)
                    start = parts[0][1]
                    card.fields.append(
                        CardField(user_id=user_id, slot=slot, quote=quote, quote_start=start, quote_end=start + len(quote))
                    )
                else:
                    card.fields.append(CardField(user_id=user_id, slot=slot, question="(평가 카드 빈칸)"))
            db.add(card)
            db.flush()
            card_experience[card.id] = experience.id
    db.commit()
    return card_experience


# --- 채점 ---


@dataclass(frozen=True)
class ExtractedRequirement:
    id: int
    name: str
    kind: str
    quote_start: int
    quote_end: int
    matched_cards: tuple[int, ...]


@dataclass
class RequirementVerdict:
    quote: str
    expected: list[str]
    kind_expected: str
    found: bool = False
    kind_correct: bool = False
    extracted_names: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)  # 키워드 후보로 AI에 보낸 카드(경험 id)
    matched: list[str] = field(default_factory=list)  # 매칭된 카드(경험 id)

    @property
    def has_evidence(self) -> bool:
        return bool(self.expected)

    @property
    def hit(self) -> bool:
        return any(card in self.expected for card in self.matched)

    @property
    def wrong(self) -> list[str]:
        return [card for card in self.matched if card not in self.expected]

    @property
    def candidate_has_answer(self) -> bool:
        return any(card in self.expected for card in self.candidates)


@dataclass
class PostingScore:
    verdicts: list[RequirementVerdict] = field(default_factory=list)
    extra_requirements: list[dict[str, object]] = field(default_factory=list)  # 정답지에 없는 역량(이름 · 매칭 카드)


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def score_posting(
    posting_text: str,
    key: PostingKey,
    extracted: Sequence[ExtractedRequirement],
    candidates: Mapping[int, Sequence[int]],
    card_experience: Mapping[int, str],
) -> PostingScore:
    spans = key_spans(posting_text, key)
    score = PostingScore(
        verdicts=[
            RequirementVerdict(quote=item.quote, expected=list(item.cards), kind_expected=item.kind)
            for item in key.requirements
        ]
    )

    def experiences(card_ids: Sequence[int]) -> list[str]:
        return [card_experience.get(card_id, f"card-{card_id}") for card_id in card_ids]

    for item in extracted:
        overlaps = [_overlap((item.quote_start, item.quote_end), span) for span in spans]
        best = max(range(len(spans)), key=lambda index: overlaps[index]) if spans else -1
        if best < 0 or overlaps[best] == 0:
            score.extra_requirements.append({"name": item.name, "matched": experiences(item.matched_cards)})
            continue
        verdict = score.verdicts[best]
        verdict.found = True
        verdict.extracted_names.append(item.name)
        verdict.kind_correct = verdict.kind_correct or item.kind == verdict.kind_expected
        for card in experiences(candidates.get(item.id, [])):
            if card not in verdict.candidates:
                verdict.candidates.append(card)
        for card in experiences(item.matched_cards):
            if card not in verdict.matched:
                verdict.matched.append(card)
    return score


# --- 공고 하나 평가 (실제 서비스 흐름) ---


@dataclass
class PostingEvalResult:
    file_name: str
    company: str
    score: PostingScore = field(default_factory=PostingScore)
    error: str | None = None  # AI 오류 종류(있으면 이 공고는 그 단계에서 멈춤)
    error_step: str | None = None
    extract_drops: dict[str, int] = field(default_factory=dict)
    match_drops: dict[str, int] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)
    usage: LLMUsage = field(default_factory=LLMUsage)
    retries: int = 0


Sleep = Callable[[float], Awaitable[None]]
PlanT = TypeVar("PlanT", bound=AnalysisPlan)
ReplyT = TypeVar("ReplyT")


@dataclass(frozen=True)
class RetryPolicy:
    """AI 서버 오류(500 · 429)면 단계마다 몇 번 더 해 볼지 · 얼마나 쉴지(T-006). sleep은 테스트에서 바꿔 끼운다."""

    retries: int = 0
    wait: float = 60.0
    sleep: Sleep = asyncio.sleep


async def _run_step(
    db: Session,
    client: LLMClient,
    result: PostingEvalResult,
    *,
    step: str,
    prepare: Callable[[], PlanT],
    request: Callable[[LLMClient, Sequence[Message]], Awaitable[StructuredReply[ReplyT]]],
    policy: RetryPolicy,
    needs_ai: Callable[[PlanT], bool] = lambda plan: True,
) -> tuple[PlanT, StructuredReply[ReplyT] | None]:
    """한 단계(① 또는 ②): 선점 → AI → (다시 해 볼 오류면 쉬고 처음부터). (마지막 계획, 답 또는 None)을 돌려준다.

    답이 None이면 AI를 안 불렀거나(needs_ai가 False) 실패한 것 — 실패면 result.error · error_step이 채워진다.
    실패는 서비스와 똑같이 save_failed로, 예상 못 한 오류 · 중단은 abandon으로 정리한다(선점 · 사용량).
    """
    left = max(0, policy.retries)
    while True:
        plan = prepare()
        if not needs_ai(plan):
            return plan, None
        started = time.perf_counter()
        try:
            reply = await request(client, plan.messages)
        except LLMError as exc:
            result.seconds[step] = time.perf_counter() - started
            result.usage = result.usage + exc.usage
            save_failed(db, plan, exc)
            if isinstance(exc, RETRYABLE_ERRORS) and left > 0:
                left -= 1
                result.retries += 1
                await policy.sleep(policy.wait)
                continue
            result.error, result.error_step = type(exc).__name__, step
            return plan, None
        except BaseException:
            abandon(db, plan)
            raise
        result.seconds[step] = time.perf_counter() - started
        result.usage = result.usage + reply.usage
        return plan, reply


async def evaluate_posting(
    db: Session,
    *,
    user_id: int,
    file_name: str,
    posting_text: str,
    key: PostingKey,
    card_experience: Mapping[int, str],
    client: LLMClient,
    retries: int = 0,
    retry_wait: float = 60.0,
    sleep: Sleep = asyncio.sleep,
) -> PostingEvalResult:
    """공고 하나: 공고 추가 → ① 역량 뽑기 → ② 매칭을 실제 서비스 함수로 돌리고 정답지와 비교한다."""
    first_line = next((line.strip() for line in posting_text.splitlines() if line.strip()), file_name)
    company = first_line[:APPLICATION_COMPANY_MAX_CHARS]  # 공고 첫 줄을 회사 칸으로(평가용)
    result = PostingEvalResult(file_name=file_name, company=company)
    result.score = score_posting(posting_text, key, [], {}, card_experience)  # AI가 실패해도 정답지 줄 수는 센다
    application_id = create_application(
        db, user_id=user_id, company=company, role="평가", deadline=None, url=None, posting_text=posting_text, questions=[]
    )
    policy = RetryPolicy(retries=retries, wait=retry_wait, sleep=sleep)

    plan, reply = await _run_step(
        db, client, result, step="extract", policy=policy, request=request_requirements,
        prepare=lambda: prepare_extract(db, user_id=user_id, application_id=application_id),
    )
    if reply is None:
        return result
    extract_outcome = save_extract(db, plan, reply)
    result.extract_drops = extract_outcome.drop_reasons
    if extract_outcome.requirement_count == 0:
        return result

    # 키워드 후보가 없으면 서비스처럼 AI 없이 끝(모든 역량 '근거 없음')
    match_plan, match_reply = await _run_step(
        db, client, result, step="match", policy=policy, request=request_matches,
        prepare=lambda: prepare_match(db, user_id=user_id, application_id=application_id),
        needs_ai=lambda plan: plan.needs_ai,
    )
    candidates = {req_id: list(cards) for req_id, cards in match_plan.candidates.items()}
    if not (match_plan.needs_ai and match_reply is None):  # 매칭 AI가 실패했으면 저장 없이 뽑은 역량만으로 채점(매칭 0)
        result.match_drops = save_match(db, match_plan, match_reply).drop_reasons
    extracted = _load_extracted(db, user_id=user_id, application_id=application_id)
    result.score = score_posting(posting_text, key, extracted, candidates, card_experience)
    return result


def _load_extracted(db: Session, *, user_id: int, application_id: int) -> list[ExtractedRequirement]:
    detail = get_application_detail(db, user_id=user_id, application_id=application_id)
    return [
        ExtractedRequirement(
            id=item.id,
            name=item.name,
            kind=item.kind,
            quote_start=item.quote_start,
            quote_end=item.quote_end,
            matched_cards=tuple(match.card_id for match in item.matches),
        )
        for item in detail.requirements
    ]


# --- 요약 ---


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def summarize(results: Sequence[PostingEvalResult]) -> dict[str, object]:
    verdicts = [verdict for result in results for verdict in result.score.verdicts]
    evidence = [verdict for verdict in verdicts if verdict.has_evidence]
    traps = [verdict for verdict in verdicts if not verdict.has_evidence]
    found_evidence = [verdict for verdict in evidence if verdict.found]
    hits = sum(1 for verdict in evidence if verdict.hit)
    trap_matches = sum(len(verdict.matched) for verdict in traps)
    wrong_on_evidence = sum(len(verdict.wrong) for verdict in evidence)
    extract_drops: Counter[str] = Counter()
    match_drops: Counter[str] = Counter()
    for result in results:
        extract_drops.update(result.extract_drops)
        match_drops.update(result.match_drops)
    usage = LLMUsage()
    for result in results:
        usage = usage + result.usage
    seconds = [value for result in results for value in result.seconds.values()]
    return {
        "postings": len(results),
        "requirements_seeded": len(verdicts),
        "requirements_with_evidence": len(evidence),
        "requirements_without_evidence": len(traps),
        # 핵심 수치
        "match_hits": hits,
        "match_hit_rate": _rate(hits, len(evidence)),
        "false_matches": trap_matches + wrong_on_evidence,
        "false_matches_on_traps": trap_matches,
        "false_matches_wrong_card": wrong_on_evidence,
        # 진단
        "requirements_found": sum(1 for verdict in verdicts if verdict.found),
        "requirement_found_rate": _rate(sum(1 for verdict in verdicts if verdict.found), len(verdicts)),
        "kind_correct": sum(1 for verdict in verdicts if verdict.kind_correct),
        "extra_requirements": sum(len(result.score.extra_requirements) for result in results),
        "match_hit_rate_among_found": _rate(hits, len(found_evidence)),
        "candidate_recall_among_found": _rate(
            sum(1 for verdict in found_evidence if verdict.candidate_has_answer), len(found_evidence)
        ),
        "traps_left_empty": sum(1 for verdict in traps if verdict.found and not verdict.matched),
        "traps_found": sum(1 for verdict in traps if verdict.found),
        "extract_drop_reasons": dict(extract_drops),
        "match_drop_reasons": dict(match_drops),
        "failures": sum(1 for result in results if result.error),
        "retries": sum(result.retries for result in results),
        "seconds_avg": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "seconds_max": round(max(seconds), 1) if seconds else None,
        "usage": dataclasses.asdict(usage),
    }


def result_to_dict(result: PostingEvalResult) -> dict[str, object]:
    return {
        "file": result.file_name,
        "company": result.company,
        "error": result.error,
        "error_step": result.error_step,
        "retries": result.retries,
        "seconds": {step: round(value, 1) for step, value in result.seconds.items()},
        "extract_drops": result.extract_drops,
        "match_drops": result.match_drops,
        "requirements": [
            {
                "quote": verdict.quote,
                "expected": verdict.expected,
                "found": verdict.found,
                "extracted_as": verdict.extracted_names,
                "kind_correct": verdict.kind_correct,
                "candidates": verdict.candidates,
                "matched": verdict.matched,
                "hit": verdict.hit if verdict.has_evidence else None,
                "wrong": verdict.wrong,
            }
            for verdict in result.score.verdicts
        ],
        "extra_requirements": result.score.extra_requirements,
    }
