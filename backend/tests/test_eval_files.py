"""평가 결과 파일 쓰기(scripts/eval_files.py) — 쓰다 실패해도 원래 파일(사람 판정)이 남는지. F-008 · F-009 평가가 같이 쓴다."""

from pathlib import Path

import pytest

from scripts.eval_files import PROVIDER_HELP, write_json_atomic


def test_write_json_keeps_the_old_file_when_replacing_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "result.json"
    out.write_text('{"human": "직접 적은 판정"}', encoding="utf-8")

    def broken_replace(self: Path, target: Path) -> Path:
        raise OSError("디스크 오류")

    monkeypatch.setattr(Path, "replace", broken_replace)
    with pytest.raises(OSError):
        write_json_atomic(out, {"new": True})
    assert out.read_text(encoding="utf-8") == '{"human": "직접 적은 판정"}'
    assert list(tmp_path.iterdir()) == [out]  # 임시 파일을 남기지 않는다


def test_write_json_does_not_touch_the_file_when_the_payload_cannot_be_written(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    out.write_text("원본", encoding="utf-8")
    with pytest.raises(TypeError):
        write_json_atomic(out, {"bad": object()})
    assert out.read_text(encoding="utf-8") == "원본"
    assert list(tmp_path.iterdir()) == [out]


def test_provider_help_lists_every_real_provider() -> None:
    assert "nvidia" in PROVIDER_HELP and "exaone" in PROVIDER_HELP and "mock" not in PROVIDER_HELP
