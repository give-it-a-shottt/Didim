"""application tables (applications, questions, requirements, matches, claims, analysis logs)

(첫 줄은 alembic이 터미널에 찍는다. Windows cp949에서 깨지지 않게 영문으로 쓴다, T-003)
공고 입력 · 요구 역량 추출 · 경험 매칭 (F-007 설계 의도 '데이터' — 사용자 확인 2026-11-12).

- applications: 지원(회사 · 직무 · 마감일 · URL 링크 · 붙여 넣은 공고 본문 · 상태). extracted_at · matched_at으로
  ① 역량 뽑기 · ② 매칭을 끝냈는지 본다(매칭 줄이 없는 역량이 '근거 없음'인지 '아직 안 함'인지 가르려고).
- application_questions: 자소서 문항 · 글자 수(F-008이 씀).
- posting_requirements: 역량 이름 · 필수/우대 · 공고 원문 인용과 위치.
- requirement_matches: 역량 ↔ 내 카드, 이유(AI) · 카드 칸 인용과 위치. 카드를 지우면 같이 지워진다.
- application_claims: 공고 분석 선점(D-020 — 사용자당 AI 작업 1개). ①과 ②가 같은 줄을 쓴다.
- posting_analysis_logs: 평가 로그(D-005). application_id는 외래키 아님(로그는 남김).

모든 표는 user_id 외래키 ON DELETE CASCADE(D-004).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("company", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("posting_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_applications_user_deadline", "applications", ["user_id", "deadline"], unique=False)

    op.create_table(
        "application_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_limit", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "position", name="uq_application_questions_position"),
    )
    op.create_index("ix_application_questions_user_id", "application_questions", ["user_id"], unique=False)

    op.create_table(
        "posting_requirements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=False),
        sa.Column("quote_end", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "position", name="uq_posting_requirements_position"),
    )
    op.create_index("ix_posting_requirements_user_id", "posting_requirements", ["user_id"], unique=False)

    op.create_table(
        "requirement_matches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("requirement_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(length=16), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_source", sa.String(length=16), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=False),
        sa.Column("quote_end", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_id"], ["posting_requirements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id", "card_id", name="uq_requirement_matches_card"),
    )
    op.create_index("ix_requirement_matches_user_id", "requirement_matches", ["user_id"], unique=False)
    op.create_index("ix_requirement_matches_card_id", "requirement_matches", ["card_id"], unique=False)

    op.create_table(
        "application_claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", name="uq_application_claims_application_id"),
    )
    op.create_index("ix_application_claims_user_id", "application_claims", ["user_id"], unique=False)

    op.create_table(
        "posting_analysis_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(length=16), nullable=False),
        sa.Column("items_sent", sa.Integer(), nullable=False),
        sa.Column("cards_sent", sa.Integer(), nullable=False),
        sa.Column("kept", sa.Integer(), nullable=False),
        sa.Column("drop_reasons", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_posting_analysis_logs_user_id", "posting_analysis_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("posting_analysis_logs")
    op.drop_table("application_claims")
    op.drop_table("requirement_matches")
    op.drop_table("posting_requirements")
    op.drop_table("application_questions")
    op.drop_table("applications")
