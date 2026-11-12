"""notion connections and notes.notion_page_id

(첫 줄은 alembic이 터미널에 찍는다. Windows cp949에서 깨지지 않게 영문으로 쓴다, T-003)
노션 연결 (F-005 설계 의도 '데이터' — 사용자 확인 2026-11-12).

- notion_connections: 사용자당 1줄(user_id 유니크, CASCADE). 워크스페이스, 접근 · 갱신 토큰(암호화), 만료 시각, 상태,
  가져오기 시작 시각(importing_since — 사용자당 가져오기 하나, 1차 리뷰 D).
- notes.notion_page_id: 노션에서 가져온 노트의 페이지 번호. (user_id, notion_page_id) 유니크 — 같은 페이지는 한 번만.
  마크다운 노트는 NULL이라 유니크에 걸리지 않는다(PostgreSQL · SQLite 모두 NULL끼리는 다르게 본다).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notion_connections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_name", sa.String(length=255), nullable=False),
        sa.Column("bot_id", sa.String(length=64), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("importing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    # 유니크 '제약' 대신 유니크 '색인'으로 둔다. SQLite에서 제약을 더하려면 표를 새로 만들어 옮기는데(batch),
    # 옛 표를 지울 때 ON DELETE CASCADE로 조각이 함께 지워졌다(test_migrations에서 발견). 색인은 표를 다시 만들지 않는다.
    op.add_column("notes", sa.Column("notion_page_id", sa.String(length=36), nullable=True))
    op.create_index("uq_notes_user_notion_page", "notes", ["user_id", "notion_page_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_notes_user_notion_page", table_name="notes")
    # batch(표 다시 만들기)를 쓰지 않는다 — SQLite에서 notes를 다시 만들면 CASCADE로 조각 · 문제 · 카드가 지워진다.
    # SQLite 3.35+와 PostgreSQL 모두 ALTER TABLE ... DROP COLUMN을 바로 지원한다.
    op.drop_column("notes", "notion_page_id")
    op.drop_table("notion_connections")
