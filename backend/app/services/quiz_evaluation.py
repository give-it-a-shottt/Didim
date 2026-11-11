"""퀴즈 평가 (F-004 완료 기준 7, D-005 — 정답을 미리 심어 둔 가상 노트).

재는 것
- 버려진 문제 비율: AI가 낸 문제 중 내용 검사(근거 인용이 원문에 글자 그대로 있는지 등)에서 버린 비율.
- 정답 일치율: 남은 문제 중 '원문 조각만으로 정답이 맞다고 확인되는' 비율.
- 해설 일치율: 남은 문제 중 '해설이 원문과 어긋나지 않는' 비율.

정답 · 해설 판정은 채점 AI가 한다(사용자 선택 2026-11-11 — 비용이 크면 '심은 핵심값 자동 비교'로 바꾼다).
채점 AI에는 원문 조각과 문제 · 보기 · 정답 · 해설만 보내고(원칙 6), 정해진 JSON 모양으로 받는다(원칙 3).
채점 AI도 틀릴 수 있어서, 결과 파일에 문제마다 판정 이유를 남겨 사람이 골라 확인할 수 있게 한다.

문제 만들기는 실제 서비스와 같은 함수(prepare_generation → request_quiz_drafts → save_generation)를 그대로 쓴다.
평가용 DB(scripts/quiz_eval.py의 임시 SQLite)에서 돌리므로 개발 DB · 내 계정은 건드리지 않는다.
"""

import asyncio
import dataclasses
import json
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Note, Quiz
from app.llm.base import LLMClient, LLMError, LLMRateLimited, LLMReply, LLMUnavailable, LLMUsage, Message
from app.llm.structured import complete_json
from app.services.quiz_generation import (
    NoEligibleChunks,
    prepare_generation,
    request_quiz_drafts,
    save_failed_generation,
    save_generation,
)

JUDGE_SYSTEM_PROMPT = """너는 복습 문제 검수자다. 문제마다 함께 준 '원문 조각'만 근거로 판단한다.
일반 상식이나 원문 밖의 지식으로 판단하지 않는다. 원문 내용이 사실인지는 따지지 않는다.

- answer_supported: 원문 조각만 읽고 정답 보기가 맞다고 확인되고, 나머지 보기는 원문에 비춰 틀리면 true.
  원문으로 정답을 확인할 수 없거나, 다른 보기도 원문상 맞을 수 있거나, 정답 보기가 원문과 어긋나면 false.
  OX 문제는 문제 문장이 원문에 비춰 참이면 정답이 O, 거짓이면 X여야 true다.
- explanation_consistent: 해설이 원문과 어긋나는 내용이나 원문에 없는 주장을 담고 있지 않으면 true.
- reason: 판단 이유를 한국어 한두 문장으로.

받은 모든 quiz_id에 대해 결과를 하나씩 낸다."""


DEFAULT_RATE_LIMIT_WAIT_SECONDS = 30.0  # 429에 대기 시간(Retry-After)이 없을 때
MAX_RATE_LIMIT_WAITS = 3
# 평가 중 AI 서버 오류(500 · 연결 안 됨 · 한도)면 노트 단위로 쉬었다가 다시 해 본다(서비스 코드에는 없음)
RETRYABLE_ERRORS = (LLMUnavailable, LLMRateLimited)


