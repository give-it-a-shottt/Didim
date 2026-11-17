"""draft sentences: confirmed_claims

(첫 줄은 alembic이 터미널에 찍는다. Windows cp949에서 깨지지 않게 영문으로 쓴다, T-003)
자소서 문장 '확인 필요' 경고의 [확인함] (D-028, F-008 설계 의도 '확인 필요' — 사용자 선택 2026-11-16 · 17).

- confirmed_claims: [확인함]을 누를 때 걸려 있던 이유(예: "unknown_token:40|result_without_record"). 경고 자체는
  저장하지 않고 읽을 때 계산하며, 지금 이유가 이 값과 같을 때만 꺼진 것으로 본다 — 카드가 바뀌어 이유가 달라지면
  다시 경고한다(Q-029). 비어 있으면 확인 안 함. 문장 글이나 근거가 바뀌면 코드가 비운다.

비어 있어도 되는 칸이라 기존 문장이 있는 DB에서도 그대로 올라간다(옛 문장은 '확인 안 함').

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch: SQLite(테스트)는 ALTER가 제한적이라 표를 새로 만들어 옮긴다. PostgreSQL에서는 보통 ALTER로 돈다.
    with op.batch_alter_table("draft_sentences") as batch:
        batch.add_column(sa.Column("confirmed_claims", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("draft_sentences") as batch:
        batch.drop_column("confirmed_claims")
