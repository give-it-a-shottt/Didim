"""DB 설정이 비어 있을 때 조용히 다른 DB로 넘어가지 않고 멈추는지 확인한다(D-008, F-001 2차)."""

import pytest

from app.config import load_settings
from app.db.session import DatabaseConfigError, create_db_engine


def test_load_settings_has_no_default_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert load_settings().database_url == ""


def test_create_db_engine_rejects_empty_url() -> None:
    with pytest.raises(DatabaseConfigError, match="DATABASE_URL"):
        create_db_engine("")
