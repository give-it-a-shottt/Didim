"""AI 사용량 확인 · 기록 테스트 (D-018, F-004 완료 기준 6).

확인하는 것:
- '오늘'은 한국 시간 0시에 바뀐다(UTC 15시). 시간대 없는 시각은 거부한다.
- 오늘 쓴 호출 수 = 오늘(한국 시간) 기록의 calls 합계. 어제 기록 · 다른 사용자의 기록은 세지 않는다(D-004).
- 상한에 닿으면 DailyLimitExceeded, 그 전에는 남은 양을 돌려준다. 사용자마다 상한(daily_limit)이 다르면 그 값을 쓴다.
- 기록: 실패한 호출도 센다, 호출 0번은 기록하지 않는다, 결과 종류만 남긴다.
- 기록 저장이 실패하면 되돌리고 False(기능 결과를 막지 않음), 실패 로그에 사용자 내용이 없다.
- 사용자를 지우면 사용량 기록도 지워진다(CASCADE).
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import DEFAULT_DAILY_LIMIT
from app.db.models import AIUsageLog
from app.korea_time import korea_day_start_utc, korea_today
from app.llm.base import (
    LLMConfigError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMRequestError,
    LLMUnavailable,
    LLMUsage,
)
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.note_service import delete_user_account
from app.services.usage_service import (
    FEATURE_QUIZ_GENERATE,
    DailyLimitExceeded,
    daily_usage,
    ensure_within_daily_limit,
    outcome_for,
    record_usage,
)

UTC = timezone.utc
# 한국 2026-11-11 오전 10시 = UTC 2026-11-11 01:00
KOREA_MORNING = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)


def _user(db: Session, sub: str) -> int:
    return get_or_create_google_user(db, GoogleProfile(sub=sub, email=f"{sub}@example.com", name=sub)).id


def _record(db: Session, user_id: int, calls: int, at: datetime) -> None:
    assert record_usage(
        db, user_id=user_id, feature=FEATURE_QUIZ_GENERATE, usage=LLMUsage(calls=calls), outcome="ok", now=at
    )


# --- 한국 시간 '오늘' ---


def test_korea_day_changes_at_midnight_korea_time() -> None:
    assert korea_today(datetime(2026, 11, 10, 14, 59, 59, tzinfo=UTC)) == date(2026, 11, 10)
    assert korea_today(datetime(2026, 11, 10, 15, 0, 0, tzinfo=UTC)) == date(2026, 11, 11)


def test_korea_day_start_is_15_utc_of_the_day_before() -> None:
    assert korea_day_start_utc(date(2026, 11, 11)) == datetime(2026, 11, 10, 15, 0, tzinfo=UTC)


def test_time_without_timezone_is_rejected() -> None:
    with pytest.raises(ValueError):
        korea_today(datetime(2026, 11, 11, 1, 0))


# --- 오늘 쓴 양 · 상한 ---


def test_new_user_has_the_default_limit_and_nothing_used(db_session: Session) -> None:
    user_id = _user(db_session, "u-new")

    usage = daily_usage(db_session, user_id=user_id, now=KOREA_MORNING)

    assert (usage.used, usage.limit, usage.remaining) == (0, DEFAULT_DAILY_LIMIT, DEFAULT_DAILY_LIMIT)


def test_only_today_in_korea_time_is_counted(db_session: Session) -> None:
    """한국 날짜가 바뀌는 순간(UTC 15:00) 앞뒤를 나눠 센다."""
    user_id = _user(db_session, "u-day")
    day_start = korea_day_start_utc(date(2026, 11, 11))
    _record(db_session, user_id, 5, day_start - timedelta(seconds=1))  # 한국 11-10 23:59:59 → 어제
    _record(db_session, user_id, 2, day_start)  # 한국 11-11 00:00:00 → 오늘
    _record(db_session, user_id, 3, KOREA_MORNING)

    assert daily_usage(db_session, user_id=user_id, now=KOREA_MORNING).used == 5


def test_other_users_usage_is_not_counted(db_session: Session) -> None:
    me = _user(db_session, "u-me")
    other = _user(db_session, "u-other")
    _record(db_session, other, 30, KOREA_MORNING)
    _record(db_session, me, 1, KOREA_MORNING)

    assert daily_usage(db_session, user_id=me, now=KOREA_MORNING).used == 1


def test_limit_is_reached_exactly_at_the_daily_limit(db_session: Session) -> None:
    user_id = _user(db_session, "u-limit")
    _record(db_session, user_id, DEFAULT_DAILY_LIMIT - 1, KOREA_MORNING)

    assert ensure_within_daily_limit(db_session, user_id=user_id, now=KOREA_MORNING).remaining == 1

    _record(db_session, user_id, 1, KOREA_MORNING)
    with pytest.raises(DailyLimitExceeded) as caught:
        ensure_within_daily_limit(db_session, user_id=user_id, now=KOREA_MORNING)
    assert (caught.value.usage.used, caught.value.usage.remaining) == (DEFAULT_DAILY_LIMIT, 0)


def test_going_over_the_limit_still_reports_zero_remaining(db_session: Session) -> None:
    """동시 요청 · 재시도로 상한을 넘을 수 있다(D-018). 그래도 남은 양은 음수가 아니다."""
    user_id = _user(db_session, "u-over")
    _record(db_session, user_id, DEFAULT_DAILY_LIMIT + 3, KOREA_MORNING)

    with pytest.raises(DailyLimitExceeded) as caught:
        ensure_within_daily_limit(db_session, user_id=user_id, now=KOREA_MORNING)
    assert caught.value.usage.remaining == 0


def test_limit_resets_the_next_korea_day(db_session: Session) -> None:
    user_id = _user(db_session, "u-reset")
    _record(db_session, user_id, DEFAULT_DAILY_LIMIT, KOREA_MORNING)

    next_day = korea_day_start_utc(date(2026, 11, 12))
    assert ensure_within_daily_limit(db_session, user_id=user_id, now=next_day).used == 0


def test_per_user_daily_limit_is_used(db_session: Session) -> None:
    user = get_or_create_google_user(db_session, GoogleProfile(sub="u-small", email="s@example.com", name="s"))
    user.daily_limit = 2
    db_session.commit()
    _record(db_session, user.id, 2, KOREA_MORNING)

    with pytest.raises(DailyLimitExceeded):
        ensure_within_daily_limit(db_session, user_id=user.id, now=KOREA_MORNING)


def test_unknown_user_is_an_error(db_session: Session) -> None:
    with pytest.raises(LookupError):
        daily_usage(db_session, user_id=999_999, now=KOREA_MORNING)


# --- 기록 ---


def test_usage_row_keeps_calls_tokens_and_outcome_only(db_session: Session) -> None:
    user_id = _user(db_session, "u-row")

    saved = record_usage(
        db_session,
        user_id=user_id,
        feature=FEATURE_QUIZ_GENERATE,
        usage=LLMUsage(calls=3, prompt_tokens=1200, completion_tokens=400),
        outcome=outcome_for(LLMInvalidOutput("형식", attempts=2, raw_content="비밀 원문")),
        now=KOREA_MORNING,
    )

    assert saved is True
    row = db_session.scalars(select(AIUsageLog).where(AIUsageLog.user_id == user_id)).one()
    assert (row.feature, row.calls, row.prompt_tokens, row.completion_tokens, row.outcome) == (
        "quiz_generate",
        3,
        1200,
        400,
        "invalid_output",
    )


def test_zero_calls_are_not_recorded(db_session: Session) -> None:
    user_id = _user(db_session, "u-zero")

    assert record_usage(db_session, user_id=user_id, feature=FEATURE_QUIZ_GENERATE, usage=LLMUsage(), outcome="ok")
    assert db_session.scalar(select(func.count()).select_from(AIUsageLog)) == 0


def test_outcome_names_each_llm_error_kind() -> None:
    assert outcome_for(None) == "ok"
    assert outcome_for(LLMRateLimited("429")) == "rate_limited"
    assert outcome_for(LLMUnavailable("down")) == "unavailable"
    assert outcome_for(LLMConfigError("key")) == "config_error"
    assert outcome_for(LLMRequestError("400", status_code=400)) == "request_error"
    assert outcome_for(LLMInvalidOutput("bad", attempts=2, raw_content="")) == "invalid_output"


def test_failed_save_rolls_back_and_returns_false(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    user_id = _user(db_session, "u-fail")
    rolled_back: list[bool] = []
    original_rollback = db_session.rollback

    def failing_commit() -> None:
        raise OperationalError("INSERT", {}, Exception("db down"))

    def tracking_rollback() -> None:
        rolled_back.append(True)
        original_rollback()

    monkeypatch.setattr(db_session, "commit", failing_commit)
    monkeypatch.setattr(db_session, "rollback", tracking_rollback)

    saved = record_usage(
        db_session, user_id=user_id, feature=FEATURE_QUIZ_GENERATE, usage=LLMUsage(calls=1), outcome="ok"
    )

    monkeypatch.undo()
    assert saved is False
    assert rolled_back == [True]
    assert db_session.scalar(select(func.count()).select_from(AIUsageLog)) == 0
    assert "AI 사용량 기록 실패" in caplog.text
    assert "db down" not in caplog.text


def test_deleting_the_user_deletes_usage_rows(db_session: Session) -> None:
    user_id = _user(db_session, "u-delete")
    _record(db_session, user_id, 2, KOREA_MORNING)

    delete_user_account(db_session, user_id=user_id)

    assert db_session.scalar(select(func.count()).select_from(AIUsageLog)) == 0
