"""AI 사용량 확인 · 기록 (D-018, 설계 원칙 4).

AI를 부르는 기능(퀴즈 · 카드 후보 · 자소서 · 면접)은 모두 이 순서를 따른다.
1. ensure_within_daily_limit — 부르기 전에 오늘 쓴 호출 수가 상한보다 적은지 확인. 다 썼으면 DailyLimitExceeded.
2. AI를 부른다(F-014 LLM 클라이언트). 성공 · 실패 모두 usage(실제 호출 수 · 토큰)가 붙어 온다.
3. record_usage — 실제 사용량을 한 줄 기록(성공 · 실패 모두).

확인과 기록 사이(AI를 부르는 최대 180초)에는 DB를 잠그지 않는다. 그래서 동시 요청 · 재시도로 상한을 조금
넘을 수 있다(D-018에서 받아들인 제약, 사용자 확인).
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AIUsageLog, User
from app.korea_time import korea_day_start_utc, korea_today, now_utc
from app.llm.base import (
    LLMConfigError,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMRequestError,
    LLMUnavailable,
    LLMUsage,
)

logger = logging.getLogger(__name__)

# 기능 이름(ai_usage_logs.feature). 사용량 화면(7주차)에서 기능별로 나눠 보여 준다.
FEATURE_QUIZ_GENERATE = "quiz_generate"
FEATURE_CARD_FIND = "card_find"  # 경험 카드 후보 찾기(F-006)
FEATURE_POSTING_EXTRACT = "posting_extract"  # 공고 요구 역량 뽑기(F-007 ①)
FEATURE_POSTING_MATCH = "posting_match"  # 요구 역량 ↔ 경험 카드 매칭(F-007 ②)

OUTCOME_OK = "ok"
OUTCOME_ERROR = "error"  # LLMError 공통 부모 · 예상 못 한 오류(요청 취소 등)
OUTCOME_SAVE_FAILED = "save_failed"  # AI는 불렀는데 문제 저장(DB)이 실패


@dataclass(frozen=True)
class DailyUsage:
    used: int  # 오늘(한국 시간 0시부터) 쓴 실제 호출 수
    limit: int

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)


class DailyLimitExceeded(Exception):
    """오늘 AI 호출 상한을 다 썼다. AI를 부르지 않고 남은 사용량(0)과 다시 쓸 수 있는 때를 안내한다."""

    def __init__(self, usage: DailyUsage) -> None:
        super().__init__(f"오늘 AI 사용량을 다 썼어요({usage.used}/{usage.limit}).")
        self.usage = usage


def daily_usage(db: Session, *, user_id: int, now: datetime | None = None) -> DailyUsage:
    """오늘 쓴 호출 수와 상한. 사용자 조건을 항상 건다(D-004)."""
    since = korea_day_start_utc(korea_today(now))
    used = db.scalar(
        select(func.coalesce(func.sum(AIUsageLog.calls), 0)).where(
            AIUsageLog.user_id == user_id,
            AIUsageLog.created_at >= since,
        )
    )
    limit = db.scalar(select(User.daily_limit).where(User.id == user_id))
    if limit is None:
        raise LookupError("사용자를 찾지 못했어요.")
    return DailyUsage(used=int(used or 0), limit=int(limit))


def ensure_within_daily_limit(db: Session, *, user_id: int, now: datetime | None = None) -> DailyUsage:
    """AI를 부르기 전에 호출한다. 남은 양이 1 이상이면 그대로 돌려주고, 없으면 DailyLimitExceeded."""
    usage = daily_usage(db, user_id=user_id, now=now)
    if usage.remaining <= 0:
        raise DailyLimitExceeded(usage)
    return usage


def outcome_for(error: LLMError | None) -> str:
    """AI 호출 결과를 기록용 이름으로. 오류 문구 · 내용은 넣지 않고 종류만."""
    if error is None:
        return OUTCOME_OK
    if isinstance(error, LLMInvalidOutput):
        return "invalid_output"
    if isinstance(error, LLMRateLimited):
        return "rate_limited"
    if isinstance(error, LLMUnavailable):
        return "unavailable"
    if isinstance(error, LLMConfigError):
        return "config_error"
    if isinstance(error, LLMRequestError):
        return "request_error"
    return OUTCOME_ERROR


def record_usage(
    db: Session,
    *,
    user_id: int,
    feature: str,
    usage: LLMUsage,
    outcome: str,
    now: datetime | None = None,
) -> bool:
    """실제 사용량을 한 줄 기록하고 커밋한다. 저장에 실패하면 되돌리고 False(부른 기능의 결과는 그대로 돌려줌).

    호출이 0번이면(부르기 전에 막힘) 기록하지 않는다.
    """
    if usage.calls <= 0:
        return True
    db.add(
        AIUsageLog(
            user_id=user_id,
            feature=feature,
            calls=usage.calls,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            outcome=outcome,
            created_at=now if now is not None else now_utc(),
        )
    )
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 기록 실패가 기능 결과를 막지 않게(D-018)
        db.rollback()
        logger.warning(
            "AI 사용량 기록 실패 user_id=%s feature=%s calls=%s error=%s",
            user_id,
            feature,
            usage.calls,
            type(exc).__name__,
        )
        return False
    return True
