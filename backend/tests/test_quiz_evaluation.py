"""퀴즈 평가 테스트 (F-004 완료 기준 7) — 실제 AI 없이 채점 응답 읽기 · 집계 · 흐름을 확인한다.

실제 수치는 scripts/quiz_eval.py로 잰다(외부 AI · 키에 기대지 않게 pytest에는 넣지 않음, D-014).
"""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import QuizGenerationLog
from app.llm import LLMRateLimited, LLMUnavailable, MockLLMClient, Message
from app.llm.base import LLMUsage
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user
from app.services.quiz_evaluation import (
    JudgedQuizIn,
    NoteEvalResult,
    PatientClient,
    QuizForJudge,
    QuizVerdict,
    build_judge_messages,
    collect_verdicts,
    evaluate_note,
    mock_judge_responder,
    summarize,
)
from app.services.quiz_generation import mock_quiz_responder

NOTES_DIR = Path(__file__).resolve().parent.parent / "eval" / "quiz" / "notes"


def _quiz(quiz_id: int, *, chunk: str = "원문 조각") -> QuizForJudge:
    return QuizForJudge(
        quiz_id=quiz_id,
        kind="mcq",
        chunk_content=chunk,
        question="질문?",
        choices=["가", "나", "다", "라"],
        answer_index=1,
        explanation="해설",
        quote="인용",
    )


def test_judge_gets_only_the_source_chunk_and_quiz_fields() -> None:
    messages = build_judge_messages("노트 제목", [_quiz(7, chunk="ETag가 같으면 304를 돌려준다.")])

    assert [m.role for m in messages] == ["system", "user"]
    payload = json.loads(messages[1].content)
    assert payload["note_title"] == "노트 제목"
    assert payload["quizzes"] == [
        {
            "quiz_id": 7,
            "source_chunk": "ETag가 같으면 304를 돌려준다.",
            "kind": "mcq",
            "question": "질문?",
            "choices": ["가", "나", "다", "라"],
            "answer_index": 1,
            "answer": "나",
            "explanation": "해설",
        }
    ]


def test_verdicts_follow_sent_order_first_wins_unknown_ignored_missing_is_none() -> None:
    quizzes = [_quiz(1), _quiz(2), _quiz(3)]
    judged = [
        JudgedQuizIn(quiz_id=2, answer_supported=False, explanation_consistent=True, reason=" 원문과 다름 "),
        JudgedQuizIn(quiz_id=1, answer_supported=True, explanation_consistent=True, reason="맞음"),
        JudgedQuizIn(quiz_id=2, answer_supported=True, explanation_consistent=True, reason="두 번째는 무시"),
        JudgedQuizIn(quiz_id=99, answer_supported=True, explanation_consistent=True, reason="보내지 않은 번호"),
    ]

    verdicts = collect_verdicts(quizzes, judged)

    assert [(v.quiz.quiz_id, v.answer_supported, v.reason) for v in verdicts] == [
        (1, True, "맞음"),
        (2, False, "원문과 다름"),
        (3, None, "채점 AI가 이 문제를 판정하지 않았어요."),
    ]


def test_summary_rates_exclude_unjudged_and_handle_empty() -> None:
    first = NoteEvalResult(
        note_title="A",
        chunks_sent=5,
        kept=3,
        dropped=1,
        drop_reasons={"quote_not_found": 1},
        generation_seconds=12.0,
        generation_usage=LLMUsage(calls=1, prompt_tokens=100, completion_tokens=50),
        judge_usage=LLMUsage(calls=1),
        verdicts=[
            QuizVerdict(_quiz(1), True, True, ""),
            QuizVerdict(_quiz(2), False, True, ""),
            QuizVerdict(_quiz(3), None, None, ""),  # 판정 못 받음 → 분모에서 뺌
        ],
    )
    failed = NoteEvalResult(note_title="B", chunks_sent=5, generation_error="LLMUnavailable", generation_seconds=180.0)

    summary = summarize([first, failed])

    assert (summary["produced"], summary["dropped"], summary["drop_rate"]) == (4, 1, 0.25)
    assert (summary["judged"], summary["unjudged"]) == (2, 1)
    assert (summary["answer_match_rate"], summary["explanation_match_rate"]) == (0.5, 1.0)
    assert summary["generation_failures"] == 1
    assert summary["generation_seconds_max"] == 12.0  # 실패한 노트의 시간은 평균 · 최대에서 뺀다
    assert summary["usage"]["generation"] == {"calls": 1, "prompt_tokens": 100, "completion_tokens": 50}
    empty = summarize([])
    assert (empty["drop_rate"], empty["answer_match_rate"], empty["generation_seconds_avg"]) == (None, None, None)


def _note(db: Session, sub: str = "eval-user"):  # noqa: ANN202
    user = get_or_create_google_user(db, GoogleProfile(sub=sub, email=f"{sub}@example.com", name=sub))
    content = (NOTES_DIR / "01-http-cache.md").read_text(encoding="utf-8")
    note = create_note_for_user(db, user_id=user.id, title="HTTP 캐시 정리", content=content, chunks=split_markdown(content))
    return user.id, note


