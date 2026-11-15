"""평가 스크립트가 같이 쓰는 AI 한 단계 부르기 (F-007 공고 분석 평가 · F-008 자소서 초안 평가, T-006).

한 단계 = 선점(prepare) → AI(request). AI 서버 오류(500 · 429)면 서비스처럼 실패로 정리(save_failed)한 뒤
policy대로 쉬고 처음부터 다시 한다. 예상 못 한 오류 · 중단은 abandon으로 정리하고 올린다(선점 · 사용량).
서비스 코드는 이 함수를 쓰지 않는다 — 서비스는 실패를 바로 알리고(원칙 4), 평가는 느려도 끝까지 가는 게 낫다.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.llm.base import LLMError, LLMRateLimited, LLMUnavailable, LLMUsage

# 평가 중 AI 서버 오류(500 · 연결 안 됨 · 한도)면 쉬었다가 다시 해 본다 — 퀴즈 · 카드 · 공고 · 자소서 평가가 같이 쓴다
RETRYABLE_ERRORS = (LLMUnavailable, LLMRateLimited)

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class RetryPolicy:
    """AI 서버 오류(500 · 429)면 단계마다 몇 번 더 해 볼지 · 얼마나 쉴지(T-006). sleep은 테스트에서 바꿔 끼운다."""

    retries: int = 0
    wait: float = 60.0
    sleep: Sleep = asyncio.sleep


@dataclass
class StepOutcome[PlanT, ReplyT]:
    plan: PlanT  # 마지막 계획(다시 했으면 마지막 시도의 것)
    reply: ReplyT | None = None  # None이면 AI를 안 불렀거나(needs_ai가 False) 실패
    error: LLMError | None = None  # 실패면 마지막 오류(다시 해 볼 수 없는 오류이거나 횟수를 다 씀)
    seconds: float | None = None  # 마지막 AI 호출 시간. None이면 AI를 부르지 않음
    usage: LLMUsage = field(default_factory=LLMUsage)  # 모든 시도를 합친 사용량
    retries: int = 0


async def run_ai_step[PlanT, ReplyT](
    *,
    prepare: Callable[[], PlanT],
    request: Callable[[PlanT], Awaitable[ReplyT]],
    save_failed: Callable[[PlanT, LLMError], object],
    abandon: Callable[[PlanT], object],
    policy: RetryPolicy,
    needs_ai: Callable[[PlanT], bool] = lambda plan: True,
    usage_of: Callable[[ReplyT], LLMUsage],
) -> StepOutcome[PlanT, ReplyT]:
    left = max(0, policy.retries)
    usage = LLMUsage()
    retries = 0
    while True:
        plan = prepare()
        if not needs_ai(plan):
            return StepOutcome(plan=plan, usage=usage, retries=retries)
        started = time.perf_counter()
        try:
            reply = await request(plan)
        except LLMError as exc:
            seconds = time.perf_counter() - started
            usage = usage + exc.usage
            save_failed(plan, exc)
            if isinstance(exc, RETRYABLE_ERRORS) and left > 0:
                left -= 1
                retries += 1
                await policy.sleep(policy.wait)
                continue
            return StepOutcome(plan=plan, error=exc, seconds=seconds, usage=usage, retries=retries)
        except BaseException:
            abandon(plan)
            raise
        seconds = time.perf_counter() - started
        return StepOutcome(
            plan=plan, reply=reply, seconds=seconds, usage=usage + usage_of(reply), retries=retries
        )