class PatientClient:
    """평가 전용 AI 클라이언트 감싸개. 서비스 코드는 429에 바로 알리지만(원칙 4), 평가는 느려도 끝까지 가는 게 낫다.

    - 호출 사이 최소 간격(min_interval): 무료 API는 짧은 간격으로 이어 부르면 막는 것 같아(2026-11-11, 사용자) 쉬었다 부른다.
    - 429(사용량 한도)면 서버가 알려 준 시간(없으면 30초) 기다렸다가 다시 부른다.
    기다린 호출도 사용량에 더해 돌려준다(적게 세지 않게).
    """

    def __init__(
        self,
        inner: LLMClient,
        *,
        min_interval: float = 0.0,
        default_wait: float = DEFAULT_RATE_LIMIT_WAIT_SECONDS,
        max_waits: int = MAX_RATE_LIMIT_WAITS,
        sleep=asyncio.sleep,  # noqa: ANN001 — 테스트에서 바꿔 끼움
        clock=time.monotonic,  # noqa: ANN001
    ) -> None:
        self._inner = inner
        self._min_interval = min_interval
        self._default_wait = default_wait
        self._max_waits = max_waits
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None
        self.waits: list[float] = []  # 429로 기다린 시간 기록(결과 보고용)

    async def _keep_interval(self) -> None:
        if self._last_call is not None:
            gap = self._min_interval - (self._clock() - self._last_call)
            if gap > 0:
                await self._sleep(gap)
        self._last_call = self._clock()

    async def chat(self, messages: Sequence[Message]) -> LLMReply:
        spent = LLMUsage()
        for attempt in range(self._max_waits + 1):
            await self._keep_interval()
            try:
                reply = await self._inner.chat(messages)
            except LLMRateLimited as exc:
                spent = spent + exc.usage
                if attempt == self._max_waits:
                    exc.usage = spent
                    raise
                wait = exc.retry_after_seconds or self._default_wait
                self.waits.append(wait)
                await self._sleep(wait)
                continue
            return dataclasses.replace(reply, usage=spent + reply.usage)
        raise AssertionError("unreachable")


class JudgedQuizIn(BaseModel):
    """채점 AI가 문제 하나에 대해 돌려주는 판정."""

    quiz_id: int = Field(description="판정한 문제 번호(보낸 quizzes의 quiz_id 중 하나)")
    answer_supported: bool = Field(description="원문 조각만으로 정답 보기가 맞다고 확인되면 true")
    explanation_consistent: bool = Field(description="해설이 원문과 어긋나지 않고 원문에 없는 주장이 없으면 true")
    reason: str = Field(description="판단 이유(한국어 한두 문장)")


class JudgeBatchIn(BaseModel):
    results: list[JudgedQuizIn]


@dataclass(frozen=True)
class QuizForJudge:
    quiz_id: int
    kind: str
    chunk_content: str  # 근거 조각 원문
    question: str
    choices: list[str]
    answer_index: int
    explanation: str
    quote: str


@dataclass(frozen=True)
class QuizVerdict:
    """판정 결과. 채점 AI가 이 문제를 빼먹었거나 채점 호출이 실패하면 두 값이 None(판정 못 받음)."""

    quiz: QuizForJudge
    answer_supported: bool | None
    explanation_consistent: bool | None
    reason: str


def build_judge_messages(note_title: str, quizzes: Sequence[QuizForJudge]) -> list[Message]:
    """문제마다 근거 조각 원문과 문제 · 보기 · 정답 · 해설만 보낸다(원칙 6). 인용 문장은 조각 안에 있어서 따로 보내지 않는다."""
    payload = {
        "note_title": note_title,
        "quizzes": [
            {
                "quiz_id": quiz.quiz_id,
                "source_chunk": quiz.chunk_content,
                "kind": quiz.kind,
                "question": quiz.question,
                "choices": quiz.choices,
                "answer_index": quiz.answer_index,
                "answer": quiz.choices[quiz.answer_index] if 0 <= quiz.answer_index < len(quiz.choices) else "",
                "explanation": quiz.explanation,
            }
            for quiz in quizzes
        ],
    }
    return [
        Message("system", JUDGE_SYSTEM_PROMPT),
        Message("user", json.dumps(payload, ensure_ascii=False)),
    ]


def collect_verdicts(quizzes: Sequence[QuizForJudge], judged: Sequence[JudgedQuizIn]) -> list[QuizVerdict]:
    """보낸 문제 순서대로 판정을 짝짓는다. 같은 번호가 두 번이면 처음 것, 보내지 않은 번호는 무시, 빠진 문제는 None."""
    first: dict[int, JudgedQuizIn] = {}
    for item in judged:
        first.setdefault(item.quiz_id, item)
    verdicts = []
    for quiz in quizzes:
        item = first.get(quiz.quiz_id)
        if item is None:
            verdicts.append(QuizVerdict(quiz, None, None, "채점 AI가 이 문제를 판정하지 않았어요."))
        else:
            verdicts.append(QuizVerdict(quiz, item.answer_supported, item.explanation_consistent, item.reason.strip()))
    return verdicts


