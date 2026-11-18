"""평가 한 번에 돌리기 · 회차 요약 테스트 (F-010 완료 기준 2).

평가 자체(AI)는 돌리지 않는다 — 가짜 러너가 결과 파일을 써 주고, 요약이 대표 수치 · 판정 대기 · 실패를 맞게 남기는지 본다.
"""

import json
from pathlib import Path

from app.services.eval_report import (
    STEP_BY_KEY,
    STEPS,
    headline,
    list_summaries,
    parse_result_path,
    step_entry,
)
from scripts import eval_all

OPTIONS = eval_all.Options(provider="nvidia", only=(), pause=3.0, retries=2, retry_wait=60.0, allow_mock=False)
SIZES = {"quiz_notes": 1}


def test_parse_result_path() -> None:
    assert parse_result_path("결과 파일: eval/quiz/results/quiz-x.json\n") == "eval/quiz/results/quiz-x.json"
    assert parse_result_path("  결과 파일:   a.json  ") == "a.json"
    assert parse_result_path("결과 파일:") is None
    assert parse_result_path("사용량: {...}") is None


def test_headline_hides_label_metrics_while_pending() -> None:
    step = STEP_BY_KEY["drafts_ai"]
    summary = {"warn_rate": 0.8, "needs_check_not_fabricated": 5, "unsupported_per_draft": 0.58, "labels_pending": 3}
    metrics, pending = headline(step, summary)
    assert pending == 3
    by_key = {m["key"]: m["value"] for m in metrics}
    assert by_key == {"warn_rate": None, "needs_check_not_fabricated": None, "unsupported_per_draft": 0.58}

    metrics, pending = headline(step, {**summary, "labels_pending": 0})
    assert pending == 0
    assert {m["key"]: m["value"] for m in metrics}["warn_rate"] == 0.8


def test_headline_ignores_missing_or_non_numbers() -> None:
    metrics, _ = headline(STEP_BY_KEY["quiz"], {"drop_rate": 0.02, "answer_match_rate": None, "explanation_match_rate": True})
    assert [m["value"] for m in metrics] == [0.02, None, None]


def test_step_entry_failed_and_partial() -> None:
    step = STEP_BY_KEY["cards"]
    failed = step_entry(step, result_file=None, payload=None, error="종료 코드 1")
    assert failed["status"] == "failed" and failed["metrics"] == [] and failed["error"] == "종료 코드 1"
    partial = step_entry(step, result_file="r.json", payload={"model": "m", "complete": False, "summary": {"found_rate": 0.5}}, error=None)
    assert partial["status"] == "partial" and partial["model"] == "m"


def test_build_command_planted_and_ai() -> None:
    planted = eval_all.build_command(STEP_BY_KEY["drafts_planted"], OPTIONS)
    assert planted[-2:] == ["scripts.draft_eval", "--planted"]
    ai = eval_all.build_command(STEP_BY_KEY["drafts_ai"], OPTIONS)
    assert ai[2:4] == ["scripts.draft_eval", "nvidia"] and "--planted" not in ai and "--allow-mock" not in ai
    assert ai[ai.index("--pause") + 1] == "3.0"


def _fake_runner(tmp_path: Path, summaries: dict[str, dict[str, object]], *, fail: set[str] = frozenset()):  # type: ignore[assignment]
    calls: list[list[str]] = []

    def runner(command: list[str]) -> tuple[int, str | None]:
        calls.append(command)
        module = command[2].removeprefix("scripts.")
        planted = "--planted" in command
        key = next(s.key for s in STEPS if s.module == module and s.planted == planted)
        if key in fail:
            return 1, None
        out = tmp_path / f"{key}.json"
        model = "none" if planted else "nemotron"
        out.write_text(json.dumps({"model": model, "summary": summaries.get(key, {})}), encoding="utf-8")
        return 0, str(out)

    return runner, calls


