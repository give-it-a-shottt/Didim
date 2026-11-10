"""DB 구조 버전 확인 (D-015).

DB 구조는 Alembic 버전 파일(backend/migrations/versions/)로만 바꾼다. 서버는 테이블을 직접 만들지 않고,
시작할 때 "DB가 최신 버전인지"만 확인한다. 아니면 무엇을 실행해야 하는지 적은 오류로 멈춘다
(구조가 안 맞는 채로 떠서 요청마다 500이 나는 것보다 시작 때 바로 알 수 있게).

오류는 상황별로 나눈다. 안내가 다르기 때문이다.
- DatabaseUnavailableError: DB에 연결이 안 됨 → DB가 켜져 있는지 확인
- DatabaseNotMigratedError: DB가 코드보다 뒤처짐(버전 기록 없음 포함) → `alembic upgrade head`
- DatabaseAheadOfCodeError: DB가 코드보다 앞섬(코드가 모르는 버전) → upgrade로는 못 고침, 코드를 최신으로

파일 이름이 `migrations`가 아닌 이유: backend/migrations/(Alembic 실행 환경)와 헷갈리지 않게.
"""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"
UPGRADE_COMMAND = "uv run --env-file .env alembic upgrade head"
STAMP_FIRST_VERSION_COMMAND = "uv run --env-file .env alembic stamp 0001"


class DatabaseSchemaError(RuntimeError):
    """서버 시작 때 DB 구조 확인이 실패했을 때의 공통 부모."""


class DatabaseUnavailableError(DatabaseSchemaError):
    """DB에 연결할 수 없다(서버 꺼짐 · 주소 오류). 메시지에 주소 · 비밀번호를 넣지 않는다."""


class DatabaseNotMigratedError(DatabaseSchemaError):
    """DB 구조가 코드의 최신 버전보다 뒤처져 있다(버전 기록이 없는 경우 포함)."""


class DatabaseAheadOfCodeError(DatabaseSchemaError):
    """DB에 코드가 모르는 버전이 기록되어 있다(새 코드로 올린 DB를 옛 코드로 여는 경우)."""


def alembic_config() -> Config:
    """backend/alembic.ini를 읽은 설정. 어느 폴더에서 실행해도 같은 파일을 가리킨다."""
    config = Config(str(ALEMBIC_INI_PATH))
    # 코드에서 부를 때는 alembic.ini의 로그 설정으로 앱 로그 설정을 덮어쓰지 않는다(migrations/env.py)
    config.attributes["configure_logger"] = False
    return config


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config())


def expected_heads() -> tuple[str, ...]:
    """코드(버전 파일)가 기대하는 최신 버전."""
    return tuple(sorted(_script_directory().get_heads()))


def known_revisions() -> frozenset[str]:
    """코드(버전 파일)가 아는 모든 버전 번호."""
    return frozenset(script.revision for script in _script_directory().walk_revisions())


def current_heads(engine: Engine) -> tuple[str, ...]:
    """DB에 기록된 현재 버전(alembic_version 테이블). 없으면 빈 값.

    연결이 안 되면 DatabaseUnavailableError. 드라이버 오류 문구에는 호스트 · 파일 경로가 들어 있어
    메시지에 옮기지 않고(원인은 `__cause__`로 남김), 확인할 것만 적는다.
    """
    try:
        with engine.connect() as connection:
            return tuple(sorted(MigrationContext.configure(connection).get_current_heads()))
    except OperationalError as exc:
        raise DatabaseUnavailableError(
            "DB에 연결할 수 없어요. DB가 켜져 있는지(레포 루트에서 `docker compose up -d db`), "
            "환경변수 DATABASE_URL의 주소 · 계정이 맞는지 확인해 주세요."
        ) from exc


def ensure_db_migrated(engine: Engine) -> None:
    """DB가 코드의 최신 버전과 같지 않으면 상황에 맞는 DatabaseSchemaError."""
    expected = expected_heads()
    current = current_heads(engine)
    if current == expected:
        return

    known = known_revisions()
    unknown = [revision for revision in current if revision not in known]
    if unknown:
        raise DatabaseAheadOfCodeError(
            f"DB가 이 코드보다 새 버전이에요(DB: {', '.join(unknown)}, 코드 최신: {', '.join(expected)}). "
            f"`{UPGRADE_COMMAND}`로는 고칠 수 없어요. 코드를 최신으로 받아 주세요. "
            f"옛 코드를 꼭 써야 하면 새 코드 쪽에서 `alembic downgrade {', '.join(expected)}`로 DB를 먼저 되돌려요."
        )
    raise DatabaseNotMigratedError(
        f"DB 구조가 최신이 아니에요(지금: {', '.join(current) or '버전 기록 없음'}, 필요: {', '.join(expected)}). "
        f"backend 폴더에서 `{UPGRADE_COMMAND}`를 실행해 주세요. "
        f"전에 create_all로 만든 DB라면 처음 한 번만 `{STAMP_FIRST_VERSION_COMMAND}`을 먼저 실행해요."
    )
