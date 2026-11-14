"""draft tables (drafts, draft sentences, draft logs)

(첫 줄은 alembic이 터미널에 찍는다. Windows cp949에서 깨지지 않게 영문으로 쓴다, T-003)
근거 달린 자소서 초안 (F-008 설계 의도 '데이터' — 사용자 확인 2026-11-13, 더한 칸 2026-11-14).

- drafts: 문항당 초안 하나(question_id 유니크). AI 원문(ai_text — '내가 고친 비율'용) · version(두 탭 동시 저장 막기) ·
  completed_at([이 문항 완료]).
- draft_sentences: 순서 · 글 · 출처(ai · edited · user) · AI 원래 문장 · 근거(카드 · 칸 · 인용 · 인용 출처 · 위치 ·
  누가 붙였는지). 카드를 지우면 card_id만 비운다(SET NULL — 인용은 남아 '카드 없음'으로 보임).
- draft_logs: 평가 로그(D-005). application_id · question_id는 외래키 아님(로그는 남김).

선점은 F-007의 application_claims를 그대로 쓴다(같은 공고에서 분석과 초안 쓰기가 동시에 돌지 않음, D-020).
모든 표는 user_id 외래키 ON DELETE CASCADE(D-004).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drafts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("ai_text", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["application_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", name="uq_drafts_question_id"),
    )
    op.create_index("ix_drafts_user_id", "drafts", ["user_id"], unique=False)
    op.create_index("ix_drafts_application_id", "drafts", ["application_id"], unique=False)

    op.create_table(
        "draft_sentences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("card_id", sa.Integer(), nullable=True),
        sa.Column("slot", sa.String(length=16), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("quote_source", sa.String(length=16), nullable=True),
        sa.Column("quote_start", sa.Integer(), nullable=True),
        sa.Column("quote_end", sa.Integer(), nullable=True),
        sa.Column("evidence_origin", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_id"], ["drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "position", name="uq_draft_sentences_position"),
    )
    op.create_index("ix_draft_sentences_user_id", "draft_sentences", ["user_id"], unique=False)
    op.create_index("ix_draft_sentences_card_id", "draft_sentences", ["card_id"], unique=False)

    op.create_table(
        "draft_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("cards_sent", sa.Integer(), nullable=False),
        sa.Column("sentences", sa.Integer(), nullable=False),
        sa.Column("supported", sa.Integer(), nullable=False),
        sa.Column("drop_reasons", sa.JSON(), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column("char_limit", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_draft_logs_user_id", "draft_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("draft_logs")
    op.drop_table("draft_sentences")
    op.drop_table("drafts")
