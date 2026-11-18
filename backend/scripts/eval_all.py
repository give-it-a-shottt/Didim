"""평가 한 번에 돌리기 — 가상 데이터 평가 5개를 같은 모델로 차례로 돌리고 회차 요약을 남긴다 (F-010 완료 기준 2, D-005).

backend 폴더에서:
    uv run --env-file .env python -m scripts.eval_all nvidia --pause 3              # 퀴즈 · 카드 · 매칭 · 자소서 · 면접 전부
    uv run --env-file .env python -m scripts.eval_all nvidia --pause 3 --only quiz  # 일부만(키는 쉼표로: quiz,cards,...)
    uv run --env-file .env python -m scripts.eval_all nvidia --pause 3 --resume eval/summary/run-<시각>.json  # 멈춘 회차 이어 하기
    uv run python -m scripts.eval_all --rescore eval/summary/run-<시각>.json        # 사람 판정을 적은 뒤 다시 채점(AI 안 부름)
    uv run python -m scripts.eval_all --readme                                      # README 표를 최근 회차로(표시 사이만 바꿈)

- 순서: 퀴즈 → 카드 → 매칭 → 자소서(심은 문장 · AI 초안) → 면접(심은 질문 · AI 질문). 기능별 스크립트를 그대로
  하위 프로세스로 돌린다(출력은 그대로 보이고, 하나가 실패해도 나머지는 계속 — 요약에 'failed'로 남음).
- 요약: eval/summary/run-<시각>.json(모델 · 날짜 · 커밋 · 데이터 규모 · 평가마다 결과 파일과 대표 수치). 단계가 끝날
  때마다 덮어써서 중간에 멈춰도 그때까지 남는다. 대표 수치 정의는 app/services/eval_report.py 한 곳.
- 자소서 · 면접의 AI 결과는 사람 판정(human)이 끝나야 최종 수치다. 판정 대기가 남은 수치는 요약에 null —
  결과 파일에 판정을 적고 --rescore로 다시 채점하면 요약도 바뀐다.
- 검색 평가는 내 실제 기록이라 묶지 않는다(README '참고 사례'). 키 · 주소는 출력하지 않는다. pytest에는 넣지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.services.eval_report import (
    EVAL_SUMMARY_DIR,
    STEP_BY_KEY,
    STEPS,
    SUMMARY_VERSION,
    EvalStep,
    list_summaries,
    parse_result_path,
    readme_table,
    replace_readme_block,
    step_entry,
)
from scripts.eval_files import PROVIDER_HELP, write_json_atomic

BACKEND_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BACKEND_DIR / "eval"
SUMMARY_DIR = EVAL_SUMMARY_DIR
README_PATH = BACKEND_DIR.parent / "README.md"

# (종료 코드, 결과 파일 경로) — 테스트에서 가짜로 바꿔 끼운다
Runner = Callable[[list[str]], tuple[int, str | None]]


@dataclass(frozen=True)
class Options:
    provider: str | None
    only: tuple[str, ...]
    pause: float
    retries: int
    retry_wait: float
    allow_mock: bool


def build_command(step: EvalStep, options: Options) -> list[str]:
    command = [sys.executable, "-m", f"scripts.{step.module}"]
    if step.planted:
        return [*command, "--planted"]
    if options.provider:
        command.append(options.provider)
    command += ["--pause", str(options.pause), "--retries", str(options.retries), "--retry-wait", str(options.retry_wait)]
    if options.allow_mock:
        command.append("--allow-mock")
    return command


def run_streaming(command: list[str]) -> tuple[int, str | None]:
    """스크립트를 돌리며 출력을 그대로 보이고, '결과 파일:' 줄의 경로를 받는다."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result_path: str | None = None
    with subprocess.Popen(
        command, cwd=BACKEND_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            result_path = parse_result_path(line) or result_path
        code = proc.wait()
    return code, result_path


def _load_result(result_path: str | None) -> tuple[dict[str, object] | None, str | None]:
    if result_path is None:
        return None, "결과 파일 경로를 받지 못했어요."
    path = Path(result_path)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"결과 파일을 읽지 못했어요: {type(exc).__name__}"
    if not isinstance(payload, dict):
        return None, "결과 파일 모양이 달라요."
    return payload, None


def collect(step: EvalStep, code: int, result_path: str | None) -> dict[str, object]:
    payload, error = _load_result(result_path)
    if code != 0 and error is None:
        error = f"종료 코드 {code}"
    # Windows 구분자로 남기지 않는다 — 요약 파일은 레포에 올라가 다른 OS에서도 읽힌다
    shown = Path(result_path).as_posix() if result_path else None
    return step_entry(step, result_file=shown, payload=payload, error=error)


def data_sizes(eval_dir: Path = EVAL_DIR) -> dict[str, int]:
    """이번 회차 평가 데이터 규모 — 리포트에 '무엇으로 잰 수치인지' 같이 보인다."""
    cards = json.loads((eval_dir / "cards" / "answers.json").read_text(encoding="utf-8"))
    postings = json.loads((eval_dir / "postings" / "answers.json").read_text(encoding="utf-8"))
    questions = json.loads((eval_dir / "drafts" / "questions.json").read_text(encoding="utf-8"))
    return {
        "quiz_notes": len(list((eval_dir / "quiz" / "notes").glob("*.md"))),
        "card_notes": len(cards["notes"]),
        "experiences": sum(len(note["experiences"]) for note in cards["notes"].values()),
        "postings": len(postings["postings"]),
        "requirements": sum(len(p["requirements"]) for p in postings["postings"].values()),
        "draft_questions": sum(len(qs) for qs in questions["questions"].values()),
    }


def git_commit() -> tuple[str | None, bool]:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BACKEND_DIR, capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=BACKEND_DIR, capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return None, False
    return commit or None, dirty


def run_model(evals: Sequence[dict[str, object]]) -> str | None:
    """회차의 AI 모델 — 심은 데이터 평가(model 'none')는 빼고 처음 나온 모델."""
    for entry in evals:
        model = entry.get("model")
        if isinstance(model, str) and model and model != "none":
            return model
    return None


def resume_problem(summary: dict[str, object], options: Options, sizes: dict[str, int]) -> str | None:
    """이어 하기를 막아야 하는 이유. 데이터 규모 · 제공자가 다르면 한 회차에 다른 조건의 수치가 섞인다."""
    if summary.get("version") != SUMMARY_VERSION or not isinstance(summary.get("evals"), list):
        return "요약 파일 모양이 달라요."
    if summary.get("data") != sizes:
        return "평가 데이터 규모가 처음 회차와 달라요. 새 회차로 돌려 주세요."
    if summary.get("provider") != options.provider:
        return f"처음 회차의 AI 제공자({summary.get('provider')})와 달라요."
    return None


def _ordered(evals: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    order = {step.key: index for index, step in enumerate(STEPS)}
    return sorted(evals, key=lambda entry: order.get(str(entry.get("key")), len(order)))


def run_all(options: Options, out: Path, *, runner: Runner = run_streaming, sizes: dict[str, int] | None = None,
            commit: tuple[str | None, bool] = (None, False), resume: dict[str, object] | None = None) -> dict[str, object]:
    """평가를 차례로 돌려 out에 요약을 쓴다. resume(같은 out의 이전 요약)이 있으면 'ok'인 단계는 건너뛰고 이어 쓴다."""
    evals: list[dict[str, object]] = []
    if resume is not None:
        summary = resume
        previous = resume.get("evals")
        evals = [e for e in previous if isinstance(e, dict) and e.get("status") == "ok"] if isinstance(previous, list) else []
        # --only로 고른 단계는 'ok'여도 다시 돌려 그 칸을 바꾼다(예: 결과 파일 모양을 바꾼 뒤 매칭만 다시)
        evals = [e for e in evals if str(e.get("key")) not in options.only]
        summary["resumed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    else:
        summary = {
            "version": SUMMARY_VERSION,
            "run_id": out.stem.removeprefix("run-"),
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "finished_at": None,
            "provider": options.provider,
            "model": None,
            "commit": commit[0],
            "dirty": commit[1],
            "data": sizes if sizes is not None else data_sizes(),
            "evals": [],
        }
    done = {str(entry.get("key")) for entry in evals}
    steps = [step for step in STEPS if (not options.only or step.key in options.only) and step.key not in done]
    if done:
        print(f"이미 끝난 단계는 건너뛰어요: {', '.join(sorted(done))}", flush=True)
    for index, step in enumerate(steps, start=1):
        print(f"\n=== [{index}/{len(steps)}] {step.title} ===", flush=True)
        code, result_path = runner(build_command(step, options))
        evals = _ordered([*evals, collect(step, code, result_path)])
        summary["evals"] = evals
        summary["model"] = run_model(evals)
        write_json_atomic(out, summary)
    summary["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_json_atomic(out, summary)
    return summary


def rescore(path: Path, *, runner: Runner = run_streaming) -> int:
    """사람 판정을 적은 자소서 · 면접 결과를 다시 채점하고 요약의 그 칸을 바꾼다. AI는 부르지 않는다."""
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
        evals = summary["evals"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"요약 파일 오류: {type(exc).__name__}")
        return 1
    failed = False
    for index, entry in enumerate(evals):
        step = STEP_BY_KEY.get(str(entry.get("key")))
        result_file = entry.get("result_file")
        if step is None or not step.rescorable or not isinstance(result_file, str):
            continue
        print(f"\n=== {step.title} 다시 채점 ===", flush=True)
        code, _ = runner([sys.executable, "-m", f"scripts.{step.module}", "--score", result_file])
        evals[index] = collect(step, code, result_file)
        failed = failed or evals[index]["status"] == "failed"
    summary["rescored_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_json_atomic(path, summary)
    return 1 if failed else 0


def update_readme(readme: Path, summary_dir: Path = SUMMARY_DIR) -> int:
    """README의 표시 사이에 최근 회차 표를 넣는다(리포트 화면과 같은 요약 파일). README의 다른 글은 건드리지 않는다."""
    runs = list_summaries(summary_dir)
    if not runs:
        print("요약 파일이 없어요. 먼저 평가를 돌려 주세요.")
        return 1
    try:
        text = readme.read_text(encoding="utf-8")
        readme.write_text(replace_readme_block(text, readme_table(runs[0])), encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"README 갱신 실패: {exc}")
        return 1
    print(f"README 표를 회차 {runs[0].get('run_id')}로 바꿨어요.")
    return 0


def print_summary(summary: dict[str, object]) -> None:
    print("\n=== 회차 요약 ===")
    evals = summary.get("evals")
    for entry in evals if isinstance(evals, list) else []:
        parts = []
        for metric in entry["metrics"]:
            value = metric["value"]
            if value is None:
                shown = "판정 대기" if entry["labels_pending"] else "-"
            elif metric["kind"] == "rate":
                shown = f"{value * 100:.1f}%"
            else:
                shown = f"{value}"
            parts.append(f"{metric['label']} {shown}")
        status = "" if entry["status"] == "ok" else f" [{entry['status']}: {entry.get('error') or '중간에 멈춤'}]"
        print(f"- {entry['title']}{status}: " + " · ".join(parts))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # Windows cp949 파이프 출력(T-003)
        sys.stdout.reconfigure(encoding="utf-8")
    keys = ",".join(step.key for step in STEPS)
    parser = argparse.ArgumentParser(description="평가 한 번에 돌리기(F-010 완료 기준 2)")
    parser.add_argument("provider", nargs="?", default=None, help=PROVIDER_HELP)
    parser.add_argument("--only", default="", help=f"일부만 돌리기(쉼표로): {keys}")
    parser.add_argument("--rescore", type=Path, default=None, help="사람 판정을 적은 뒤 요약 파일을 다시 채점(AI 안 부름)")
    parser.add_argument("--readme", action="store_true", help="README 표를 최근 회차 요약으로 바꾸기(AI 안 부름)")
    parser.add_argument("--resume", type=Path, default=None, help="멈춘 회차 이어 하기 — 'ok'인 단계는 건너뛰고 같은 요약 파일에 이어 씀")
    parser.add_argument("--allow-mock", action="store_true", help="흐름 확인용으로 mock도 허용(수치는 뜻 없음)")
    parser.add_argument("--pause", type=float, default=20.0, help="AI 호출 사이 최소 간격(초)")
    parser.add_argument("--retries", type=int, default=2, help="AI 서버 오류(500 · 429)면 다시 해 볼 횟수(0 이상)")
    parser.add_argument("--retry-wait", type=float, default=60.0, help="다시 해 보기 전에 쉬는 시간(초)")
    args = parser.parse_args()
    if args.readme:
        raise SystemExit(update_readme(README_PATH))
    if args.rescore is not None:
        raise SystemExit(rescore(args.rescore))
    if args.retries < 0 or args.pause < 0 or args.retry_wait < 0:
        parser.error("--retries · --pause · --retry-wait는 0 이상이어야 해요.")
    only = tuple(key.strip() for key in args.only.split(",") if key.strip())
    unknown = [key for key in only if key not in STEP_BY_KEY]
    if unknown:
        parser.error(f"모르는 평가 키: {', '.join(unknown)} (가능: {keys})")
    options = Options(args.provider, only, args.pause, args.retries, args.retry_wait, args.allow_mock)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    resume: dict[str, object] | None = None
    if args.resume is not None:
        out = args.resume
        try:
            resume = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            parser.error(f"요약 파일을 읽지 못했어요: {type(exc).__name__}")
        problem = resume_problem(resume, options, data_sizes()) if isinstance(resume, dict) else "요약 파일 모양이 달라요."
        if problem:
            parser.error(problem)
    else:
        out = SUMMARY_DIR / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    summary = run_all(options, out, commit=git_commit(), resume=resume)
    print_summary(summary)
    shown = out.resolve()  # --resume에 상대 경로를 넘겨도 깨지지 않게(2026-11-18 실제로 남)
    print(f"\n요약 파일: {shown.relative_to(BACKEND_DIR) if shown.is_relative_to(BACKEND_DIR) else shown}")
    evals = summary["evals"]
    raise SystemExit(1 if isinstance(evals, list) and any(e["status"] == "failed" for e in evals) else 0)


if __name__ == "__main__":
    main()