def load_quizzes_for_judge(db: Session, *, user_id: int, note_id: int) -> list[QuizForJudge]:
    rows = db.execute(
        select(Quiz, Chunk.content)
        .join(Chunk, Chunk.id == Quiz.chunk_id)
        .where(Quiz.user_id == user_id, Quiz.note_id == note_id, Chunk.user_id == user_id)
        .order_by(Chunk.position)
    ).all()
    return [
        QuizForJudge(
            quiz_id=quiz.id,
            kind=quiz.kind,
            chunk_content=content,
            question=quiz.question,
            choices=list(quiz.choices),
            answer_index=quiz.answer_index,
            explanation=quiz.explanation,
            quote=quiz.quote,
        )
        for quiz, content in rows
    ]


@dataclass
class NoteEvalResult:
    note_title: str
    chunks_sent: int = 0
    kept: int = 0
    dropped: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    generation_error: str | None = None  # 문제 만들기 실패(오류 종류 이름)
    retries: int = 0  # AI 서버 오류로 쉬었다가 다시 해 본 횟수(문제 만들기 + 채점)
    generation_seconds: float = 0.0  # 문제 만들기 AI 호출에 걸린 시간(형식 재시도 포함)
    generation_usage: LLMUsage = field(default_factory=LLMUsage)
    judge_error: str | None = None
    judge_usage: LLMUsage = field(default_factory=LLMUsage)
    verdicts: list[QuizVerdict] = field(default_factory=list)


async def evaluate_note(
    db: Session,
    *,
    user_id: int,
    note: Note,
    generator: LLMClient,
    judge: LLMClient,
    retries: int = 0,
    retry_wait: float = 60.0,
    sleep=asyncio.sleep,  # noqa: ANN001 — 테스트에서 바꿔 끼움
) -> NoteEvalResult:
    """노트 하나: 실제 서비스 흐름으로 문제를 만들고, 남은 문제를 채점 AI로 판정한다. AI 오류는 결과에 적고 넘어간다.

    AI 서버 오류(500 · 연결 안 됨 · 한도)면 retry_wait초 쉬었다가 retries번까지 다시 해 본다. 쉬는 시간은 AI 호출의
    전체 시간 상한(180초) 밖이다 — 실패한 시도도 서비스와 똑같이 로그 · 사용량을 남기고 선점을 푼 뒤 처음부터 다시 한다.
    """
    result = NoteEvalResult(note_title=note.title)
    for attempt in range(retries + 1):
        try:
            plan = prepare_generation(db, user_id=user_id, note_id=note.id)
        except NoEligibleChunks:
            result.generation_error = "NoEligibleChunks"
            return result
        result.chunks_sent = len(plan.chunks)

        started = time.perf_counter()
        try:
            reply = await request_quiz_drafts(generator, plan.messages)
        except LLMError as exc:
            result.generation_seconds = time.perf_counter() - started
            result.generation_usage = result.generation_usage + exc.usage
            save_failed_generation(db, plan, exc)
            if isinstance(exc, RETRYABLE_ERRORS) and attempt < retries:
                result.retries += 1
                await sleep(retry_wait)
                continue
            result.generation_error = type(exc).__name__
            return result
        result.generation_seconds = time.perf_counter() - started
        result.generation_usage = result.generation_usage + reply.usage
        break

    outcome = save_generation(db, plan, reply)
    result.kept, result.dropped, result.drop_reasons = outcome.kept, outcome.dropped, dict(outcome.drop_reasons)

    quizzes = load_quizzes_for_judge(db, user_id=user_id, note_id=note.id)
    if not quizzes:
        return result
    messages = build_judge_messages(note.title, quizzes)
    for attempt in range(retries + 1):
        try:
            judged = await complete_json(judge, messages, JudgeBatchIn)
        except LLMError as exc:
            result.judge_usage = result.judge_usage + exc.usage
            if isinstance(exc, RETRYABLE_ERRORS) and attempt < retries:
                result.retries += 1
                await sleep(retry_wait)
                continue
            result.judge_error = type(exc).__name__
            result.verdicts = [QuizVerdict(quiz, None, None, "채점 호출이 실패했어요.") for quiz in quizzes]
            return result
        break
    result.judge_usage = result.judge_usage + judged.usage
    result.verdicts = collect_verdicts(quizzes, judged.value.results)
    return result


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def summarize(results: Sequence[NoteEvalResult]) -> dict[str, object]:
    """수치 요약. 비율의 분모가 0이면 None. 판정 못 받은 문제는 일치율 분모에서 빼고 따로 센다."""
    kept = sum(r.kept for r in results)
    dropped = sum(r.dropped for r in results)
    produced = kept + dropped  # AI가 낸 문제 수
    verdicts = [v for r in results for v in r.verdicts]
    judged = [v for v in verdicts if v.answer_supported is not None]
    answer_ok = sum(1 for v in judged if v.answer_supported)
    explanation_ok = sum(1 for v in judged if v.explanation_consistent)
    drop_reasons: Counter[str] = Counter()
    for r in results:
        drop_reasons.update(r.drop_reasons)
    generation_usage = sum((r.generation_usage for r in results), LLMUsage())
    judge_usage = sum((r.judge_usage for r in results), LLMUsage())
    seconds = [r.generation_seconds for r in results if r.generation_error is None and r.chunks_sent]
    return {
        "notes": len(results),
        "chunks_sent": sum(r.chunks_sent for r in results),
        "produced": produced,
        "kept": kept,
        "dropped": dropped,
        "drop_rate": _rate(dropped, produced),
        "drop_reasons": dict(drop_reasons),
        "judged": len(judged),
        "unjudged": len(verdicts) - len(judged),
        "answer_match_rate": _rate(answer_ok, len(judged)),
        "explanation_match_rate": _rate(explanation_ok, len(judged)),
        "generation_failures": sum(1 for r in results if r.generation_error is not None),
        "retries": sum(r.retries for r in results),
        "judge_failures": sum(1 for r in results if r.judge_error is not None),
        "generation_seconds_max": round(max(seconds), 1) if seconds else None,
        "generation_seconds_avg": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "usage": {
            "generation": {"calls": generation_usage.calls, "prompt_tokens": generation_usage.prompt_tokens, "completion_tokens": generation_usage.completion_tokens},
            "judge": {"calls": judge_usage.calls, "prompt_tokens": judge_usage.prompt_tokens, "completion_tokens": judge_usage.completion_tokens},
        },
    }


