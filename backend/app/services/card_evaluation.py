"""경험 카드 평가 (F-006 완료 기준 7, D-005 — 경험을 미리 심어 둔 가상 노트).

재는 것 (사용자 확인 2026-11-11)
- 찾은 비율: 심어 둔 경험 중 후보로 찾은 경험의 비율.
- 없는 경험으로 만든 후보 수: 함정 구간(개념 설명 · 계획 · 남의 경험)이나 경험이 없는 노트에서 나온 후보.
- 인용 검사로 빈칸이 된 칸 비율: AI가 인용을 준 칸 중 검사(글자 그대로 있는지 등)에서 빈칸으로 돌린 비율.
- (덤) 기록에 없는 칸을 빈칸으로 남긴 비율: 정답지에 '빠진 칸'으로 적은 칸을 AI가 인용 없이 둔 비율.

판정은 채점 AI 없이 인용 위치로 한다(사용자 선택 2026-11-11 — 매기는 사람 · AI의 판단이 섞이지 않게).
- 정답지(eval/cards/answers.json)는 경험 · 함정을 노트의 '## 제목' 구간으로 적는다.
- 후보 하나는 인용이 가장 많이 들어간 구간으로 판정한다. 동률이면 경험 구간을 고른다(경험 순서가 앞선 쪽).
- 인용이 두 구간 이상에 걸치면 '섞임'으로 표시한다(판정은 그대로, 사람이 골라 보게).
- 같은 경험에서 후보가 둘 이상 나오면 첫 후보만 '찾음', 나머지는 '중복'으로 센다.

후보 찾기는 실제 서비스와 같은 함수(prepare_search → request_card_drafts → save_search)를 그대로 쓴다.
평가용 DB(scripts/card_eval.py의 임시 SQLite)에서 돌리므로 개발 DB · 내 계정은 건드리지 않는다.
"""

import asyncio
import dataclasses
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import CARD_SLOTS
from app.db.models import Card, Note
from app.llm.base import LLMClient, LLMError, LLMUsage
from app.services.card_generation import (
    NoChunks,
    abandon_search,
    prepare_search,
    request_card_drafts,
    save_failed_search,
    save_search,
)
from app.services.quiz_evaluation import RETRYABLE_ERRORS

KIND_EXPERIENCE = "experience"
KIND_TRAP = "trap"
KIND_OUTSIDE = "outside"  # 정답지의 어느 구간에도 없는 인용(노트 제목 줄 등)
KIND_NO_EXPERIENCE_NOTE = "no_experience_note"  # 경험이 없는 노트에서 나온 후보

_SECTION_HEADING = re.compile(r"^(#{1,2})\s+(.+?)\s*$", re.MULTILINE)


# --- 정답지 ---


@dataclass(frozen=True)
class ExperienceKey:
    id: str
    sections: tuple[str, ...]
    missing: tuple[str, ...] = ()  # 기록에 없어서 빈칸으로 남아야 하는 칸(확실한 것만)


@dataclass(frozen=True)
class TrapKey:
    section: str
    kind: str  # concept · plan · others


@dataclass(frozen=True)
class NoteKey:
    experiences: tuple[ExperienceKey, ...]
    traps: tuple[TrapKey, ...] = ()


def parse_answer_key(raw: Mapping[str, object]) -> dict[str, NoteKey]:
    """answers.json의 notes 부분을 읽는다. 칸 이름이 틀리면 평가 전에 멈춘다."""
    keys: dict[str, NoteKey] = {}
    for file_name, note in dict(raw["notes"]).items():  # type: ignore[arg-type]
        experiences = []
        for item in note["experiences"]:
            missing = tuple(item.get("missing", []))
            unknown = [slot for slot in missing if slot not in CARD_SLOTS]
            if unknown:
                raise ValueError(f"{file_name} {item['id']}: 모르는 칸 {unknown}")
            experiences.append(ExperienceKey(id=item["id"], sections=tuple(item["sections"]), missing=missing))
        traps = tuple(TrapKey(section=item["section"], kind=item["kind"]) for item in note.get("traps", []))
        keys[file_name] = NoteKey(experiences=tuple(experiences), traps=traps)
    return keys


# --- 구간 ---


@dataclass(frozen=True)
class Region:
    kind: str  # KIND_EXPERIENCE · KIND_TRAP
    id: str  # 경험 id 또는 "trap:<구간 제목>"
    start: int
    end: int


