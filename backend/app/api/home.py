"""홈 (F-012) — GET /api/home: 단계 띠 개수 · 오늘 복습 · 마감이 다가온 지원 · 빈칸 있는 카드. 계산은 home_service."""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services.home_service import get_home

router = APIRouter(tags=["home"])


class HomeStepsOut(BaseModel):
    notes: int
    reviews_today: int
    cards: int
    applications: int
    drafted_applications: int


class DeadlineOut(BaseModel):
    id: int
    company: str
    role: str
    deadline: date
    days_left: int
    status: str


class BlankCardOut(BaseModel):
    id: int
    title: str
    blank_slots: list[str]


class HomeOut(BaseModel):
    steps: HomeStepsOut
    deadlines: list[DeadlineOut]
    blank_cards: list[BlankCardOut]


@router.get("/home", response_model=HomeOut)
def read_home(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> HomeOut:
    view = get_home(db, user_id=current_user.id)
    return HomeOut.model_validate(view, from_attributes=True)