def test_run_all_writes_summary_and_goes_on_after_failure(tmp_path: Path) -> None:
    runner, calls = _fake_runner(tmp_path, {"quiz": {"drop_rate": 0.1}, "drafts_ai": {"warn_rate": 0.8, "labels_pending": 2}}, fail={"cards"})
    out = tmp_path / "summary" / "run-20261117-120000.json"
    out.parent.mkdir()
    summary = eval_all.run_all(OPTIONS, out, runner=runner, sizes=SIZES, commit=("abc1234", True))

    assert len(calls) == len(STEPS)  # 카드가 실패해도 끝까지
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved == summary
    assert saved["run_id"] == "20261117-120000" and saved["model"] == "nemotron" and saved["commit"] == "abc1234" and saved["dirty"]
    assert saved["finished_at"] is not None and saved["data"] == SIZES
    by_key = {e["key"]: e for e in saved["evals"]}
    assert by_key["cards"]["status"] == "failed"
    assert by_key["quiz"]["metrics"][0]["value"] == 0.1
    assert "\\" not in str(by_key["quiz"]["result_file"])  # 요약 파일 경로는 / 로(다른 OS에서도 읽힘)
    assert by_key["drafts_ai"]["labels_pending"] == 2 and by_key["drafts_ai"]["metrics"][0]["value"] is None
    assert list_summaries(out.parent) == [saved]


def test_run_all_only(tmp_path: Path) -> None:
    runner, calls = _fake_runner(tmp_path, {})
    options = eval_all.Options("nvidia", ("quiz", "interview_ai"), 3.0, 2, 60.0, False)
    summary = eval_all.run_all(options, tmp_path / "run-1.json", runner=runner, sizes=SIZES)
    assert [e["key"] for e in summary["evals"]] == ["quiz", "interview_ai"]  # type: ignore[index]
    assert len(calls) == 2


def test_rescore_updates_only_rescorable_entries(tmp_path: Path) -> None:
    runner, _ = _fake_runner(tmp_path, {"drafts_ai": {"warn_rate": 0.8, "labels_pending": 2}, "quiz": {"drop_rate": 0.1}})
    out = tmp_path / "run-1.json"
    eval_all.run_all(OPTIONS, out, runner=runner, sizes=SIZES)
    # 사람이 판정을 마쳤다고 치고 결과 파일을 바꾼다
    (tmp_path / "drafts_ai.json").write_text(json.dumps({"model": "nemotron", "summary": {"warn_rate": 0.75, "labels_pending": 0}}), encoding="utf-8")
    scored: list[list[str]] = []

    def score_runner(command: list[str]) -> tuple[int, str | None]:
        scored.append(command)
        return 0, None

    assert eval_all.rescore(out, runner=score_runner) == 0
    assert {c[2] for c in scored} == {"scripts.draft_eval", "scripts.interview_eval"} and all("--score" in c for c in scored)
    by_key = {e["key"]: e for e in json.loads(out.read_text(encoding="utf-8"))["evals"]}
    assert by_key["drafts_ai"]["metrics"][0]["value"] == 0.75 and by_key["drafts_ai"]["labels_pending"] == 0
    assert by_key["quiz"]["metrics"][0]["value"] == 0.1  # 다시 채점 안 하는 칸은 그대로


def test_rescore_reports_broken_summary(tmp_path: Path) -> None:
    broken = tmp_path / "run-x.json"
    broken.write_text("{not json", encoding="utf-8")
    assert eval_all.rescore(broken, runner=lambda c: (0, None)) == 1


def test_list_summaries_skips_broken_and_other_versions(tmp_path: Path) -> None:
    (tmp_path / "run-1.json").write_text("{broken", encoding="utf-8")
    (tmp_path / "run-2.json").write_text(json.dumps({"version": 999}), encoding="utf-8")
    (tmp_path / "run-3.json").write_text(json.dumps({"version": 1, "run_id": "3"}), encoding="utf-8")
    assert [r["run_id"] for r in list_summaries(tmp_path)] == ["3"]
    assert list_summaries(tmp_path / "없음") == []


