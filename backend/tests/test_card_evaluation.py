"""경험 카드 평가 테스트 (F-006 완료 기준 7) — 실제 AI 없이 구간 판정 · 집계 · 흐름을 확인한다.

실제 수치는 scripts/card_eval.py로 잰다(외부 AI · 키에 기대지 않게 pytest에는 넣지 않음, D-014).
"""

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CardGenerationLog
from app.llm import LLMUnavailable, MockLLMClient, Message
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.card_evaluation import (
    KIND_EXPERIENCE,
    KIND_NO_EXPERIENCE_NOTE,
    KIND_OUTSIDE,
    KIND_TRAP,
    Candidate,
    CandidateField,
    ExperienceKey,
    NoteKey,
    TrapKey,
    build_regions,
    evaluate_note,
    judge_candidate,
    parse_answer_key,
    score_note,
    section_spans,
    summarize,
)
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval" / "cards"

NOTE = """# 회고

## 경험 A
상황 A 문장이 여기 있다.

### 결과
결과 A 문장이 여기 있다.

## 개념
개념 설명 문장이 여기 있다.

## 경험 B
상황 B 문장이 여기 있다.
"""

KEY = NoteKey(
    experiences=(
        ExperienceKey("a", ("경험 A",), missing=("task",)),
        ExperienceKey("b", ("경험 B",)),
    ),
    traps=(TrapKey("개념", "concept"),),
)


def _candidate(card_id: int, **quotes: str) -> Candidate:
    """칸 이름=인용 문장 → NOTE 안의 위치를 찾아 후보를 만든다. 주지 않은 칸은 빈칸."""
    fields = []
    for slot in ("situation", "task", "action", "result"):
        text = quotes.get(slot)
        start = NOTE.index(text) if text is not None else None
        fields.append(CandidateField(slot, text, start, None if text else "질문?"))
    return Candidate(card_id=card_id, title=f"후보 {card_id}", fields=tuple(fields))


def test_section_spans_include_subheadings_and_stop_at_next_section() -> None:
    spans = section_spans(NOTE)

    assert list(spans) == ["경험 A", "개념", "경험 B"]
    start, end = spans["경험 A"]
    assert "결과 A 문장" in NOTE[start:end]  # '###' 소제목은 구간 안
    assert "개념 설명" not in NOTE[start:end]
    assert spans["경험 B"][1] == len(NOTE)


def test_build_regions_stops_on_unknown_section() -> None:
    with pytest.raises(ValueError, match="없는 구간"):
        build_regions(NOTE, NoteKey(experiences=(ExperienceKey("x", ("없는 구간",)),)))


def test_parse_answer_key_rejects_unknown_slot() -> None:
    raw = {"notes": {"n.md": {"experiences": [{"id": "x", "sections": ["경험 A"], "missing": ["결과"]}]}}}
    with pytest.raises(ValueError, match="모르는 칸"):
        parse_answer_key(raw)


def test_candidate_goes_to_region_with_most_quotes() -> None:
    regions = build_regions(NOTE, KEY)

    in_a = judge_candidate(_candidate(1, situation="상황 A 문장", result="결과 A 문장"), regions)
    in_trap = judge_candidate(
        _candidate(2, situation="개념 설명 문장", action="개념 설명 문장이", result="상황 B 문장"), regions
    )

    assert (in_a.kind, in_a.target, in_a.mixed) == (KIND_EXPERIENCE, "a", False)
    assert (in_trap.kind, in_trap.target, in_trap.mixed) == (KIND_TRAP, "trap:개념", True)
    assert in_trap.quote_regions == {"situation": "trap:개념", "action": "trap:개념", "result": "b"}


def test_tie_prefers_experience_and_marks_mixed() -> None:
    verdict = judge_candidate(_candidate(1, situation="개념 설명 문장", result="상황 B 문장"), build_regions(NOTE, KEY))

    assert (verdict.kind, verdict.target, verdict.mixed) == (KIND_EXPERIENCE, "b", True)


def test_quote_outside_every_region_and_no_experience_note() -> None:
    outside = judge_candidate(_candidate(1, situation="# 회고"), build_regions(NOTE, KEY))
    none_note = judge_candidate(_candidate(2, situation="상황 A 문장"), None)

    assert (outside.kind, outside.target) == (KIND_OUTSIDE, None)
    assert none_note.kind == KIND_NO_EXPERIENCE_NOTE


def test_score_note_counts_found_duplicates_false_and_missing_slots() -> None:
    candidates = [
        _candidate(1, situation="상황 A 문장", task="결과 A 문장"),  # 빠진 칸(task)에 인용을 넣음
        _candidate(2, situation="상황 A 문장이"),  # 같은 경험 두 번째 → 중복, task는 빈칸
        _candidate(3, situation="개념 설명 문장"),  # 함정
    ]

    score = score_note(NOTE, KEY, candidates)

    assert score.seeded == ["a", "b"]
    assert score.found == ["a"]
    assert [v.candidate.card_id for v in score.duplicates] == [2]
    assert [v.candidate.card_id for v in score.false_candidates] == [3]
    assert [(c.card_id, c.slot, c.kept_blank) for c in score.missing_checks] == [(1, "task", False), (2, "task", True)]


