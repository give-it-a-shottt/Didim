"""search: user+content GIN index (pg_trgm, btree_gin), search_logs table

(첫 줄은 alembic이 터미널에 찍는다. Windows cp949에서 깨지지 않게 영문으로 쓴다, T-003)
기록 검색 (F-003, 설계 의도 '데이터' — 사용자 확인, D-016 키워드 검색으로 시작).

- pg_trgm · btree_gin 확장 설치(PostgreSQL만) + chunks (user_id, content gin_trgm_ops) GIN 색인 하나.
  사용자 조건과 본문 비슷함을 한 색인으로 같이 거른다(1차 리뷰 뒤 실측으로 바꿈 · 사용자 확인). SQLite(테스트)에서는 보통 색인.
- search_logs: 검색마다 질문 · 방식 · 결과(조각 ID와 점수)를 남긴다(D-005 평가용).

확장을 설치하려면 DB 계정에 권한이 있어야 한다(로컬 docker의 기본 계정은 있음). 배포 DB는 Q-012 때 확인.
되돌리기(downgrade)는 색인 · 테이블만 지우고 확장은 남긴다(다른 곳에서 쓸 수 있고, 남아 있어도 해가 없음).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")

    op.create_index(
        "ix_chunks_user_content_trgm",
        "chunks",
        ["user_id", "content"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )

    op.create_table(
        "search_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_logs_user_id", "search_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("search_logs")
    op.drop_index("ix_chunks_user_content_trgm", table_name="chunks")
