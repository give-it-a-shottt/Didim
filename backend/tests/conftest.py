"""테스트 공통 설정 — 테스트가 어떤 DB를 쓰는지는 이 파일 한 곳에서만 정한다.

- 기본: SQLite(테스트마다 임시 파일). 빠르고 외부 준비가 필요 없다.
- PostgreSQL(D-008)로 돌리려면 TEST_DATABASE_URL에 **테스트 전용 DB**(이름이 `_test`로 끝남)를 준다.
  예) docker-compose의 didim_test, 호스트는 127.0.0.1(T-002). 테스트는 시작 · 끝에 그 DB의 테이블을 모두 지우므로,
  개발 DB(didim)를 가리키면 데이터가 사라진다. 그래서 이름이 `_test`로 끝나지 않으면 바로 멈춘다.
"""

import os
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

TEST_DB_NAME_SUFFIX = "_test"


def _read_postgres_test_url() -> str:
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not url:
        return ""
    database = make_url(url).database or ""
    if not database.endswith(TEST_DB_NAME_SUFFIX):
        pytest.exit(
            f"TEST_DATABASE_URL의 DB 이름은 '{TEST_DB_NAME_SUFFIX}'로 끝나야 해요(지금: '{database}'). "
            "테스트는 그 DB의 테이블을 모두 지우므로 개발 · 운영 DB를 쓰면 안 돼요."
        )
    return url


POSTGRES_TEST_URL = _read_postgres_test_url()

# 앱은 DATABASE_URL이 없으면 시작하지 않는다. 셸에 개발용 DATABASE_URL이 있어도 테스트가 그 DB를
# 건드리지 않도록 항상 덮어쓴다. (서버 시작 단계의 init_db만 이 값을 쓰고, 요청은 아래 db_session을 쓴다.)
os.environ["DATABASE_URL"] = POSTGRES_TEST_URL or "sqlite://"


@pytest.fixture()
def test_db_url_guard() -> Callable[[], str]:
    """위 가드 함수를 테스트에 넘겨준다(test_db_config.py에서 가드가 제대로 막는지 확인할 때 씀).

    테스트 파일이 `from conftest import ...`로 직접 가져오면 tests/__init__.py가 생기거나
    pytest import 방식이 바뀔 때 깨질 수 있다. fixture는 pytest가 이어 주므로 그런 변화에 영향을 받지 않는다.
    """
    return _read_postgres_test_url


@pytest.fixture()
def db_session(tmp_path: Path) -> Generator[Session, None, None]:
    """테스트마다 깨끗한 DB 세션. PostgreSQL이면 테스트 전용 DB, 아니면 임시 SQLite 파일."""
    from app.db.base import Base
    from app.db.session import create_db_engine

    db_url = POSTGRES_TEST_URL or f"sqlite:///{tmp_path / 'test_didim.db'}"
    engine = create_db_engine(db_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        if POSTGRES_TEST_URL:
            Base.metadata.drop_all(bind=engine)
        engine.dispose()
