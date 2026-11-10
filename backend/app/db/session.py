from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import DB_CONNECT_TIMEOUT_SECONDS, load_settings
from app.db.schema_version import ensure_db_migrated


class DatabaseConfigError(RuntimeError):
    """DATABASE_URL 환경변수가 비어 있을 때 발생한다."""


def create_db_engine(database_url: str) -> Engine:
    """DB 엔진을 만든다.

    운영 · 개발 DB는 PostgreSQL이다(D-008). SQLite는 테스트(tests/conftest.py)에서만 명시적으로 쓰고,
    그때도 외래키(ON DELETE CASCADE)가 동작하도록 PRAGMA를 켠다.
    """
    if not database_url:
        raise DatabaseConfigError(
            "환경변수 DATABASE_URL이 비어 있어요. 예) postgresql+psycopg://DB_USER:DB_PASSWORD@127.0.0.1:5432/didim "
            "(로컬 DB는 레포 루트의 docker-compose.yml로 띄워요)"
        )
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    elif database_url.startswith("postgresql"):
        connect_args["connect_timeout"] = DB_CONNECT_TIMEOUT_SECONDS

    # hide_parameters: DB 오류 메시지 · 로그에 INSERT 값(노트 원문 등 개인 기록)이 찍히지 않게 한다(F-002 1차 R2)
    engine = create_engine(database_url, connect_args=connect_args, future=True, hide_parameters=True)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """앱이 쓰는 엔진 하나. 처음 부를 때 환경변수 DATABASE_URL로 만들고, 이후는 같은 것을 돌려준다."""
    global _engine
    if _engine is None:
        _engine = create_db_engine(load_settings().database_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    return _session_factory


def dispose_engine() -> None:
    """엔진의 연결을 모두 닫고 잊는다. 서버가 꺼질 때 부른다(app/main.py).

    다음에 get_engine()을 부르면 그때의 DATABASE_URL로 새로 만든다.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def ensure_db_ready() -> None:
    """앱 시작 시 DB에 연결하고, 구조가 최신 버전인지 확인한다(D-015).

    서버는 테이블을 만들지 않는다. 구조는 Alembic 버전 파일로만 바꾸고(`alembic upgrade head`),
    최신이 아니면 실행할 명령을 적은 오류로 시작을 멈춘다(오류 종류는 app/db/schema_version.py).
    """
    ensure_db_migrated(get_engine())


def get_db() -> Generator[Session, None, None]:
    """요청마다 세션을 열고, 끝나면 닫는다."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()
