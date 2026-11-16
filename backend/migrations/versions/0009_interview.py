"""interview tables (interview questions, card interview claims, interview logs)

(첫 줄은 alembic이 터미널에 찍는다. Windows cp949에서 깨지지 않게 영문으로 쓴다, T-003)
면접 연습 (F-009 설계 의도 '데이터' — 사용자 확인 2026-11-13, 2026-11-15).

- interview_questions: 카드 칸별 꼬리 질문. 근거(칸 · 인용 · 인용 출처 · 위치) · 내 답 메모 · 답한 시각.
  카드를 지우면 같이 지운다(CASCADE). 카드 안 순서는 유니크((card_id, position) — card_id로 찾는 색인도 겸함).
- card_interview_claims: 카드별 [면접 질문 만들기] 선점(card_id 유니크, D-020). 끝나면 지운다.
- interview_logs: 평가 로그(D-005). card_id는 외래키 아님(로그는 남김).

모든 표는 user_id 외래키 ON DELETE CASCADE(D-004).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(length=16), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_source", sa.String(length=16), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=False),
        sa.Column("quote_end", sa.Integer(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_id", "position", name="uq_interview_questions_position"),
    )
    op.create_index("ix_interview_questions_user_id", "interview_questions", ["user_id"], unique=False)

    op.create_table(
        "card_interview_claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_id", name="uq_card_interview_claims_card_id"),
    )
    op.create_index("ix_card_interview_claims_user_id", "card_interview_claims", ["user_id"], unique=False)

    op.create_table(
        "interview_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("fields_sent", sa.Integer(), nullable=False),
        sa.Column("questions", sa.Integer(), nullable=False),
        sa.Column("kept", sa.Integer(), nullable=False),
        sa.Column("drop_reasons", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interview_logs_user_id", "interview_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("interview_logs")
    op.drop_table("card_interview_claims")
    op.drop_table("interview_questions")
