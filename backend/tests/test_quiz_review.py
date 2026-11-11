"""문제 풀기 · 복습 간격 · 오답노트 테스트 (F-004 완료 기준 3 · 4 · 5).

규칙(사용자 확인 2026-11-10 · 11):
- 복습일이 된 문제를 맞히면 당일 → 1 → 3 → 7 → 14일(14일에서 멈춤), 연속 정답 +1.
- 틀리면 언제든 0단계 · 오늘 다시 · 오답노트. 오답노트는 연속 2번 맞히면 빠짐.
- 복습일 전에 미리 맞히면 기록만 남기고 상태 그대로.
API: 목록에는 정답 · 해설 · 인용이 없고, 답을 내면 채점 · 해설 · 근거 위치 · 다음 복습일을 준다.
남의 문제 · 노트는 404(D-004). '오늘'은 한국 날짜.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import MAX_REVIEW_SESSION_QUIZZES, SESSION_COOKIE_NAME, Settings
from app.db.models import Chunk, Note, Quiz, QuizAttempt, QuizReview
from app.korea_time import korea_today
from app.services.auth_service import GoogleProfile, create_session_token, get_or_create_google_user
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user
from app.services.quiz_review import (
    ReviewState,
    answer_quiz,
    list_today_reviews,
    list_wrong_answers,
    next_review_state,
)

TODAY = date(2026, 11, 11)
QUOTE = "인덱스는 조회를 빠르게 하지만 쓰기를 느리게 해요."
NOTE = f"""# 데이터베이스

