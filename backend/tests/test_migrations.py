"""DB 마이그레이션 테스트 (D-015).

확인하는 것:
- 버전 파일을 처음부터 끝까지 적용한 DB가 모델(app/db/models.py)과 같은 구조인가
  → 모델만 고치고 버전 파일을 안 만들면 이 테스트가 실패한다.
- 되돌리기(downgrade)가 되는가
- 서버 시작 확인(app/db/schema_version.py)이 상황별로 맞는 안내를 내는가
  (버전 기록 없음 · create_all로 만든 DB · DB가 코드보다 앞섬 · DB 연결 안 됨)
- 서버가 DB가 최신이 아니면 멈추고, 최신이면 뜨고, DATABASE_URL이 없으면 멈추는가

다른 테스트는 속도를 위해 create_all로 테이블을 만든다. 이 파일만 실제 버전 파일을 실행한다.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text

from app.db import session as db_session_module
from app.db.base import Base
from app.db.schema_version import (
    STAMP_FIRST_VERSION_COMMAND,
    UPGRADE_COMMAND,
    DatabaseAheadOfCodeError,
    DatabaseNotMigratedError,
    DatabaseSchemaError,
    DatabaseUnavailableError,
    alembic_config,
    current_heads,
    ensure_db_migrated,
    expected_heads,
)
from app.db.session import DatabaseConfigError, create_db_engine, dispose_engine
from app.main import app

APP_TABLES = {
    "users",
    "notes",
    "chunks",
    "search_logs",
    "ai_usage_logs",
    "quizzes",
    "note_quiz_claims",
    "quiz_reviews",
    "quiz_attempts",
    "quiz_generation_logs",
}
FIRST_VERSION = "0001"


def _run_alembic(engine: Engine, operation: str, revision: str) -> None:
    """이미 열어 둔 연결로 alembic 명령을 실행한다(migrations/env.py가 이 연결을 그대로 씀)."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        getattr(command, operation)(config, revision)


def _table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_there_is_exactly_one_latest_version() -> None:
    """최신 버전이 두 갈래로 갈라지면(브랜치) upgrade head가 모호해진다."""
    assert len(expected_heads()) == 1


def test_upgrade_creates_same_structure_as_models(empty_db_engine: Engine) -> None:
    _run_alembic(empty_db_engine, "upgrade", "head")

    assert APP_TABLES <= _table_names(empty_db_engine)
    with empty_db_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    assert differences == [], f"모델과 버전 파일이 달라요. 버전 파일을 새로 만들어야 해요: {differences}"


def test_downgrade_removes_all_app_tables(empty_db_engine: Engine) -> None:
    _run_alembic(empty_db_engine, "upgrade", "head")
    _run_alembic(empty_db_engine, "downgrade", "base")

    assert APP_TABLES.isdisjoint(_table_names(empty_db_engine))
    assert current_heads(empty_db_engine) == ()


def test_chunk_location_upgrade_keeps_existing_chunks(empty_db_engine: Engine) -> None:
    """0002(조각 위치 컬럼)는 이미 있는 조각을 지우지 않는다. 옛 조각의 위치는 임시 기본값('' · 0)으로 남는다."""
    _run_alembic(empty_db_engine, "upgrade", FIRST_VERSION)
    with empty_db_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, google_sub, email, name, daily_limit, created_at) "
                "VALUES (1, 'sub-1', 'a@example.com', 'A', 30, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO notes (id, user_id, title, content, source, kind, content_hash, created_at, updated_at) "
                "VALUES (1, 1, 't', 'body', 'markdown', 'study', 'h', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO chunks (id, user_id, note_id, position, content, created_at) "
                "VALUES (1, 1, 1, 0, 'body', CURRENT_TIMESTAMP)"
            )
        )

    _run_alembic(empty_db_engine, "upgrade", "head")

    with empty_db_engine.connect() as connection:
        row = connection.execute(
            text("SELECT content, heading_path, start_offset, end_offset FROM chunks WHERE id = 1")
        ).one()
    assert tuple(row) == ("body", "", 0, 0)


def test_migrated_db_passes_the_check(empty_db_engine: Engine) -> None:
    _run_alembic(empty_db_engine, "upgrade", "head")
    ensure_db_migrated(empty_db_engine)  # 오류 없이 지나가야 한다
    assert current_heads(empty_db_engine) == expected_heads()


# --- 상황별 안내 -------------------------------------------------------------


def test_empty_db_is_reported_with_the_command_to_run(empty_db_engine: Engine) -> None:
    with pytest.raises(DatabaseNotMigratedError) as info:
        ensure_db_migrated(empty_db_engine)
    assert UPGRADE_COMMAND in str(info.value)
    assert "버전 기록 없음" in str(info.value)


def test_db_made_by_create_all_is_not_treated_as_migrated(empty_db_engine: Engine) -> None:
    """전에 create_all로 만든 DB는 테이블이 있어도 버전 기록이 없다 → 멈추고 stamp를 안내한다."""
    Base.metadata.create_all(bind=empty_db_engine)
    with pytest.raises(DatabaseNotMigratedError) as info:
        ensure_db_migrated(empty_db_engine)
    assert STAMP_FIRST_VERSION_COMMAND in str(info.value)