def test_score_note_without_key_counts_every_candidate_as_false() -> None:
    score = score_note(NOTE, None, [_candidate(1, situation="상황 A 문장")])

    assert score.seeded == [] and score.found == []
    assert len(score.false_candidates) == 1


def test_answer_key_matches_eval_notes() -> None:
    """레포의 정답지와 가상 노트가 맞는지 — 제목 오타 · 노트 추가 누락을 평가 전에 잡는다."""
    keys = parse_answer_key(json.loads((EVAL_DIR / "answers.json").read_text(encoding="utf-8")))
    paths = sorted((EVAL_DIR / "notes").glob("*.md"))

    assert {path.name for path in paths} == set(keys)
    for path in paths:
        regions = build_regions(path.read_text(encoding="utf-8"), keys[path.name])
        assert regions, path.name
    assert sum(len(key.experiences) for key in keys.values()) == 12


# --- 서비스 흐름 그대로 (mock AI) ---


def _quoting_responder(cards: Sequence[dict[str, str]]):  # noqa: ANN202
    """보낸 조각에서 문장을 찾아 그 조각 번호로 인용하는 가짜 AI. 칸 이름=문장."""

    def respond(messages: Sequence[Message]) -> str:
        payload = json.loads(messages[-1].content)
        out = []
        for card in cards:
            drafted: dict[str, object] = {"title": card.get("title", "경험")}
            for slot in ("situation", "task", "action", "result"):
                text = card.get(slot)
                # 원문에 없는 문장은 첫 조각 번호를 붙인다(지어낸 인용 — 검사에서 quote_not_found로 떨어져야 함)
                chunk_id = next(
                    (c["chunk_id"] for c in payload["chunks"] if text and text in c["content"]),
                    payload["chunks"][0]["chunk_id"],
                )
                drafted[slot] = (
                    {"chunk_id": chunk_id, "quote": text, "question": None}
                    if text
                    else {"chunk_id": None, "quote": None, "question": "무엇을 했나요?"}
                )
            out.append(drafted)
        return json.dumps({"cards": out}, ensure_ascii=False)

    return respond


def _note(db: Session):  # noqa: ANN202
    user = get_or_create_google_user(db, GoogleProfile(sub="card-eval-test", email="e@example.invalid", name="평가"))
    note = create_note_for_user(db, user_id=user.id, title="회고", content=NOTE, chunks=split_markdown(NOTE))
    return user.id, note


def test_evaluate_note_runs_real_search_flow_then_scores(db_session: Session) -> None:
    user_id, note = _note(db_session)
    client = MockLLMClient(
        responder=_quoting_responder(
            [
                {"situation": "상황 A 문장이 여기 있다.", "result": "결과 A 문장이 여기 있다."},
                {"situation": "개념 설명 문장이 여기 있다."},
                {"situation": "지어낸 문장이 여기 있다."},  # 원문에 없음 → 빈칸 → 인용 0개라 후보를 버림
            ]
        )
    )

    result = asyncio.run(
        evaluate_note(db_session, user_id=user_id, note=note, file_name="n.md", key=KEY, client=client)
    )

    assert result.error is None
    assert result.score.found == ["a"]
    assert [v.kind for v in result.score.verdicts] == [KIND_EXPERIENCE, KIND_TRAP]
    assert (result.quoted_fields, result.emptied_fields) == (3, 1)
    assert result.drop_reasons == {"quote_not_found": 1, "no_quote": 1}
    log = db_session.scalars(select(CardGenerationLog)).one()  # 서비스와 같은 평가 로그가 남는다
    assert (log.candidates, log.quoted_fields, log.emptied_fields) == (2, 3, 1)

    summary = summarize([result])
    assert (summary["found_rate"], summary["false_candidates"], summary["emptied_rate"]) == (0.5, 1, 0.25)
    assert summary["missed_experiences"] == ["b"]
    assert (summary["missing_slots_checked"], summary["missing_slots_kept_blank"]) == (1, 1)


def test_evaluate_note_retries_server_errors_then_records_failure(db_session: Session) -> None:
    user_id, note = _note(db_session)
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    client = MockLLMClient([LLMUnavailable("끊김")] * 6)
    result = asyncio.run(
        evaluate_note(
            db_session,
            user_id=user_id,
            note=note,
            file_name="n.md",
            key=KEY,
            client=client,
            retries=1,
            retry_wait=5,
            sleep=fake_sleep,
        )
    )

    assert result.error == "LLMUnavailable"
    assert (result.retries, waits) == (1, [5])
    assert result.score.seeded == ["a", "b"] and result.score.found == []  # 실패해도 분모에 들어간다
    assert summarize([result])["found_rate"] == 0.0