def section_spans(markdown: str) -> dict[str, tuple[int, int]]:
    """'## 제목' 구간마다 (시작, 끝) — 제목 줄부터 다음 '#' · '##' 제목 직전까지. '###' 이하는 구간 안에 포함."""
    headings = [(m.start(), len(m.group(1)), m.group(2)) for m in _SECTION_HEADING.finditer(markdown)]
    spans: dict[str, tuple[int, int]] = {}
    for index, (start, level, title) in enumerate(headings):
        if level != 2:
            continue
        end = headings[index + 1][0] if index + 1 < len(headings) else len(markdown)
        if title in spans:
            raise ValueError(f"같은 제목의 구간이 두 번 있어요: {title}")
        spans[title] = (start, end)
    return spans


def build_regions(markdown: str, key: NoteKey) -> list[Region]:
    """정답지 구간을 노트 원문 위치로 바꾼다. 정답지의 제목이 노트에 없으면 평가 전에 멈춘다(정답지 오타)."""
    spans = section_spans(markdown)

    def span_of(title: str) -> tuple[int, int]:
        if title not in spans:
            raise ValueError(f"노트에 '## {title}' 구간이 없어요")
        return spans[title]

    regions = [
        Region(KIND_EXPERIENCE, experience.id, *span_of(title))
        for experience in key.experiences
        for title in experience.sections
    ]
    regions += [Region(KIND_TRAP, f"trap:{trap.section}", *span_of(trap.section)) for trap in key.traps]
    return regions


# --- 후보 판정 ---


@dataclass(frozen=True)
class CandidateField:
    slot: str
    quote: str | None
    quote_start: int | None
    question: str | None


@dataclass(frozen=True)
class Candidate:
    card_id: int
    title: str
    fields: tuple[CandidateField, ...]


@dataclass(frozen=True)
class CandidateVerdict:
    candidate: Candidate
    kind: str  # KIND_EXPERIENCE · KIND_TRAP · KIND_OUTSIDE · KIND_NO_EXPERIENCE_NOTE
    target: str | None  # 경험 id · "trap:<제목>" · None
    mixed: bool  # 인용이 두 구간 이상에 걸침
    duplicate: bool = False  # 같은 경험의 두 번째 이후 후보
    quote_regions: dict[str, str] = field(default_factory=dict)  # 칸 → 구간 id(또는 "outside")


def _region_of(position: int, regions: Sequence[Region]) -> Region | None:
    for region in regions:
        if region.start <= position < region.end:
            return region
    return None


def judge_candidate(candidate: Candidate, regions: Sequence[Region] | None) -> CandidateVerdict:
    """regions가 None이면 경험이 없는 노트 — 후보는 모두 '없는 경험으로 만든 후보'다."""
    if regions is None:
        return CandidateVerdict(candidate, KIND_NO_EXPERIENCE_NOTE, None, mixed=False)
    counts: Counter[str] = Counter()
    by_id: dict[str, Region] = {}
    quote_regions: dict[str, str] = {}
    for item in candidate.fields:
        if item.quote is None or item.quote_start is None:
            continue
        region = _region_of(item.quote_start, regions)
        region_id = region.id if region is not None else KIND_OUTSIDE
        if region is not None:
            by_id[region.id] = region
        counts[region_id] += 1
        quote_regions[item.slot] = region_id
    if not counts:  # 저장된 후보는 인용이 1개 이상이라 여기 오지 않는다(안전망)
        return CandidateVerdict(candidate, KIND_OUTSIDE, None, mixed=False)

    order = {region.id: index for index, region in enumerate(regions)}  # 경험이 함정보다 앞에 있다

    def rank(region_id: str) -> tuple[int, int]:
        return (-counts[region_id], order.get(region_id, len(order)))

    best = min(counts, key=rank)
    mixed = len(counts) > 1
    if best == KIND_OUTSIDE:
        return CandidateVerdict(candidate, KIND_OUTSIDE, None, mixed, quote_regions=quote_regions)
    return CandidateVerdict(candidate, by_id[best].kind, best, mixed, quote_regions=quote_regions)


# --- 노트 하나 ---


@dataclass(frozen=True)
class MissingCheck:
    experience_id: str
    card_id: int
    slot: str
    kept_blank: bool  # 기록에 없는 칸을 인용 없이 두었나


@dataclass
class NoteScore:
    seeded: list[str] = field(default_factory=list)  # 심어 둔 경험 id
    found: list[str] = field(default_factory=list)
    verdicts: list[CandidateVerdict] = field(default_factory=list)
    missing_checks: list[MissingCheck] = field(default_factory=list)

    @property
    def false_candidates(self) -> list[CandidateVerdict]:
        return [v for v in self.verdicts if v.kind != KIND_EXPERIENCE]

    @property
    def duplicates(self) -> list[CandidateVerdict]:
        return [v for v in self.verdicts if v.duplicate]


