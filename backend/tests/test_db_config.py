"""DB 설정 안전장치 테스트 (D-008, F-001 2 · 3차 리뷰).

여기 있는 테스트는 기능이 아니라 "실수했을 때 조용히 넘어가지 않고 멈추는지"를 확인한다.
- DATABASE_URL이 비면 다른 DB(예: SQLite)로 몰래 넘어가지 않는다.
- 테스트용 DB 주소가 개발 DB를 가리키면 테스트를 시작하기 전에 멈춘다.
- PostgreSQL 연결에 시간 제한이 들어간다(없으면 연결이 무한 대기할 수 있음, T-002).
"""

from typing import Any

import pytest

from app.config import DB_CONNECT_TIMEOUT_SECONDS, load_settings
from app.db import session as db_session_module
from app.db.session import DatabaseConfigError, create_db_engine


def test_load_settings_has_no_default_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert load_settings().database_url == ""


def test_create_db_engine_rejects_empty_url() -> None:
    with pytest.raises(DatabaseConfigError, match="DATABASE_URL"):
        create_db_engine("")


def test_test_db_guard_stops_when_url_points_to_dev_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST_DATABASE_URL이 개발 DB(didim)를 가리키면 pytest가 바로 멈춰야 한다.

    왜 중요한가: 테스트는 시작 · 끝에 그 DB의 테이블을 모두 지운다(conftest.py의 drop_all).
    가드가 없으면 실수로 개발 DB 주소를 넣는 순간 개발 데이터가 사라진다.

    무엇을 하는가:
    1. 환경변수 TEST_DATABASE_URL을 이름이 `_test`로 끝나지 않는 DB(didim)로 바꾼다.
       monkeypatch라서 이 테스트가 끝나면 원래 값으로 돌아온다.
    2. conftest.py의 가드 함수 `_read_postgres_test_url()`을 직접 부른다.
       (DB에 실제로 붙지 않는다. 주소 문자열에서 DB 이름만 읽어 검사한다.)
    3. pytest.exit()가 던지는 예외(pytest.exit.Exception)가 나오는지,
       메시지에 지금 DB 이름(didim)이 들어 있는지 확인한다.

    이 테스트가 실패한다면: 가드가 지워졌거나, 이름 검사가 느슨해져 개발 DB로 테스트가 돌 수 있다는 뜻.
    """
    from conftest import _read_postgres_test_url  # tests/conftest.py (pytest가 tests 폴더를 경로에 넣어 줌)

    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql+psycopg://DB_USER:DB_PASSWORD@127.0.0.1:5432/didim"
    )

    with pytest.raises(pytest.exit.Exception, match="'didim'"):
        _read_postgres_test_url()


def test_create_db_engine_sets_connect_timeout_for_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    """PostgreSQL 엔진을 만들 때 connect_timeout(연결 시간 제한)이 들어가야 한다.

    왜 중요한가: Windows에서 localhost가 IPv6로 먼저 붙으면 psycopg 연결이 끝없이 기다렸다(T-002).
    시간 제한이 있으면 몇 초 뒤 에러로 끝나서 원인을 바로 알 수 있다.

    무엇을 하는가:
    1. app/db/session.py 안의 create_engine을 가짜 함수로 바꿔 끼운다(monkeypatch).
       가짜 함수는 엔진을 만들지 않고, 받은 인자만 `captured`에 적어 둔다.
       → 실제 PostgreSQL 서버가 없어도 테스트가 돈다.
    2. create_db_engine()에 PostgreSQL 주소를 넣어 부른다.
    3. create_engine에 넘어간 connect_args에 connect_timeout이 설정값(DB_CONNECT_TIMEOUT_SECONDS)
       그대로 들어갔는지 확인한다.

    이 테스트가 실패한다면: 누군가 connect_timeout을 지웠거나 PostgreSQL 주소 판별이 바뀌었다는 뜻.
    """
    captured: dict[str, Any] = {}

    def fake_create_engine(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()  # PostgreSQL 경로에서는 엔진에 이벤트를 걸지 않으므로 빈 객체로 충분

    monkeypatch.setattr(db_session_module, "create_engine", fake_create_engine)

    create_db_engine("postgresql+psycopg://DB_USER:DB_PASSWORD@127.0.0.1:5432/didim_test")

    assert captured["kwargs"]["connect_args"]["connect_timeout"] == DB_CONNECT_TIMEOUT_SECONDS
