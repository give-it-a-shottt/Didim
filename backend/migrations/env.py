"""Alembic 실행 환경 (D-015).

DB 주소는 alembic.ini가 아니라 환경변수 DATABASE_URL에서 읽는다(비밀값을 파일에 적지 않기 위해).
테스트 · 서버 코드가 이미 열어 둔 연결을 넘겨주면(config.attributes["connection"]) 그 연결을 그대로 쓴다.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

import app.db.models  # noqa: F401 — 모델을 등록해야 autogenerate가 테이블을 안다
from app.config import load_settings
from app.db.base import Base
from app.db.session import create_db_engine

config = context.config

# 명령 줄(alembic ...)로 돌릴 때만 로그 설정을 적용한다. 코드에서 부를 때는 앱의 로그 설정을 건드리지 않는다.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite는 ALTER TABLE이 제한적이라 테이블을 새로 만들어 옮기는 방식(batch)을 쓴다(테스트용)
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    # DATABASE_URL이 비어 있으면 create_db_engine이 이유를 적은 오류로 멈춘다
    engine = create_db_engine(load_settings().database_url)
    try:
        with engine.connect() as new_connection:
            _run(new_connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    # --sql(실행하지 않고 SQL만 출력) 방식은 쓰지 않는다. 필요해지면 그때 추가한다.
    raise SystemExit("offline 모드(--sql)는 지원하지 않아요. DB에 연결해서 실행해 주세요.")

run_migrations_online()
