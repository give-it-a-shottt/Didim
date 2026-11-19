"""배포 설정 테스트 (D-032) — Vercel의 상한(요청 4.5MB · 바깥 서버로 넘긴 요청 120초) 안에 들고, 운영에서 문서 경로가 꺼지는지."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from app.config import (
    BYTES_PER_MB,
    MAX_IMPORT_FILE_BYTES,
    MAX_IMPORT_REQUEST_BYTES,
    MAX_IMPORT_TOTAL_BYTES,
    NOTION_IMPORT_TIME_BUDGET_SECONDS,
    Settings,
    api_docs_urls,
)
from app.llm.settings import (
    DEFAULT_LLM_TIMEOUT_SECONDS,
    DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
VERCEL_REQUEST_BODY_LIMIT_BYTES = int(4.5 * BYTES_PER_MB)
VERCEL_EXTERNAL_REWRITE_TIMEOUT_SECONDS = 120
SAVE_MARGIN_SECONDS = 20  # AI가 끝난 뒤 저장할 여유(next.config.ts PROXY_TIMEOUT_MS 주석과 같은 값)
NOTION_OVERRUN_MARGIN_SECONDS = 40  # 노션 요청 하나가 예산을 넘칠 수 있는 여유(config.py 주석)


def test_import_request_fits_in_vercel_body_limit() -> None:
    assert MAX_IMPORT_TOTAL_BYTES == 3 * BYTES_PER_MB
    assert MAX_IMPORT_FILE_BYTES <= MAX_IMPORT_TOTAL_BYTES
    assert MAX_IMPORT_REQUEST_BYTES < VERCEL_REQUEST_BODY_LIMIT_BYTES


def test_every_long_request_fits_in_vercel_rewrite_timeout() -> None:
    """한 요청이 걸리는 시간이 모두 120초 안 — 넘으면 화면은 504인데 서버는 저장하는 일(T-005)."""
    assert DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS + SAVE_MARGIN_SECONDS <= VERCEL_EXTERNAL_REWRITE_TIMEOUT_SECONDS
    assert DEFAULT_LLM_TIMEOUT_SECONDS <= DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS
    assert NOTION_IMPORT_TIME_BUDGET_SECONDS + NOTION_OVERRUN_MARGIN_SECONDS <= VERCEL_EXTERNAL_REWRITE_TIMEOUT_SECONDS


def test_api_docs_urls(test_settings: Settings) -> None:
    assert api_docs_urls(test_settings) == {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    production = replace(test_settings, frontend_url="https://didim.example")
    assert api_docs_urls(production) == {"docs_url": None, "redoc_url": None, "openapi_url": None}


def test_vercel_entry_is_the_same_app() -> None:
    from app.main import app
    from index import app as entry

    assert entry is app
    assert (BACKEND_DIR / ".python-version").read_text(encoding="utf-8").strip() == "3.13"


def _run_app_check(env_overrides: dict[str, str], code: str) -> subprocess.CompletedProcess[str]:
    """앱은 불러올 때 환경변수로 정해져서(문서 경로 · 허용 목록 검사), 새 파이썬에서 불러 본다."""
    env = {k: v for k, v in os.environ.items() if k not in {"COOKIE_SECURE", "FRONTEND_URL", "GOOGLE_REDIRECT_URI", "ALLOWED_LOGIN_EMAILS"}}
    env.update(env_overrides)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
    )


def test_production_app_has_no_docs() -> None:
    """운영 환경변수로 실제 앱을 불러 /docs · /openapi.json이 404인지(완료 기준 3, 1차 리뷰 R3)."""
    code = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "client = TestClient(app)\n"  # with 없이 — 시작 처리(DB 확인)를 돌리지 않는다
        "print(client.get('/docs').status_code, client.get('/openapi.json').status_code, client.get('/redoc').status_code)\n"
    )
    production = _run_app_check({"FRONTEND_URL": "https://didim.example", "ALLOWED_LOGIN_EMAILS": "owner@example.com"}, code)
    assert production.returncode == 0, production.stderr
    assert production.stdout.split() == ["404", "404", "404"]
    local = _run_app_check({}, code)
    assert local.returncode == 0, local.stderr
    assert local.stdout.split() == ["200", "200", "200"]


def test_production_without_allowlist_fails_on_import() -> None:
    """운영인데 목록이 비면 앱을 불러오는 순간 멈춘다 — Vercel이 시작 처리(lifespan)를 건너뛰어도(1차 리뷰 R2)."""
    result = _run_app_check({"FRONTEND_URL": "https://didim.example"}, "import app.main")
    assert result.returncode != 0
    assert "LoginConfigError" in result.stderr and "ALLOWED_LOGIN_EMAILS" in result.stderr


def test_production_engine_does_not_hold_connections(tmp_path: Path) -> None:
    """운영 엔진은 NullPool — 함수가 놀 때 Supabase 풀러 연결을 쥐고 있지 않는다(1차 리뷰 R2)."""
    from sqlalchemy.pool import NullPool

    from app.db.session import create_db_engine

    url = f"sqlite:///{tmp_path / 'p.db'}"
    assert isinstance(create_db_engine(url, pooled=False).pool, NullPool)
    assert not isinstance(create_db_engine(url).pool, NullPool)