def test_evaluate_note_runs_real_generation_flow_then_judges_kept_quizzes(db_session: Session) -> None:
    user_id, note = _note(db_session)
    generator = MockLLMClient(responder=mock_quiz_responder)
    judge = MockLLMClient(responder=mock_judge_responder)

    result = asyncio.run(evaluate_note(db_session, user_id=user_id, note=note, generator=generator, judge=judge))

    assert (result.chunks_sent, result.kept, result.dropped, result.generation_error) == (5, 5, 0, None)
    assert len(result.verdicts) == 5 and all(v.answer_supported for v in result.verdicts)
    assert all(v.quiz.quote in v.quiz.chunk_content for v in result.verdicts)  # 채점에 근거 조각 원문을 붙여 보냄
    assert len(judge.calls) == 1  # 노트 하나에 채점 1번
    log = db_session.scalars(select(QuizGenerationLog)).one()  # 서비스와 같은 평가 로그가 남는다
    assert (log.kept, log.dropped) == (5, 0)


def test_generation_failure_is_recorded_and_judge_is_not_called(db_session: Session) -> None:
    user_id, note = _note(db_session)
    judge = MockLLMClient(responder=mock_judge_responder)

    result = asyncio.run(
        evaluate_note(
            db_session, user_id=user_id, note=note, generator=MockLLMClient([LLMUnavailable("끊김")] * 3), judge=judge
        )
    )

    assert result.generation_error == "LLMUnavailable"
    assert result.generation_usage.calls >= 1
    assert result.verdicts == [] and judge.calls == []


def test_judge_failure_keeps_quizzes_as_unjudged(db_session: Session) -> None:
    user_id, note = _note(db_session)

    result = asyncio.run(
        evaluate_note(
            db_session,
            user_id=user_id,
            note=note,
            generator=MockLLMClient(responder=mock_quiz_responder),
            judge=MockLLMClient(['{"results": "형식 틀림"}'] * 3),
        )
    )

    assert (result.kept, result.judge_error) == (5, "LLMInvalidOutput")
    assert [v.answer_supported for v in result.verdicts] == [None] * 5
    assert summarize([result])["unjudged"] == 5


@pytest.mark.parametrize("path", sorted(NOTES_DIR.glob("*.md")), ids=lambda p: p.name)
def test_virtual_notes_have_five_quiz_eligible_sections(path: Path) -> None:
    from app.config import QUIZ_MIN_CHUNK_CHARS

    chunks = split_markdown(path.read_text(encoding="utf-8"))
    eligible = [c for c in chunks if len("".join(c.content.split())) >= QUIZ_MIN_CHUNK_CHARS]
    assert len(eligible) == 5


def test_patient_client_waits_on_rate_limit_and_counts_every_call() -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    inner = MockLLMClient([LLMRateLimited("429", retry_after_seconds=7), LLMRateLimited("429"), "답"])
    client = PatientClient(inner, default_wait=30, max_waits=3, sleep=fake_sleep)

    reply = asyncio.run(client.chat([Message("user", "안녕")]))

    assert reply.content == "답"
    assert slept == [7, 30] and client.waits == [7, 30]
    assert reply.usage.calls == 3  # 한도에 걸린 호출 2번 + 성공 1번


def test_patient_client_gives_up_after_max_waits() -> None:
    async def fake_sleep(seconds: float) -> None:
        return None

    client = PatientClient(MockLLMClient([LLMRateLimited("429")] * 3), max_waits=2, sleep=fake_sleep)

    with pytest.raises(LLMRateLimited) as caught:
        asyncio.run(client.chat([Message("user", "안녕")]))
    assert caught.value.usage.calls == 3


def test_retryable_ai_failure_waits_and_tries_the_note_again(db_session: Session) -> None:
    """500(연결 안 됨)이면 쉬었다가 노트를 처음부터 다시 해 본다. 실패한 시도의 사용량도 더한다."""
    user_id, note = _note(db_session, sub="eval-retry")
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    generator = MockLLMClient([LLMUnavailable("500")], responder=mock_quiz_responder)
    result = asyncio.run(
        evaluate_note(
            db_session,
            user_id=user_id,
            note=note,
            generator=generator,
            judge=MockLLMClient(responder=mock_judge_responder),
            retries=2,
            retry_wait=60,
            sleep=fake_sleep,
        )
    )

    assert (result.generation_error, result.kept, result.retries) == (None, 5, 1)
    assert slept == [60]
    assert result.generation_usage.calls == 2  # 실패한 1번 + 성공한 1번


def test_non_retryable_failure_is_not_tried_again(db_session: Session) -> None:
    user_id, note = _note(db_session, sub="eval-noretry")

    async def fake_sleep(seconds: float) -> None:
        raise AssertionError("쉬면 안 된다")

    result = asyncio.run(
        evaluate_note(
            db_session,
            user_id=user_id,
            note=note,
            generator=MockLLMClient(['{"quizzes": "형식 틀림"}'] * 3),
            judge=MockLLMClient(responder=mock_judge_responder),
            retries=2,
            sleep=fake_sleep,
        )
    )

    assert (result.generation_error, result.retries) == ("LLMInvalidOutput", 0)


def test_patient_client_keeps_a_minimum_interval_between_calls() -> None:
    now = [100.0]
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    client = PatientClient(MockLLMClient(["a", "b"]), min_interval=20, sleep=fake_sleep, clock=lambda: now[0])

    asyncio.run(client.chat([Message("user", "1")]))
    now[0] += 5  # 5초 뒤 다음 호출
    asyncio.run(client.chat([Message("user", "2")]))

    assert slept == [15]  # 첫 호출은 바로, 두 번째는 남은 15초를 쉬고
