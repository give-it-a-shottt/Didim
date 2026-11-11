"""quiz review tables (quizzes, quiz_reviews, quiz_attempts, quiz_generation_logs) and ai_usage_logs

(첫 줄은 alembic이 터미널에 찍는다. Windows cp949에서 깨지지 않게 영문으로 쓴다, T-003)
퀴즈 · 복습 (F-004 설계 의도 '데이터' — 사용자 확인 2026-11-10 · 칸 설계 2026-11-11)과
AI 사용량 공용 표 (D-018, 사용자 확인 2026-11-11).

- quizzes: 문제(보기 목록 + 정답 번호, 근거 조각 + 원문 인용 문장과 위치). 노트 · 조각이 지워지면 같이 지움.
  조각마다 하나(chunk_id 유니크).
- note_quiz_claims: 노트별 [문제 만들기] 선점(note_id 유니크) — 동시 클릭에도 AI를 한 번만 부름(사용자 확인 2026-11-11).
- quiz_reviews: 문제마다 하나인 복습 상태(다음 복습일은 한국 날짜). '오늘 복습'용 (user_id, next_review_on) 색인.
- quiz_attempts: 푼 기록.
- quiz_generation_logs: 문제 만들기 평가 로그(보낸 · 남긴 · 버린 수와 이유). note_id는 외래키 아님(로그는 남김).
- ai_usage_logs: 모든 AI 기능의 사용량. 하루 상한은 (user_id, created_at) 색인으로 오늘 calls 합계를 센다.

모든 표는 user_id 외래키 ON DELETE CASCADE(D-004).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_logs_user_created", "ai_usage_logs", ["user_id", "created_at"], unique=False)

    op.create_table(
        "quizzes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("choices", sa.JSON(), nullable=False),
        sa.Column("answer_index", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=False),
        sa.Column("quote_end", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id", name="uq_quizzes_chunk_id"),
    )
    op.create_index("ix_quizzes_user_id", "quizzes", ["user_id"], unique=False)
    op.create_index("ix_quizzes_note_id", "quizzes", ["note_id"], unique=False)

    op.create_table(
        "note_quiz_claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", name="uq_note_quiz_claims_note_id"),
    )
    op.create_index("ix_note_quiz_claims_user_id", "note_quiz_claims", ["user_id"], unique=False)

    op.create_table(
        "quiz_reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("next_review_on", sa.Date(), nullable=False),
        sa.Column("interval_step", sa.Integer(), nullable=False),
        sa.Column("correct_streak", sa.Integer(), nullable=False),
        sa.Column("in_wrong_notes", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quiz_id", name="uq_quiz_reviews_quiz_id"),
    )
    op.create_index("ix_quiz_reviews_user_next", "quiz_reviews", ["user_id", "next_review_on"], unique=False)

    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("chosen_index", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_attempts_user_id", "quiz_attempts", ["user_id"], unique=False)
    op.create_index("ix_quiz_attempts_quiz_id", "quiz_attempts", ["quiz_id"], unique=False)

    op.create_table(
        "quiz_generation_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("chunks_sent", sa.Integer(), nullable=False),
        sa.Column("kept", sa.Integer(), nullable=False),
        sa.Column("dropped", sa.Integer(), nullable=False),
        sa.Column("drop_reasons", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_generation_logs_user_id", "quiz_generation_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("quiz_generation_logs")
    op.drop_table("quiz_attempts")
    op.drop_table("quiz_reviews")
    op.drop_table("note_quiz_claims")
    op.drop_table("quizzes")
    op.drop_table("ai_usage_logs")