def score_note(markdown: str, key: NoteKey | None, candidates: Sequence[Candidate]) -> NoteScore:
    """key가 None이면 경험이 없는 노트."""
    regions = build_regions(markdown, key) if key is not None else None
    score = NoteScore(seeded=[experience.id for experience in key.experiences] if key else [])
    missing_by_id = {experience.id: experience.missing for experience in key.experiences} if key else {}
    for candidate in candidates:
        verdict = judge_candidate(candidate, regions)
        if verdict.kind == KIND_EXPERIENCE and verdict.target is not None:
            if verdict.target in score.found:
                verdict = dataclasses.replace(verdict, duplicate=True)
            else:
                score.found.append(verdict.target)
            by_slot = {item.slot: item for item in candidate.fields}
            for slot in missing_by_id.get(verdict.target, ()):
                score.missing_checks.append(
                    MissingCheck(verdict.target, candidate.card_id, slot, kept_blank=by_slot[slot].quote is None)
                )
        score.verdicts.append(verdict)
    return score


def load_candidates(db: Session, *, user_id: int, note_id: int) -> list[Candidate]:
    """이 노트에서 찾은 후보 카드(찾은 순서). 칸은 CARD_SLOTS 순서로."""
    cards = db.scalars(
        select(Card)
        .where(Card.user_id == user_id, Card.note_id == note_id)
        .options(selectinload(Card.fields))
        .order_by(Card.id)
    ).all()
    candidates = []
    for card in cards:
        by_slot = {item.slot: item for item in card.fields}
        candidates.append(
            Candidate(
                card_id=card.id,
                title=card.title,
                fields=tuple(
                    CandidateField(slot, by_slot[slot].quote, by_slot[slot].quote_start, by_slot[slot].question)
                    for slot in CARD_SLOTS
                    if slot in by_slot
                ),
            )
        )
    return candidates


@dataclass
class NoteEvalResult:
    file_name: str
    note_title: str
    has_experience: bool
    chunks_sent: int = 0
    quoted_fields: int = 0  # 남긴 후보에서 인용이 들어간 칸
    emptied_fields: int = 0  # AI가 인용을 줬지만 검사에서 빈칸으로 돌린 칸(버린 후보 포함)
    drop_reasons: dict[str, int] = field(default_factory=dict)
    error: str | None = None  # 후보 찾기 실패(오류 종류 이름)
    retries: int = 0
    seconds: float = 0.0
    usage: LLMUsage = field(default_factory=LLMUsage)
    score: NoteScore = field(default_factory=NoteScore)


async def evaluate_note(
    db: Session,
    *,
    user_id: int,
    note: Note,
    file_name: str,
    key: NoteKey | None,
    client: LLMClient,
    retries: int = 0,
    retry_wait: float = 60.0,
    sleep=asyncio.sleep,  # noqa: ANN001 — 테스트에서 바꿔 끼움
) -> NoteEvalResult:
    """노트 하나: 실제 서비스 흐름으로 후보를 찾고, 저장된 후보를 정답지와 비교한다. AI 오류는 결과에 적고 넘어간다.

    AI 서버 오류(500 · 연결 안 됨 · 한도)면 retry_wait초 쉬었다가 retries번까지 다시 해 본다(퀴즈 평가와 같음).
    실패한 시도도 서비스와 똑같이 로그 · 사용량을 남기고 선점을 푼 뒤 처음부터 다시 한다.
    """
    result = NoteEvalResult(file_name=file_name, note_title=note.title, has_experience=key is not None)
    if key is not None:
        result.score = NoteScore(seeded=[experience.id for experience in key.experiences])
    retries = max(0, retries)
    for attempt in range(retries + 1):
        try:
            plan = prepare_search(db, user_id=user_id, note_id=note.id)
        except NoChunks:
            result.error = "NoChunks"
            return result
        result.chunks_sent = len(plan.chunks)

        started = time.perf_counter()
        try:
            reply = await request_card_drafts(client, plan.messages)
        except LLMError as exc:
            result.seconds = time.perf_counter() - started
            result.usage = result.usage + exc.usage
            save_failed_search(db, plan, exc)
            if isinstance(exc, RETRYABLE_ERRORS) and attempt < retries:
                result.retries += 1
                await sleep(retry_wait)
                continue
            result.error = type(exc).__name__
            return result
        except BaseException:  # 예상 못 한 오류 · 중단 — 서비스와 같이 정리하고 올린다
            abandon_search(db, plan)
            raise
        result.seconds = time.perf_counter() - started
        result.usage = result.usage + reply.usage
        break

    outcome = save_search(db, plan, reply)
    result.quoted_fields, result.emptied_fields = outcome.quoted_fields, outcome.emptied_fields
    result.drop_reasons = dict(outcome.drop_reasons)
    candidates = load_candidates(db, user_id=user_id, note_id=note.id)
    result.score = score_note(note.content, key, candidates)
    return result


