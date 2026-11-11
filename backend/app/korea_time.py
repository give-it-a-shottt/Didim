"""'오늘'의 기준 — 한국 시간 0시 (D-018, 사용자 확인 2026-11-11).

AI 하루 상한(D-018)과 '오늘 복습'(F-004)이 같은 함수를 쓴다. 둘의 '오늘'이 어긋나면
"상한은 풀렸는데 복습은 어제 것" 같은 일이 생기기 때문이다.

한국은 일광 절약 시간이 없어서 UTC+9 고정 오프셋으로 둔다. zoneinfo("Asia/Seoul")를 쓰면 Windows에서
tzdata 패키지가 따로 필요하다.
DB에는 UTC로 저장하고, 비교할 때 "한국 날짜의 0시"를 UTC로 바꿔 쓴다.
"""

from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9), name="KST")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def korea_today(now: datetime | None = None) -> date:
    """지금(또는 주어진 시각)의 한국 날짜. now는 시간대가 붙은 값이어야 한다."""
    moment = now if now is not None else now_utc()
    if moment.tzinfo is None:
        raise ValueError("시간대가 없는 시각은 한국 날짜로 바꿀 수 없어요.")
    return moment.astimezone(KST).date()


def korea_day_start_utc(day: date) -> datetime:
    """한국 날짜 day의 0시를 UTC 시각으로. 예) 2026-11-11 → 2026-11-10 15:00 UTC."""
    return datetime.combine(day, time.min, tzinfo=KST).astimezone(timezone.utc)
