from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import load_settings


def create_db_engine(database_url: str) -> Engine:
    """DB 엔진을 만든다. SQLite를 쓸 때는 외래키(ON DELETE CASCADE)가 동작하도록 PRAGMA를 켠다."""
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(database_url, connect_args=connect_args, future=True)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_session_factory() -> sessionmaker[Session]:
    global _engine, _session_factory
    if _session_factory is None:
        settings = load_settings()
        _engine = create_db_engine(settings.database_url)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return _session_factory


def init_db() -> None:
    """앱 시작 시 1주차 테이블(users, notes, chunks)이 없으면 생성한다."""
    from app.db.base import Base
    import app.db.models  # noqa: F401 — 모델 등록 보장

    get_session_factory()
    if _engine is not None:
        Base.metadata.create_all(bind=_engine)


def get_db() -> Generator[Session, None, None]:
    """요청마다 세션을 열고, 끝나면 닫는다."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()
