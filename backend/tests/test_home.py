"""홈 API 테스트 (F-012) — 단계 띠 개수 · 마감이 다가온 지원 · 빈칸 있는 카드 · 사용자 분리(D-004)."""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import SESSION_COOKIE_NAME, Settings
from app.db.models import (
    Application,
    ApplicationQuestion,
    Card,
    CardField,
    Draft,
    Quiz,
    QuizReview,
)
from app.korea_time import korea_today
from app.services.auth_service import (
    GoogleProfile,
    create_session_token,
    get_or_create_google_user,
)
from app.services.chunking import split_markdown
from app.services.home_service import get_home
from app.services.note_service import create_note_for_user

NOW = datetime(2026, 11, 18, 3, 0, tzinfo=UTC)  # 한국 2026-11-18 정오
TODAY = korea_today(NOW)


def _user(db: Session, sub: str) -> int:
    return get_or_create_google_user(db, GoogleProfile(sub=sub, email=f"{sub}@example.com", name=sub)).id


def _note(db: Session, user_id: int, title: str = "노트") -> int:
    content = f"# {title}\n\n## 본문\n복습할 내용이 들어 있는 조각이다. 충분히 길게 적어 둔다."
    return create_note_for_user(db, user_id=user_id, title=title, content=content, chunks=split_markdown(content)).id


def _card(db: Session, user_id: int, title: str, *, status: str = "saved", blank: tuple[str, ...] = (), updated: int = 0) -> int:
    card = Card(user_id=user_id, title=title, status=status, updated_at=NOW + timedelta(minutes=updated))
    db.add(card)
    db.flush()
    for slot in ("situation", "task", "action", "result"):
        db.add(CardField(user_id=user_id, card_id=card.id, slot=slot, quote=None if slot in blank else f"{slot} 인용"))
    db.commit()
    return card.id


def _application(db: Session, user_id: int, company: str, *, days: int | None, status: str = "ready") -> int:
    deadline = TODAY + timedelta(days=days) if days is not None else None
    app_row = Application(user_id=user_id, company=company, role="개발", deadline=deadline, posting_text="공고", status=status)
    db.add(app_row)
    db.commit()
    return app_row.id


def _draft(db: Session, user_id: int, application_id: int) -> None:
    position = db.query(ApplicationQuestion).filter(ApplicationQuestion.application_id == application_id).count()
    question = ApplicationQuestion(user_id=user_id, application_id=application_id, position=position, text="문항")
    db.add(question)
    db.flush()
    db.add(Draft(user_id=user_id, application_id=application_id, question_id=question.id, ai_text="초안"))
    db.commit()


def _due_review(db: Session, user_id: int, *, days: int) -> None:
    """복습 문제 하나 — 조각 하나에 문제 하나뿐이라(quizzes.chunk_id 고유) 문제마다 노트를 따로 만든다."""
    from app.db.models import Chunk

    note_id = _note(db, user_id, f"복습 {days}")
    chunk = db.query(Chunk).filter(Chunk.note_id == note_id).first()
    assert chunk is not None
    quiz = Quiz(
        user_id=user_id, note_id=note_id, chunk_id=chunk.id, kind="ox", question="q", choices=["O", "X"],
        answer_index=0, explanation="e", quote="q", quote_start=0, quote_end=1,
    )
    db.add(quiz)
    db.flush()
    db.add(QuizReview(user_id=user_id, quiz_id=quiz.id, next_review_on=TODAY + timedelta(days=days)))
    db.commit()


def test_empty_account_has_zero_everywhere(db_session: Session) -> None:
    view = get_home(db_session, user_id=_user(db_session, "1"), now=NOW)
    assert vars(view.steps) == {"notes": 0, "reviews_today": 0, "cards": 0, "applications": 0, "drafted_applications": 0}
    assert view.deadlines == [] and view.blank_cards == []


def test_step_counts_follow_each_feature(db_session: Session) -> None:
    me = _user(db_session, "1")
    _due_review(db_session, me, days=0)
    _due_review(db_session, me, days=-3)  # 밀린 것도 오늘 차례
    _due_review(db_session, me, days=2)  # 아직 아님
    _note(db_session, me, "복습 없는 노트")
    _card(db_session, me, "저장")
    _card(db_session, me, "후보", status="candidate")  # 후보는 세지 않음
    first = _application(db_session, me, "가", days=3)
    _application(db_session, me, "나", days=None)
    _draft(db_session, me, first)
    _draft(db_session, me, first)  # 같은 지원의 두 번째 초안 — 지원은 한 번만 센다
    steps = get_home(db_session, user_id=me, now=NOW).steps
    assert vars(steps) == {"notes": 4, "reviews_today": 2, "cards": 1, "applications": 2, "drafted_applications": 1}


def test_upcoming_deadlines_within_seven_days_not_submitted(db_session: Session) -> None:
    me = _user(db_session, "1")
    _application(db_session, me, "오늘", days=0)
    _application(db_session, me, "엿새", days=6)
    _application(db_session, me, "이레", days=7)  # 오늘 포함 7일 밖
    _application(db_session, me, "지남", days=-1)
    _application(db_session, me, "없음", days=None)
    _application(db_session, me, "제출", days=1, status="submitted")
    _application(db_session, me, "작성 중", days=2, status="writing")
    _application(db_session, me, "사흘", days=3)
    _application(db_session, me, "닷새", days=5)
    deadlines = get_home(db_session, user_id=me, now=NOW).deadlines
    assert [(d.company, d.days_left) for d in deadlines] == [("오늘", 0), ("작성 중", 2), ("사흘", 3), ("닷새", 5)]  # 최대 4개
    assert deadlines[0].deadline == TODAY and isinstance(deadlines[0].deadline, date)


def test_blank_cards_saved_only_recent_first(db_session: Session) -> None:
    me = _user(db_session, "1")
    _card(db_session, me, "꽉 참", updated=50)
    _card(db_session, me, "후보 빈칸", status="candidate", blank=("result",), updated=60)
    for i in range(5):
        _card(db_session, me, f"빈칸 {i}", blank=("task", "result") if i == 4 else ("result",), updated=i)
    cards = get_home(db_session, user_id=me, now=NOW).blank_cards
    assert [c.title for c in cards] == ["빈칸 4", "빈칸 3", "빈칸 2", "빈칸 1"]
    assert cards[0].blank_slots == ["task", "result"]  # CARD_SLOTS 순서


def test_home_only_sees_my_data(db_session: Session) -> None:
    me, other = _user(db_session, "1"), _user(db_session, "2")
    _due_review(db_session, other, days=0)
    _card(db_session, other, "남의 카드", blank=("result",))
    app_id = _application(db_session, other, "남의 지원", days=1)
    _draft(db_session, other, app_id)
    view = get_home(db_session, user_id=me, now=NOW)
    assert set(vars(view.steps).values()) == {0}
    assert view.deadlines == [] and view.blank_cards == []


def test_home_api_needs_login_and_returns_the_shape(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    assert client.get("/api/home").status_code == 401
    me = _user(db_session, "1")
    _card(db_session, me, "빈칸", blank=("result",))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(me, test_settings.session_secret))
    body = client.get("/api/home").json()
    assert body["steps"]["cards"] == 1 and body["deadlines"] == []
    assert body["blank_cards"] == [{"id": body["blank_cards"][0]["id"], "title": "빈칸", "blank_slots": ["result"]}]
