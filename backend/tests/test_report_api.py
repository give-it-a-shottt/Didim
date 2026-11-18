"""평가 리포트 API 테스트 (F-010 완료 기준 3) — 로그인 없이, 요약 파일만 읽는다."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import report

METRIC = {"key": "drop_rate", "label": "버려진 문제 비율", "kind": "rate", "value": 0.02}
PENDING = {"key": "warn_rate", "label": "지어낸 문장 경고율", "kind": "rate", "value": None}


def _run(run_id: str) -> dict[str, object]:
    return {
        "version": 1, "run_id": run_id, "started_at": "2026-11-17T10:00:00+09:00", "finished_at": None,
        "provider": "nvidia", "model": "nemotron", "commit": "abc1234", "dirty": False,
        "data": {"experiences": 20, "postings": 10},
        "evals": [
            {"key": "quiz", "title": "퀴즈", "status": "ok", "error": None, "model": "nemotron", "labels_pending": 0,
             "result_file": "eval/quiz/results/x.json", "metrics": [METRIC]},
            {"key": "drafts_ai", "title": "자소서 · AI 초안", "status": "ok", "error": None, "model": "nemotron",
             "labels_pending": 3, "result_file": "eval/drafts/results/y.json", "metrics": [PENDING]},
        ],
    }


@pytest.fixture()
def summary_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(report, "EVAL_SUMMARY_DIR", tmp_path)
    return tmp_path


def test_report_is_public_and_newest_first(client: TestClient, summary_dir: Path) -> None:
    for run_id in ["20261116-090000", "20261117-090000"]:
        (summary_dir / f"run-{run_id}.json").write_text(json.dumps(_run(run_id)), encoding="utf-8")
    client.cookies.clear()
    response = client.get("/api/report")
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert [r["run_id"] for r in runs] == ["20261117-090000", "20261116-090000"]
    drafts = runs[0]["evals"][1]
    assert drafts["labels_pending"] == 3 and drafts["metrics"][0]["value"] is None
    assert "result_file" not in runs[0]["evals"][0]  # 화면에 필요 없는 경로는 보내지 않는다


def test_report_skips_broken_runs(client: TestClient, summary_dir: Path) -> None:
    (summary_dir / "run-1.json").write_text(json.dumps(_run("1")), encoding="utf-8")
    bad = _run("2")
    bad["evals"] = "not a list"
    (summary_dir / "run-2.json").write_text(json.dumps(bad), encoding="utf-8")
    (summary_dir / "run-3.json").write_text("{broken", encoding="utf-8")
    assert [r["run_id"] for r in client.get("/api/report").json()["runs"]] == ["1"]


def test_report_keeps_latest_runs_only(client: TestClient, summary_dir: Path) -> None:
    for index in range(report.MAX_REPORT_RUNS + 2):
        (summary_dir / f"run-{index:02d}.json").write_text(json.dumps(_run(f"{index:02d}")), encoding="utf-8")
    runs = client.get("/api/report").json()["runs"]
    assert len(runs) == report.MAX_REPORT_RUNS and runs[0]["run_id"] == "11"


def test_report_without_runs(client: TestClient, summary_dir: Path) -> None:
    assert client.get("/api/report").json() == {"runs": []}