# --- 요약 ---


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def summarize(results: Sequence[NoteEvalResult]) -> dict[str, object]:
    """수치 요약. 비율의 분모가 0이면 None. 실패한 노트의 심은 경험도 분모에 넣는다(못 찾은 것으로)."""
    seeded = sum(len(r.score.seeded) for r in results)
    found = sum(len(r.score.found) for r in results)
    verdicts = [v for r in results for v in r.score.verdicts]
    false_by_kind: Counter[str] = Counter(v.kind for v in verdicts if v.kind != KIND_EXPERIENCE)
    false_by_trap: Counter[str] = Counter(v.target for v in verdicts if v.kind == KIND_TRAP and v.target)
    quoted = sum(r.quoted_fields for r in results)
    emptied = sum(r.emptied_fields for r in results)
    checks = [c for r in results for c in r.score.missing_checks]
    drop_reasons: Counter[str] = Counter()
    for r in results:
        drop_reasons.update(r.drop_reasons)
    usage = sum((r.usage for r in results), LLMUsage())
    seconds = [r.seconds for r in results if r.error is None and r.chunks_sent]
    return {
        "notes": len(results),
        "notes_with_experience": sum(1 for r in results if r.has_experience),
        "chunks_sent": sum(r.chunks_sent for r in results),
        "candidates": len(verdicts),
        "seeded_experiences": seeded,
        "found_experiences": found,
        "found_rate": _rate(found, seeded),
        "missed_experiences": [eid for r in results for eid in r.score.seeded if eid not in r.score.found],
        "false_candidates": sum(false_by_kind.values()),
        "false_candidates_by_kind": dict(false_by_kind),
        "false_candidates_by_trap": dict(false_by_trap),
        "duplicate_candidates": sum(1 for v in verdicts if v.duplicate),
        "mixed_candidates": sum(1 for v in verdicts if v.mixed),
        "quotes_given": quoted + emptied,
        "quotes_emptied": emptied,
        "emptied_rate": _rate(emptied, quoted + emptied),
        "drop_reasons": dict(drop_reasons),
        "missing_slots_checked": len(checks),
        "missing_slots_kept_blank": sum(1 for c in checks if c.kept_blank),
        "missing_kept_blank_rate": _rate(sum(1 for c in checks if c.kept_blank), len(checks)),
        "failures": sum(1 for r in results if r.error is not None),
        "retries": sum(r.retries for r in results),
        "seconds_max": round(max(seconds), 1) if seconds else None,
        "seconds_avg": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "usage": {"calls": usage.calls, "prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens},
    }


def result_to_dict(result: NoteEvalResult) -> dict[str, object]:
    """결과 파일에 남길 노트별 상세. 후보마다 칸 · 인용 · 구간을 남겨 사람이 판정을 검수할 수 있게 한다."""
    return {
        "file": result.file_name,
        "note_title": result.note_title,
        "has_experience": result.has_experience,
        "chunks_sent": result.chunks_sent,
        "error": result.error,
        "retries": result.retries,
        "seconds": round(result.seconds, 1),
        "quoted_fields": result.quoted_fields,
        "emptied_fields": result.emptied_fields,
        "drop_reasons": result.drop_reasons,
        "seeded": result.score.seeded,
        "found": result.score.found,
        "candidates": [
            {
                "card_id": v.candidate.card_id,
                "title": v.candidate.title,
                "verdict": v.kind,
                "target": v.target,
                "mixed": v.mixed,
                "duplicate": v.duplicate,
                "fields": [
                    {
                        "slot": item.slot,
                        "quote": item.quote,
                        "region": v.quote_regions.get(item.slot),
                        "question": item.question,
                    }
                    for item in v.candidate.fields
                ],
            }
            for v in result.score.verdicts
        ],
        "missing_checks": [
            {"experience": c.experience_id, "card_id": c.card_id, "slot": c.slot, "kept_blank": c.kept_blank}
            for c in result.score.missing_checks
        ],
    }
