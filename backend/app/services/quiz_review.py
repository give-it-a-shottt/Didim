"""문제 풀기 · 복습 간격 · 오답노트 (F-004 완료 기준 4 · 5).

복습 간격(사용자 확인 2026-11-10 · 11):
- 단계 0 → 당일, 1 → 1일, 2 → 3일, 3 → 7일, 4 → 14일 뒤(4단계에서 맞히면 14일 그대로).
- 복습일이 된 문제(next_review_on <= 오늘)를 맞히면 한 단계 올리고 연속 정답 +1.
- 틀리면 언제든(미리 풀어도) 0단계 · 오늘 다시 · 연속 정답 0 · 오답노트에 넣는다.
- 복습일 전에 미리 맞히면 기록만 남기고 상태는 그대로(미리 맞혀 간격을 건너뛰지 않게).
- 오답노트에 있는 문제는 연속 2번 맞히면 빠진다.

'오늘'은 한국 날짜(app/korea_time.py, D-018과 같은 기준). 모든 조회에 user_id 조건을 건다(D-004).
목록 · 오늘 복습에는 정답 · 해설 · 인용을 넣지 않는다 — 답을 낸 뒤 answer_quiz가 돌려준다.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import MAX_REVIEW_SESSION_QUIZZES, QUIZ_REVIEW_INTERVAL_DAYS
from app.db.models import Note, Quiz, QuizAttempt, QuizReview
from app.korea_time import korea_today, now_utc
from app.services.note_service import get_note_for_user

LAST_STEP = len(QUIZ_REVIEW_INTERVAL_DAYS) - 1
WRONG_NOTES_GRADUATION_STREAK = 2  # 오답노트는 연속 2번 맞히면 빠짐


class QuizNotFound(Exception):
    """내 문제가 아니거나 없는 문제."""


class InvalidChoice(Exception):
    """보기 범위 밖의 답."""


@dataclass(frozen=True)
class ReviewState:
    interval_step: int
    correct_streak: int
    in_wrong_notes: bool
    next_review_on: date


def next_review_state(current: ReviewState, *, correct: bool, today: date) -> ReviewState:
    """답 하나를 반영한 다음 복습 상태. DB 없이 규칙만 담는다(테스트하기 쉽게)."""
    if not correct:
        return ReviewState(interval_step=0, correct_streak=0, in_wrong_notes=True, next_review_on=today)
    if current.next_review_on > today:  # 복습일 전에 미리 맞힘 → 그대로
        return current
    step = min(current.interval_step + 1, LAST_STEP)
    streak = current.correct_streak + 1
    in_wrong_notes = current.in_wrong_notes and streak < WRONG_NOTES_GRADUATION_STREAK
    return ReviewState(
        interval_step=step,
        correct_streak=streak,
        in_wrong_notes=in_wrong_notes,
        next_review_on=today + timedelta(days=QUIZ_REVIEW_INTERVAL_DAYS[step]),
    )


# --- 목록 ---


@dataclass(frozen=True)
class QuizCard:
    """풀기 전 화면에 보여 줄 것(정답 · 해설 · 인용 없음)."""

    id: int
    note_id: int
    note_title: str
    kind: str
    question: str
    choices: list[str]
    next_review_on: date
    in_wrong_notes: bool


def _cards_query(user_id: int):  # noqa: ANN202 — select 문 타입이 길어서 생략
    return (
        select(Quiz, QuizReview, Note.title)
        .join(QuizReview, QuizReview.quiz_id == Quiz.id)
        .join(Note, Note.id == Quiz.note_id)
        .where(Quiz.user_id == user_id, QuizReview.user_id == user_id, Note.user_id == user_id)
    )


def _to_cards(rows) -> list[QuizCard]:  # noqa: ANN001
    return [
        QuizCard(
            id=quiz.id,
            note_id=quiz.note_id,
            note_title=title,
            kind=quiz.kind,
            question=quiz.question,
            choices=list(quiz.choices),
            next_review_on=review.next_review_on,
            in_wrong_notes=review.in_wrong_notes,
        )
        for quiz, review, title in rows
    ]


def list_note_quizzes(db: Session, *, user_id: int, note_id: int) -> list[QuizCard] | None:
    """그 노트의 문제(노트 안 순서). 내 노트가 아니면 None."""
    if get_note_for_user(db, user_id=user_id, note_id=note_id) is None:
        return None
    rows = db.execute(_cards_query(user_id).where(Quiz.note_id == note_id).order_by(Quiz.quote_start, Quiz.id)).all()
    return _to_cards(rows)


@dataclass(frozen=True)
class ReviewList:
    """한 세션으로 푸는 목록(오늘 복습 · 오답노트). 목록은 상한까지만, 전체 개수는 따로."""

    total: int  # 조건에 맞는 문제 수 전체
    quizzes: list[QuizCard]  # 그중 앞에서부터 MAX_REVIEW_SESSION_QUIZZES개


def list_today_reviews(db: Session, *, user_id: int, now: datetime | None = None) -> ReviewList:
    """모든 노트에서 오늘 차례인 문제(다음 복습일 <= 오늘). 오래 밀린 것부터."""
    today = korea_today(now)
    due = QuizReview.next_review_on <= today
    total = db.scalar(select(func.count()).select_from(QuizReview).where(QuizReview.user_id == user_id, due)) or 0
    rows = db.execute(
        _cards_query(user_id).where(due).order_by(QuizReview.next_review_on, Quiz.id).limit(MAX_REVIEW_SESSION_QUIZZES)
    ).all()
    return ReviewList(total=total, quizzes=_to_cards(rows))


def list_wrong_answers(db: Session, *, user_id: int) -> ReviewList:
    """오답노트(최근에 틀린 것 먼저). 오늘 복습처럼 상한까지만 보낸다(F-004 1차 리뷰 R2)."""
    wrong = QuizReview.in_wrong_notes.is_(True)
    total = db.scalar(select(func.count()).select_from(QuizReview).where(QuizReview.user_id == user_id, wrong)) or 0
    rows = db.execute(
        _cards_query(user_id)
        .where(wrong)
        .order_by(QuizReview.updated_at.desc(), Quiz.id)
        .limit(MAX_REVIEW_SESSION_QUIZZES)
    ).all()
    return ReviewList(total=total, quizzes=_to_cards(rows))


# --- 답 내기 ---


@dataclass(frozen=True)
class AnswerResult:
    correct: bool
    answer_index: int
    explanation: str
    # 근거(설계 원칙 1): 해설의 근거 칩 → 노트 상세 위치 강조(F-003)
    note_id: int
    note_title: str
    chunk_id: int
    quote: str
    quote_start: int
    quote_end: int
    next_review_on: date
    in_wrong_notes: bool


def answer_quiz(
    db: Session, *, user_id: int, quiz_id: int, chosen_index: int, now: datetime | None = None
) -> AnswerResult:
    """채점하고 푼 기록 · 복습 상태를 저장한다. QuizNotFound / InvalidChoice.

    같은 문제에 답이 동시에 두 번 들어와도 상태를 덮어쓰지 않게 복습 상태 줄을 잠근다(PostgreSQL FOR UPDATE).
    """
    at = now if now is not None else now_utc()
    row = db.execute(
        select(Quiz, QuizReview, Note.title)
        .join(QuizReview, QuizReview.quiz_id == Quiz.id)
        .join(Note, Note.id == Quiz.note_id)
        .where(Quiz.id == quiz_id, Quiz.user_id == user_id, QuizReview.user_id == user_id, Note.user_id == user_id)
        .with_for_update(of=QuizReview)
    ).one_or_none()
    if row is None:
        raise QuizNotFound
    quiz, review, note_title = row
    if not 0 <= chosen_index < len(quiz.choices):
        db.rollback()  # 잠금을 바로 푼다
        raise InvalidChoice

    correct = chosen_index == quiz.answer_index
    current = ReviewState(
        interval_step=review.interval_step,
        correct_streak=review.correct_streak,
        in_wrong_notes=review.in_wrong_notes,
        next_review_on=review.next_review_on,
    )
    updated = next_review_state(current, correct=correct, today=korea_today(at))

    db.add(QuizAttempt(user_id=user_id, quiz_id=quiz.id, chosen_index=chosen_index, is_correct=correct, created_at=at))
    if updated != current:
        review.interval_step = updated.interval_step
        review.correct_streak = updated.correct_streak
        review.in_wrong_notes = updated.in_wrong_notes
        review.next_review_on = updated.next_review_on
        review.updated_at = at
    db.commit()

    return AnswerResult(
        correct=correct,
        answer_index=quiz.answer_index,
        explanation=quiz.explanation,
        note_id=quiz.note_id,
        note_title=note_title,
        chunk_id=quiz.chunk_id,
        quote=quiz.quote,
        quote_start=quiz.quote_start,
        quote_end=quiz.quote_end,
        next_review_on=updated.next_review_on,
        in_wrong_notes=updated.in_wrong_notes,
    )
