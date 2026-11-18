"""홈 · 첫 방문 안내 (F-012) — 단계 띠 개수 · 오늘 복습 · 마감이 다가온 지원 · 빈칸 있는 카드를 한 번에.

세기만 하는 가벼운 쿼리이고 모든 조회에 user_id 조건을 건다(D-004). 각 기준은 원래 기능의 함수를 그대로 쓴다 —
오늘 복습은 quiz_review.count_today_reviews, 빈칸은 card_service.list_blank_cards(_is_blank), 남은 날은
application_service.list_upcoming_deadlines(한국 날짜). 그래서 홈 숫자와 각 화면의 숫자가 어긋나지 않는다.
첫 방문 체크리스트(노트 · 저장 카드 · 지원이 1개 이상인가)는 화면이 이 개수로 판단한다(사용자 확인 2026-11-18).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import CARD_STATUS_SAVED, HOME_DEADLINE_DAYS, HOME_LIST_LIMIT
from app.db.models import Application, Card, Draft, Note
from app.services.application_service import UpcomingDeadline, list_upcoming_deadlines
from app.services.card_service import BlankCard, list_blank_cards
from app.services.quiz_review import count_today_reviews


@dataclass(frozen=True)
class HomeSteps:
    notes: int  # 기록 = 노트 수
    reviews_today: int  # 복습 = 오늘 복습할 문제 수
    cards: int  # 카드 = 저장한 카드 수(후보 제외)
    applications: int  # 공고 = 지원 수
    drafted_applications: int  # 자소서 · 면접 = 자소서 초안을 하나라도 쓴 지원 수


@dataclass(frozen=True)
class HomeView:
    steps: HomeSteps
    deadlines: list[UpcomingDeadline]
    blank_cards: list[BlankCard]


def _count(db: Session, model: type, *conditions: object) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0  # type: ignore[arg-type]


def get_home(db: Session, *, user_id: int, now: datetime | None = None) -> HomeView:
    drafted = db.scalar(
        select(func.count(func.distinct(Draft.application_id))).where(Draft.user_id == user_id)
    ) or 0
    steps = HomeSteps(
        notes=_count(db, Note, Note.user_id == user_id),
        reviews_today=count_today_reviews(db, user_id=user_id, now=now),
        cards=_count(db, Card, Card.user_id == user_id, Card.status == CARD_STATUS_SAVED),
        applications=_count(db, Application, Application.user_id == user_id),
        drafted_applications=drafted,
    )
    return HomeView(
        steps=steps,
        deadlines=list_upcoming_deadlines(
            db, user_id=user_id, within_days=HOME_DEADLINE_DAYS, limit=HOME_LIST_LIMIT, now=now
        ),
        blank_cards=list_blank_cards(db, user_id=user_id, limit=HOME_LIST_LIMIT),
    )