def test_data_sizes_match_d005_scale() -> None:
    sizes = eval_all.data_sizes()
    assert sizes["experiences"] == 20 and sizes["postings"] == 10 and sizes["draft_questions"] == 20
    assert sizes["quiz_notes"] == 10


def test_readme_table_and_block(tmp_path: Path) -> None:
    from app.services.eval_report import README_END, README_START

    run = {
        "version": 1, "run_id": "20261117-1", "started_at": "2026-11-17T10:00:00+09:00", "model": "ultra",
        "data": {"experiences": 20, "postings": 10},
        "evals": [
            {"title": "퀴즈", "status": "ok", "labels_pending": 0,
             "metrics": [{"label": "버려진 문제 비율", "kind": "rate", "value": 0.02}]},
            {"title": "자소서 · AI 초안", "status": "ok", "labels_pending": 2,
             "metrics": [{"label": "지어낸 문장 경고율", "kind": "rate", "value": None},
                         {"label": "초안당 근거 없는 문장", "kind": "per", "value": 0.583}]},
            {"title": "경험 카드", "status": "failed", "labels_pending": 0, "metrics": []},
        ],
    }
    (tmp_path / "summary").mkdir()
    (tmp_path / "summary" / "run-20261117-1.json").write_text(json.dumps(run), encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(f"# 디딤\n\n사람이 쓴 글\n\n{README_START}\n옛 표\n{README_END}\n\n끝\n", encoding="utf-8")

    assert eval_all.update_readme(readme, tmp_path / "summary") == 0
    text = readme.read_text(encoding="utf-8")
    assert "사람이 쓴 글" in text and text.endswith("\n끝\n") and "옛 표" not in text
    assert "회차 2026-11-17 · 모델 ultra · 심은 경험 20개 · 공고 10개" in text
    assert "| 퀴즈 | 버려진 문제 비율 | 2.0% |" in text
    assert "| 자소서 · AI 초안 | 지어낸 문장 경고율 | 판정 대기 |" in text
    assert "| 자소서 · AI 초안 | 초안당 근거 없는 문장 | 0.58 |" in text
    assert "| 경험 카드 | — | 이번 회차에 돌리지 못함 |" in text

    no_marker = tmp_path / "NO.md"
    no_marker.write_text("# 표시 없음\n", encoding="utf-8")
    assert eval_all.update_readme(no_marker, tmp_path / "summary") == 1
    assert no_marker.read_text(encoding="utf-8") == "# 표시 없음\n"  # 그대로
    assert eval_all.update_readme(readme, tmp_path / "없음") == 1


def test_resume_skips_ok_steps_and_reruns_the_rest(tmp_path: Path) -> None:
    runner, _ = _fake_runner(tmp_path, {"quiz": {"drop_rate": 0.0}}, fail={"postings"})
    out = tmp_path / "run-1.json"
    first = eval_all.run_all(OPTIONS, out, runner=runner, sizes=SIZES)
    assert {e["key"]: e["status"] for e in first["evals"]}["postings"] == "failed"  # type: ignore[index]

    # 컴퓨터가 꺼진 것처럼: 앞 두 단계만 남은 요약
    saved = json.loads(out.read_text(encoding="utf-8"))
    saved["evals"] = saved["evals"][:3]  # quiz ok · cards ok · postings failed
    saved["finished_at"] = None
    assert eval_all.resume_problem(saved, OPTIONS, SIZES) is None

    runner2, calls2 = _fake_runner(tmp_path, {"quiz": {"drop_rate": 0.5}})
    summary = eval_all.run_all(OPTIONS, out, runner=runner2, sizes=SIZES, resume=saved)
    ran = [c[2] for c in calls2]
    assert "scripts.quiz_eval" not in ran and "scripts.card_eval" not in ran  # ok는 건너뜀
    assert ran.count("scripts.posting_eval") == 1  # 실패한 단계는 다시
    keys = [e["key"] for e in summary["evals"]]  # type: ignore[index]
    assert keys == [step.key for step in STEPS]  # 정해진 순서
    by_key = {e["key"]: e for e in summary["evals"]}  # type: ignore[index]
    assert by_key["quiz"]["metrics"][0]["value"] == 0.0  # 앞 회차 값 그대로
    assert by_key["postings"]["status"] == "ok"
    assert summary["run_id"] == "1" and summary["resumed_at"] and summary["finished_at"]


def test_resume_refuses_other_data_or_provider() -> None:
    base = {"version": 1, "data": SIZES, "provider": "nvidia", "evals": []}
    assert eval_all.resume_problem(base, OPTIONS, {"quiz_notes": 2}) is not None
    assert eval_all.resume_problem({**base, "provider": "exaone"}, OPTIONS, SIZES) is not None
    assert eval_all.resume_problem({**base, "evals": None}, OPTIONS, SIZES) is not None


def test_resume_with_only_reruns_that_step(tmp_path: Path) -> None:
    runner, _ = _fake_runner(tmp_path, {"postings": {"match_hit_rate": 0.8}})
    out = tmp_path / "run-1.json"
    eval_all.run_all(OPTIONS, out, runner=runner, sizes=SIZES)
    saved = json.loads(out.read_text(encoding="utf-8"))

    runner2, calls2 = _fake_runner(tmp_path, {"postings": {"match_hit_rate": 0.9}})
    only = eval_all.Options("nvidia", ("postings",), 3.0, 2, 60.0, False)
    summary = eval_all.run_all(only, out, runner=runner2, sizes=SIZES, resume=saved)
    assert [c[2] for c in calls2] == ["scripts.posting_eval"]  # 고른 단계만 다시
    by_key = {e["key"]: e for e in summary["evals"]}  # type: ignore[index]
    assert by_key["postings"]["metrics"][0]["value"] == 0.9
    assert [e["key"] for e in summary["evals"]] == [s.key for s in STEPS]  # type: ignore[index]


# --- F-010 1차 리뷰 반영 ---


def test_failed_rescore_keeps_the_previous_numbers(tmp_path: Path) -> None:
    """다시 채점이 실패하면 이전 수치를 지우지 않는다(R3)."""
    runner, _ = _fake_runner(tmp_path, {"drafts_ai": {"warn_rate": 0.8, "labels_pending": 0}})
    out = tmp_path / "run-1.json"
    eval_all.run_all(OPTIONS, out, runner=runner, sizes=SIZES)
    assert eval_all.rescore(out, runner=lambda command: (1, None)) == 1
    by_key = {e["key"]: e for e in json.loads(out.read_text(encoding="utf-8"))["evals"]}
    assert by_key["drafts_ai"]["status"] == "ok" and by_key["drafts_ai"]["metrics"][0]["value"] == 0.8


def test_rescore_skips_entries_that_are_not_objects(tmp_path: Path) -> None:
    path = tmp_path / "run-x.json"
    path.write_text(json.dumps({"version": 1, "evals": ["이상한 칸"]}), encoding="utf-8")
    assert eval_all.rescore(path, runner=lambda command: (0, None)) == 0
    path.write_text(json.dumps({"version": 1, "evals": "목록 아님"}), encoding="utf-8")
    assert eval_all.rescore(path, runner=lambda command: (0, None)) == 1


def test_collect_failure_paths(tmp_path: Path) -> None:
    """결과를 못 읽는 경우마다 'failed'와 이유를 남긴다(R3)."""
    step = STEP_BY_KEY["quiz"]
    assert eval_all.collect(step, 0, None)["error"] == "결과 파일 경로를 받지 못했어요."
    assert "읽지 못했어요" in str(eval_all.collect(step, 0, str(tmp_path / "없음.json"))["error"])
    broken = tmp_path / "broken.json"
    broken.write_text("{깨짐", encoding="utf-8")
    assert eval_all.collect(step, 0, str(broken))["status"] == "failed"
    not_object = tmp_path / "list.json"
    not_object.write_text("[1, 2]", encoding="utf-8")
    assert eval_all.collect(step, 0, str(not_object))["error"] == "결과 파일 모양이 달라요."
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"model": "m", "summary": {"drop_rate": 0.1}}), encoding="utf-8")
    entry = eval_all.collect(step, 1, str(good))  # 결과는 있지만 종료 코드 1
    assert entry["status"] == "failed" and entry["error"] == "종료 코드 1"