def result_to_dict(result: NoteEvalResult) -> dict[str, object]:
    """결과 파일에 남길 노트별 상세. 문제마다 판정 이유를 남겨 사람이 채점 AI를 검수할 수 있게 한다."""
    return {
        "note_title": result.note_title,
        "chunks_sent": result.chunks_sent,
        "kept": result.kept,
        "dropped": result.dropped,
        "drop_reasons": result.drop_reasons,
        "generation_error": result.generation_error,
        "generation_seconds": round(result.generation_seconds, 1),
        "retries": result.retries,
        "judge_error": result.judge_error,
        "quizzes": [
            {
                "kind": v.quiz.kind,
                "question": v.quiz.question,
                "choices": v.quiz.choices,
                "answer_index": v.quiz.answer_index,
                "explanation": v.quiz.explanation,
                "quote": v.quiz.quote,
                "answer_supported": v.answer_supported,
                "explanation_consistent": v.explanation_consistent,
                "reason": v.reason,
            }
            for v in result.verdicts
        ],
    }


def mock_judge_responder(messages: Sequence[Message]) -> str:
    """흐름 확인용 가짜 채점(모든 문제를 맞음으로). 수치에는 뜻이 없다 — scripts/quiz_eval.py --allow-mock · 테스트용."""
    user_messages = [message for message in messages if message.role == "user"]
    try:
        payload = json.loads(user_messages[0].content) if user_messages else {}
    except json.JSONDecodeError:
        payload = {}
    results = [
        {"quiz_id": quiz.get("quiz_id"), "answer_supported": True, "explanation_consistent": True, "reason": "(mock)"}
        for quiz in payload.get("quizzes", [])
    ]
    return json.dumps({"results": results}, ensure_ascii=False)