def test_old_create_all_db_reaches_latest_after_stamp_and_upgrade(empty_db_engine: Engine) -> None:
    """오류 문구가 안내하는 길: Alembic 전에 create_all로 만든 DB(= 0001 구조, 버전 기록 없음)는
    `stamp 0001` → (뒤처짐 안내) → `upgrade head` 순서로 최신이 된다."""
    _run_alembic(empty_db_engine, "upgrade", FIRST_VERSION)
    with empty_db_engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))  # 옛 create_all DB에는 버전 기록이 없었다

    with pytest.raises(DatabaseNotMigratedError, match="버전 기록 없음"):
        ensure_db_migrated(empty_db_engine)

    _run_alembic(empty_db_engine, "stamp", FIRST_VERSION)
    with pytest.raises(DatabaseNotMigratedError) as behind:
        ensure_db_migrated(empty_db_engine)  # 0001은 최신보다 뒤처져 있다
    assert f"지금: {FIRST_VERSION}" in str(behind.value)
    assert UPGRADE_COMMAND in str(behind.value)

    _run_alembic(empty_db_engine, "upgrade", "head")
    ensure_db_migrated(empty_db_engine)  # 오류 없이 지나가야 한다
    assert current_heads(empty_db_engine) == expected_heads()


def test_db_newer_than_code_is_reported_separately(empty_db_engine: Engine) -> None:
    """DB에 코드가 모르는 버전이 적혀 있으면 upgrade로 못 고친다 → 다른 안내를 낸다."""
    _run_alembic(empty_db_engine, "upgrade", "head")
    with empty_db_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999_future'"))

    with pytest.raises(DatabaseAheadOfCodeError) as info:
        ensure_db_migrated(empty_db_engine)
    assert "9999_future" in str(info.value)
    assert "새 버전" in str(info.value)
    assert f"`{UPGRADE_COMMAND}`를 실행해 주세요" not in str(info.value)


def test_unreachable_db_is_reported_without_its_address(tmp_path: Path) -> None:
    """DB에 연결이 안 되면(존재하지 않는 폴더의 SQLite = 드라이버 OperationalError) 안내 오류로 바꾼다.

    드라이버 오류 문구에는 파일 경로 · 호스트가 들어 있으므로, 우리 메시지에 옮겨지지 않았는지 함께 확인한다.
    """
    missing_dir = tmp_path / "no_such_dir"
    db_url = f"sqlite:///{missing_dir / 'didim.db'}"
    engine = create_db_engine(db_url)
    try:
        with pytest.raises(DatabaseUnavailableError) as info:
            ensure_db_migrated(engine)
    finally:
        engine.dispose()

    message = str(info.value)
    assert "DB가 켜져 있는지" in message
    assert str(missing_dir) not in message
    assert db_url not in message
    assert info.value.__cause__ is not None  # 원인은 디버깅용으로 남긴다


def test_schema_errors_share_one_parent() -> None:
    """서버 시작 코드가 한 종류로 잡을 수 있게 세 오류는 같은 부모를 가진다."""
    assert issubclass(DatabaseNotMigratedError, DatabaseSchemaError)
    assert issubclass(DatabaseAheadOfCodeError, DatabaseSchemaError)
    assert issubclass(DatabaseUnavailableError, DatabaseSchemaError)


# --- 서버 시작 ---------------------------------------------------------------


@pytest.fixture()
def startup_uses(monkeypatch: pytest.MonkeyPatch) -> Callable[[Engine], None]:
    """서버 시작 코드(ensure_db_ready)가 주어진 엔진을 쓰게 한다.

    session.get_engine()을 바꿔 끼운다. 시작 확인과 요청 처리가 같은 함수로 엔진을 얻으므로
    이 한 곳만 바꾸면 실제 lifespan 경로가 그대로 테스트 DB를 본다.
    """

    def _use(engine: Engine) -> None:
        monkeypatch.setattr(db_session_module, "get_engine", lambda: engine)

    return _use


@pytest.mark.real_startup_check
def test_server_refuses_to_start_when_db_is_not_migrated(
    empty_db_engine: Engine, startup_uses: Callable[[Engine], None]
) -> None:
    startup_uses(empty_db_engine)
    with pytest.raises(DatabaseNotMigratedError):
        with TestClient(app):
            pass


@pytest.mark.real_startup_check
def test_server_starts_when_db_is_migrated(empty_db_engine: Engine, startup_uses: Callable[[Engine], None]) -> None:
    _run_alembic(empty_db_engine, "upgrade", "head")
    startup_uses(empty_db_engine)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200


@pytest.mark.real_startup_check
def test_server_refuses_to_start_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """architecture.md 규칙: DATABASE_URL이 비면 서버가 시작하지 않는다 — lifespan 경로에서 확인."""
    monkeypatch.setenv("DATABASE_URL", "")
    # 아직 엔진을 만들지 않은 "처음 켜는" 상태로 되돌린다. 다음 get_engine()은 그때의 환경변수로 새로 만든다.
    dispose_engine()

    with pytest.raises(DatabaseConfigError):
        with TestClient(app):
            pass
