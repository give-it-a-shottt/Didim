"""평가 스크립트가 같이 쓰는 도우미(F-008 자소서 · F-009 면접 질문 평가) — 결과 파일 쓰기 · 명령줄 안내."""

import json
import os
import tempfile
from pathlib import Path

from app.llm.settings import LLM_PROVIDERS

# 실제 AI 제공자 목록(mock 빼고)에서 만든다 — 제공자가 늘어도 안내가 어긋나지 않게(F-009 4차 리뷰 R1 · R3 · R4)
REAL_PROVIDERS = " · ".join(name for name in LLM_PROVIDERS if name != "mock")
PROVIDER_HELP = f"{REAL_PROVIDERS} (빼면 LLM_PROVIDER 설정)"


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """같은 폴더의 임시 파일에 다 쓴 뒤 바꿔 끼운다 — 쓰다 멈춰도 원래 파일(사람 판정)이 그대로 남게(F-008 5차 리뷰 R3)."""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as tmp:
            tmp.write(text)
        Path(tmp_name).replace(path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