def test_run_all_goes_on_when_a_process_cannot_start(tmp_path: Path) -> None:
    """하위 프로세스를 띄우지 못해도(OSError) 그 단계만 실패로 두고 계속한다(R3)."""
    runner, _ = _fake_runner(tmp_path, {})

    def flaky(command: list[str]) -> tuple[int, str | None]:
        if command[2] == "scripts.quiz_eval":
            raise FileNotFoundError("python 없음")
        return runner(command)

    summary = eval_all.run_all(OPTIONS, tmp_path / "run-1.json", runner=flaky, sizes=SIZES)
    by_key = {e["key"]: e for e in summary["evals"]}  # type: ignore[index]
    assert by_key["quiz"]["status"] == "failed" and len(summary["evals"]) == len(STEPS)  # type: ignore[arg-type]


def test_resume_clears_finished_at_until_done(tmp_path: Path) -> None:
    """이어 하는 동안 요약은 '끝나지 않음' — 다시 멈춰도 끝난 회차로 보이지 않는다(R3)."""
    out = tmp_path / "run-1.json"
    saved = {"version": 1, "run_id": "1", "data": SIZES, "provider": "nvidia", "finished_at": "2026-11-17T00:00:00+09:00", "evals": []}
    seen: list[object] = []

    def watching(command: list[str]) -> tuple[int, str | None]:
        seen.append(json.loads(out.read_text(encoding="utf-8"))["finished_at"] if out.exists() else saved["finished_at"])
        return 1, None

    only = eval_all.Options("nvidia", ("quiz", "cards"), 3.0, 2, 60.0, False)
    eval_all.run_all(only, out, runner=watching, sizes=SIZES, resume=saved)
    assert seen[-1] is None  # 두 번째 단계를 돌 때 파일의 finished_at은 비어 있다


def test_rescore_goes_on_when_a_process_cannot_start(tmp_path: Path) -> None:
    """다시 채점에서 하위 프로세스를 못 띄워도 그 칸만 실패로 두고(이전 수치 유지) 나머지는 계속한다(2차 R3)."""
    runner, _ = _fake_runner(tmp_path, {"drafts_ai": {"warn_rate": 0.8}, "interview_ai": {"premise_rate": 0.0}})
    out = tmp_path / "run-1.json"
    eval_all.run_all(OPTIONS, out, runner=runner, sizes=SIZES)
    calls: list[str] = []

    def flaky(command: list[str]) -> tuple[int, str | None]:
        calls.append(command[2])
        if command[2] == "scripts.draft_eval":
            raise FileNotFoundError("python 없음")
        return 0, None

    assert eval_all.rescore(out, runner=flaky) == 1
    assert calls == ["scripts.draft_eval", "scripts.interview_eval"]  # 첫 칸이 실패해도 다음 칸을 채점
    saved = json.loads(out.read_text(encoding="utf-8"))
    by_key = {e["key"]: e for e in saved["evals"]}
    assert by_key["drafts_ai"]["metrics"][0]["value"] == 0.8 and saved["rescored_at"]
