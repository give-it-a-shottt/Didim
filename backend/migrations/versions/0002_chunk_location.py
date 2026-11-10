"""chunk location: heading_path, start_offset, end_offset

(첫 줄은 alembic이 터미널에 찍는다. Windows cp949에서 깨지지 않게 영문으로 쓴다, T-003)
조각 위치 컬럼 추가 (F-002, 설계 의도 '데이터' — 사용자 확인).

- heading_path: 조각이 속한 제목 경로. 예) "# React > ## useEffect"
- start_offset · end_offset: 노트 원문에서 조각의 시작 · 끝 글자 위치(content == note.content[start:end])

이미 조각이 있는 DB에서도 올릴 수 있게, 컬럼을 넣을 때만 임시 기본값('' · 0)을 주고 바로 지운다.
그런 옛 조각은 위치가 0~0으로 남는다(F-002 전에는 조각을 만드는 화면이 없어 실제 데이터는 없음, 2026-11-10 개발 DB 0건).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch: SQLite(테스트)는 ALTER가 제한적이라 표를 새로 만들어 옮긴다. PostgreSQL에서는 보통 ALTER로 돈다.
    with op.batch_alter_table("chunks") as batch:
        batch.add_column(sa.Column("heading_path", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("start_offset", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("end_offset", sa.Integer(), nullable=False, server_default="0"))

    # 임시 기본값은 지운다: 앞으로는 코드가 항상 실제 위치를 넣어야 한다(빠뜨리면 DB가 거절).
    with op.batch_alter_table("chunks") as batch:
        batch.alter_column("heading_path", server_default=None)
        batch.alter_column("start_offset", server_default=None)
        batch.alter_column("end_offset", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("chunks") as batch:
        batch.drop_column("end_offset")
        batch.drop_column("start_offset")
        batch.drop_column("heading_path")