## 인덱스
{QUOTE}
"""


def _state(step: int = 0, streak: int = 0, wrong: bool = False, on: date = TODAY) -> ReviewState:
    return ReviewState(interval_step=step, correct_streak=streak, in_wrong_notes=wrong, next_review_on=on)


# --- 규칙 (DB 없음) ---


@pytest.mark.parametrize(
    ("step", "next_step", "days"),
    [(0, 1, 1), (1, 2, 3), (2, 3, 7), (3, 4, 14), (4, 4, 14)],
)
def test_correct_on_due_day_moves_up_one_step(step: int, next_step: int, days: int) -> None:
    updated = next_review_state(_state(step=step, streak=1), correct=True, today=TODAY)

    assert updated == _state(step=next_step, streak=2, on=TODAY + timedelta(days=days))


def test_overdue_quiz_counts_as_due() -> None:
    updated = next_review_state(_state(step=1, on=TODAY - timedelta(days=5)), correct=True, today=TODAY)

    assert (updated.interval_step, updated.next_review_on) == (2, TODAY + timedelta(days=3))


def test_wrong_answer_resets_to_today_and_wrong_notes_even_before_due() -> None:
    for on in (TODAY, TODAY + timedelta(days=7)):
        updated = next_review_state(_state(step=3, streak=4, on=on), correct=False, today=TODAY)
        assert updated == _state(step=0, streak=0, wrong=True, on=TODAY)


def test_correct_before_due_day_changes_nothing() -> None:
    current = _state(step=2, streak=1, wrong=True, on=TODAY + timedelta(days=2))

    assert next_review_state(current, correct=True, today=TODAY) == current


def test_wrong_notes_needs_two_correct_in_a_row() -> None:
    wrong = next_review_state(_state(step=2), correct=False, today=TODAY)
    first = next_review_state(wrong, correct=True, today=TODAY)  # 오늘 다시 → 오늘 맞힘
    assert first.in_wrong_notes is True and first.correct_streak == 1

    second = next_review_state(first, correct=True, today=first.next_review_on)
    assert second.in_wrong_notes is False and second.correct_streak == 2


# --- DB · API ---


def _login(client: TestClient, db: Session, settings: Settings, sub: str) -> int:
    user = get_or_create_google_user(db, GoogleProfile(sub=sub, email=f"{sub}@example.com", name=sub))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user.id, settings.session_secret))
    return user.id


def _note(db: Session, user_id: int, title: str = "데이터베이스", sections: int = 3) -> Note:
    """조각마다 문제는 하나라서(chunk_id 유니크) 같은 인용 문장을 담은 구역을 여러 개 만든다.
    같은 내용의 노트는 중복으로 막히므로(F-002) 제목을 끝에 붙여 내용을 다르게 한다."""
    body = "".join(f"\n## 인덱스 {number}\n{QUOTE}\n" for number in range(sections))
    content = NOTE + body + "\n" + title + "\n"
    return create_note_for_user(db, user_id=user_id, title=title, content=content, chunks=split_markdown(content))


def _quiz(
    db: Session, note: Note, *, on: date, step: int = 0, wrong: bool = False, kind: str = "mcq", answer: int = 1
) -> Quiz:
    """아직 문제가 없는 첫 조각에 문제 하나를 만든다."""
    used = select(Quiz.chunk_id)
    chunk = db.scalars(
        select(Chunk).where(Chunk.note_id == note.id, Chunk.id.not_in(used)).order_by(Chunk.position)
    ).first()
    assert chunk is not None
    start = chunk.start_offset + chunk.content.index(QUOTE)
    quiz = Quiz(
        user_id=note.user_id,
        note_id=note.id,
        chunk_id=chunk.id,
        kind=kind,
        question="인덱스의 단점은?",
        choices=["조회가 느려짐", "쓰기가 느려짐", "용량이 줄어듦", "없음"] if kind == "mcq" else ["O", "X"],
        answer_index=answer,
        explanation="쓰기 때마다 인덱스도 고쳐야 해서요.",
        quote=QUOTE,
        quote_start=start,
        quote_end=start + len(QUOTE),
    )
    db.add(quiz)
    db.flush()
    db.add(QuizReview(user_id=note.user_id, quiz_id=quiz.id, next_review_on=on, interval_step=step, in_wrong_notes=wrong))
    db.commit()
    return quiz


def test_lists_hide_the_answer_and_evidence(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    user_id = _login(client, db_session, test_settings, "r-list")
    note = _note(db_session, user_id)
    quiz = _quiz(db_session, note, on=korea_today())

    for path in (f"/api/notes/{note.id}/quizzes", "/api/reviews/today"):
        response = client.get(path)
        assert response.status_code == 200, path
        card = response.json()["quizzes"][0]
        assert card["id"] == quiz.id and card["note_title"] == "데이터베이스"
        assert not {"answer_index", "explanation", "quote"} & card.keys()


def test_today_review_has_due_quizzes_from_all_my_notes_only(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "r-today")
    today = korea_today()
    first, second = _note(db_session, user_id, "첫 노트"), _note(db_session, user_id, "둘째 노트")
    overdue = _quiz(db_session, second, on=today - timedelta(days=3))
    due = _quiz(db_session, first, on=today)
    _quiz(db_session, first, on=today + timedelta(days=1))  # 내일 차례
    other = get_or_create_google_user(db_session, GoogleProfile(sub="r-other", email="x@example.com", name="x"))
    _quiz(db_session, _note(db_session, other.id), on=today)  # 남의 문제

    body = client.get("/api/reviews/today").json()

    assert body["total"] == 2
    assert [card["id"] for card in body["quizzes"]] == [overdue.id, due.id]  # 오래 밀린 것부터


def test_today_review_is_capped_but_total_is_full(db_session: Session) -> None:
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="r-cap", email="c@example.com", name="c")).id
    note = _note(db_session, user_id, sections=MAX_REVIEW_SESSION_QUIZZES + 1)
    for _ in range(MAX_REVIEW_SESSION_QUIZZES + 1):
        _quiz(db_session, note, on=TODAY)

    today = list_today_reviews(db_session, user_id=user_id, now=datetime(2026, 11, 11, 1, tzinfo=timezone.utc))

    assert (today.total, len(today.quizzes)) == (MAX_REVIEW_SESSION_QUIZZES + 1, MAX_REVIEW_SESSION_QUIZZES)


def test_wrong_answers_are_capped_but_total_is_full(db_session: Session) -> None:
    """오답노트도 오늘 복습처럼 상한까지만 보낸다(F-004 1차 리뷰 R2)."""
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="r-wcap", email="w@example.com", name="w")).id
    note = _note(db_session, user_id, sections=MAX_REVIEW_SESSION_QUIZZES + 1)
    for _ in range(MAX_REVIEW_SESSION_QUIZZES + 1):
        _quiz(db_session, note, on=TODAY, wrong=True)

    wrong = list_wrong_answers(db_session, user_id=user_id)

    assert (wrong.total, len(wrong.quizzes)) == (MAX_REVIEW_SESSION_QUIZZES + 1, MAX_REVIEW_SESSION_QUIZZES)


def test_answer_returns_grading_explanation_and_evidence_location(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "r-answer")
    note = _note(db_session, user_id)
    quiz = _quiz(db_session, note, on=korea_today())

    response = client.post(f"/api/quizzes/{quiz.id}/answer", json={"chosen_index": 1})

    assert response.status_code == 200
    body = response.json()
    assert (body["correct"], body["answer_index"], body["in_wrong_notes"]) == (True, 1, False)
    assert body["next_review_on"] == (korea_today() + timedelta(days=1)).isoformat()
    assert (body["note_id"], body["chunk_id"]) == (note.id, quiz.chunk_id)
    assert note.content[body["quote_start"] : body["quote_end"]] == body["quote"] == QUOTE
    attempt = db_session.scalars(select(QuizAttempt)).one()
    assert (attempt.user_id, attempt.quiz_id, attempt.chosen_index, attempt.is_correct) == (user_id, quiz.id, 1, True)


def test_wrong_answer_goes_to_wrong_notes_and_comes_back_today(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "r-wrong")
    quiz = _quiz(db_session, _note(db_session, user_id), on=korea_today() + timedelta(days=7), step=3)

    body = client.post(f"/api/quizzes/{quiz.id}/answer", json={"chosen_index": 0}).json()

    assert (body["correct"], body["in_wrong_notes"], body["next_review_on"]) == (False, True, korea_today().isoformat())
    assert [card["id"] for card in client.get("/api/wrong-answers").json()["quizzes"]] == [quiz.id]
    assert [card["id"] for card in client.get("/api/reviews/today").json()["quizzes"]] == [quiz.id]


def test_two_correct_in_a_row_leave_wrong_notes(db_session: Session) -> None:
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="r-grad", email="g@example.com", name="g")).id
    quiz = _quiz(db_session, _note(db_session, user_id), on=TODAY)
    day = datetime(2026, 11, 11, 1, tzinfo=timezone.utc)  # 한국 11-11 10:00

    answer_quiz(db_session, user_id=user_id, quiz_id=quiz.id, chosen_index=0, now=day)  # 틀림 → 오늘 다시
    first = answer_quiz(db_session, user_id=user_id, quiz_id=quiz.id, chosen_index=1, now=day)  # 오늘 맞힘
    second = answer_quiz(db_session, user_id=user_id, quiz_id=quiz.id, chosen_index=1, now=day + timedelta(days=1))

    assert first.in_wrong_notes is True and first.next_review_on == date(2026, 11, 12)
    assert second.in_wrong_notes is False and second.next_review_on == date(2026, 11, 15)


def test_answer_uses_the_korea_date(db_session: Session) -> None:
    """UTC로는 11-10이지만 한국은 11-11인 시각에 11-11 차례 문제를 맞히면 복습일로 친다."""
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="r-kst", email="k@example.com", name="k")).id
    quiz = _quiz(db_session, _note(db_session, user_id), on=TODAY)

    result = answer_quiz(
        db_session, user_id=user_id, quiz_id=quiz.id, chosen_index=1, now=datetime(2026, 11, 10, 16, tzinfo=timezone.utc)
    )

    assert result.next_review_on == date(2026, 11, 12)


@pytest.mark.parametrize(("kind", "chosen"), [("mcq", 4), ("mcq", -1), ("ox", 2)])
def test_choice_out_of_range_is_422_and_not_recorded(
    client: TestClient, db_session: Session, test_settings: Settings, kind: str, chosen: int
) -> None:
    user_id = _login(client, db_session, test_settings, f"r-range-{kind}-{chosen}")
    quiz = _quiz(db_session, _note(db_session, user_id), on=korea_today(), kind=kind, answer=0)

    response = client.post(f"/api/quizzes/{quiz.id}/answer", json={"chosen_index": chosen})

    assert response.status_code == 422
    assert db_session.scalars(select(QuizAttempt)).all() == []


@pytest.mark.parametrize("quiz_ref", ["other", "999999", "2147483648", "0"])
def test_someone_elses_or_missing_quiz_is_404(
    client: TestClient, db_session: Session, test_settings: Settings, quiz_ref: str
) -> None:
    owner = get_or_create_google_user(db_session, GoogleProfile(sub="r-owner", email="o@example.com", name="o"))
    others = _quiz(db_session, _note(db_session, owner.id), on=korea_today())
    _login(client, db_session, test_settings, "r-intruder")

    quiz_id = others.id if quiz_ref == "other" else quiz_ref
    response = client.post(f"/api/quizzes/{quiz_id}/answer", json={"chosen_index": 1})

    assert response.status_code == 404
    review = db_session.scalars(select(QuizReview).where(QuizReview.quiz_id == others.id)).one()
    assert review.interval_step == 0 and db_session.scalars(select(QuizAttempt)).all() == []


def test_someone_elses_note_quizzes_are_404(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    owner = get_or_create_google_user(db_session, GoogleProfile(sub="r-o2", email="o2@example.com", name="o2"))
    note = _note(db_session, owner.id)
    _quiz(db_session, note, on=korea_today())
    _login(client, db_session, test_settings, "r-i2")

    assert client.get(f"/api/notes/{note.id}/quizzes").status_code == 404
    assert client.get("/api/reviews/today").json() == {"total": 0, "quizzes": []}
    assert client.get("/api/wrong-answers").json() == {"total": 0, "quizzes": []}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/notes/1/quizzes"),
        ("get", "/api/reviews/today"),
        ("get", "/api/wrong-answers"),
        ("post", "/api/quizzes/1/answer"),
    ],
)
def test_login_is_required(client: TestClient, method: str, path: str) -> None:
    kwargs = {"json": {"chosen_index": 0}} if method == "post" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
