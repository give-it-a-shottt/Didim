"""experience card tables (cards, card_fields, note_card_claims, card_generation_logs)

(첫 줄은 alembic이 터미널에 찍는다. Windows cp949에서 깨지지 않게 영문으로 쓴다, T-003)
경험 카드 (F-006 설계 의도 '데이터' — 사용자 확인 2026-11-11).

- cards: 카드(제목 · 상태 candidate/saved). note_id는 SET NULL — 노트가 지워져도 사용자 답이 든 카드는 남음.
- card_fields: 카드마다 4줄(칸). 원문 인용 · 위치 · 조각(SET NULL), AI 빈칸 질문, 사용자 답을 따로 둔다.
  처음 계획한 card_evidence는 근거가 칸 단위라 여기에 합침. (card_id, slot) 유니크.
- note_card_claims: 노트별 [카드 후보 찾기] 선점(note_id 유니크) — note_quiz_claims 구조 + finished_at
  (찾기 끝남 = 이미 찾은 노트, 후보를 모두 버려도 남음 — 사용자 확인 2026-11-11).
- card_generation_logs: 후보 찾기 평가 로그. note_id는 외래키 아님(로그는 남김).

모든 표는 user_id 외래키 ON DELETE CASCADE(D-004).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cards_user_status", "cards", ["user_id", "status"], unique=False)
    op.create_index("ix_cards_note_id", "cards", ["note_id"], unique=False)

    op.create_table(
        "card_fields",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(length=16), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("quote_start", sa.Integer(), nullable=True),
        sa.Column("quote_end", sa.Integer(), nullable=True),
        sa.Column("chunk_id", sa.Integer(), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_id", "slot", name="uq_card_fields_card_slot"),
    )
    op.create_index("ix_card_fields_user_id", "card_fields", ["user_id"], unique=False)
    op.create_index("ix_card_fields_chunk_id", "card_fields", ["chunk_id"], unique=False)

    op.create_table(
        "note_card_claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", name="uq_note_card_claims_note_id"),
    )
    op.create_index("ix_note_card_claims_user_id", "note_card_claims", ["user_id"], unique=False)

    op.create_table(
        "card_generation_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("chunks_sent", sa.Integer(), nullable=False),
        sa.Column("candidates", sa.Integer(), nullable=False),
        sa.Column("quoted_fields", sa.Integer(), nullable=False),
        sa.Column("emptied_fields", sa.Integer(), nullable=False),
        sa.Column("drop_reasons", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_card_generation_logs_user_id", "card_generation_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("card_generation_logs")
    op.drop_table("note_card_claims")
    op.drop_table("card_fields")
    op.drop_table("cards")
