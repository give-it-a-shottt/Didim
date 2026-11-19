"""평가 회차 요약 — 무엇을 어떤 이름으로 보여 줄지 한 곳에서 정한다 (F-010 완료 기준 2 · 3, D-005).

- 한 번에 돌리기(scripts/eval_all.py)가 기능별 결과 파일에서 대표 수치를 뽑아 eval/summary/run-<시각>.json에 쓰고,
  리포트 API(GET /api/report)와 README 표(scripts/eval_readme.py)는 그 요약 파일만 읽는다. 그래서 대표 수치 정의와
  표시 규칙(수치 → 글자, 데이터 칸 이름)은 여기 하나뿐이다 — 화면은 API가 내려 준 글자를 그대로 쓴다.
- 사람 판정이 필요한 수치(AI 초안의 지어낸 문장 · AI 면접 질문의 지어낸 전제)는 판정 대기(labels_pending)가 남아
  있으면 None으로 둔다 — 화면에 '판정 대기'로 보이게 하고 숫자를 지어내지 않는다(설계 원칙 1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MetricKind = Literal["rate", "count", "per"]

SUMMARY_VERSION = 1
RESULT_LINE_PREFIX = "결과 파일:"


@dataclass(frozen=True)
class MetricDef:
    key: str  # 결과 파일 summary의 키
    label: str
    kind: MetricKind
    needs_labels: bool = False  # 사람 판정이 끝나야 뜻이 있는 수치


@dataclass(frozen=True)
class EvalStep:
    key: str
    title: str
    module: str  # python -m scripts.<module>
    planted: bool  # AI를 안 부르는 심은 데이터 평가(--planted)
    metrics: tuple[MetricDef, ...]
    rescorable: bool = False  # --score로 다시 채점할 수 있는 결과(사람 판정)


# 실행 순서 = 화면 순서. 매칭 · 자소서 · 면접은 F-006 평가 노트로 AI 없이 만든 카드를 쓴다(앞 단계 결과에 기대지 않음).
STEPS: tuple[EvalStep, ...] = (
    EvalStep("quiz", "퀴즈", "quiz_eval", False, (
        MetricDef("drop_rate", "버려진 문제 비율", "rate"),
        MetricDef("answer_match_rate", "정답 일치율", "rate"),
        MetricDef("explanation_match_rate", "해설 일치율", "rate"),
    )),
    EvalStep("cards", "경험 카드", "card_eval", False, (
        MetricDef("found_rate", "심은 경험 찾은 비율", "rate"),
        MetricDef("false_candidates", "함정 구간이 카드 후보가 된 수", "count"),
        MetricDef("missing_kept_blank_rate", "빈칸 유지율", "rate"),
    )),
    EvalStep("postings", "공고 매칭", "posting_eval", False, (
        MetricDef("match_hit_rate", "매칭 적중률", "rate"),
        MetricDef("false_matches", "없는 근거로 만든 매칭 수", "count"),
        MetricDef("requirement_found_rate", "요구 역량 찾은 비율", "rate"),
    )),
    EvalStep("drafts_planted", "자소서 · 심은 문장", "draft_eval", True, (
        MetricDef("warn_rate", "심은 문장 경고율", "rate"),
        MetricDef("genuine_flagged", "진짜 문장을 근거 없음으로 본 수", "count"),
        MetricDef("genuine_needs_check", "진짜 문장에 '확인 필요'를 붙인 수", "count"),
    )),
    EvalStep("drafts_ai", "자소서 · AI 초안", "draft_eval", False, (
        MetricDef("warn_rate", "지어낸 문장 경고율", "rate", needs_labels=True),
        MetricDef("needs_check_not_fabricated", "지어내지 않은 문장에 '확인 필요'를 붙인 수", "count", needs_labels=True),
        MetricDef("unsupported_per_draft", "초안당 근거 없는 문장", "per"),
    ), rescorable=True),
    EvalStep("interview_planted", "면접 · 심은 질문", "interview_eval", True, (
        MetricDef("catch_rate", "심은 질문 잡은 비율", "rate"),
        MetricDef("genuine_dropped", "진짜 질문을 버린 수", "count"),
    )),
    EvalStep("interview_ai", "면접 · AI 질문", "interview_eval", False, (
        MetricDef("premise_rate", "지어낸 전제가 든 질문 비율", "rate", needs_labels=True),
    ), rescorable=True),
)
STEP_BY_KEY = {step.key: step for step in STEPS}


def parse_result_path(line: str) -> str | None:
    """스크립트 출력 한 줄에서 '결과 파일: <경로>'의 경로를 꺼낸다."""
    text = line.strip()
    if not text.startswith(RESULT_LINE_PREFIX):
        return None
    path = text[len(RESULT_LINE_PREFIX):].strip()
    return path or None


def headline(step: EvalStep, summary: dict[str, object]) -> tuple[list[dict[str, object]], int]:
    """결과 파일의 summary에서 대표 수치를 뽑는다. (수치 목록, 판정 대기 수)."""
    pending_raw = summary.get("labels_pending", 0)
    pending = pending_raw if isinstance(pending_raw, int) and pending_raw > 0 else 0
    metrics: list[dict[str, object]] = []
    for metric in step.metrics:
        value = summary.get(metric.key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            value = None
        if metric.needs_labels and pending:
            value = None
        metrics.append({"key": metric.key, "label": metric.label, "kind": metric.kind, "value": value})
    return metrics, pending


def step_entry(step: EvalStep, *, result_file: str | None, payload: dict[str, object] | None, error: str | None) -> dict[str, object]:
    """요약 파일의 평가 한 칸. 결과를 못 얻었으면 status 'failed'와 이유만 남긴다."""
    entry: dict[str, object] = {"key": step.key, "title": step.title, "result_file": result_file}
    summary = payload.get("summary") if payload is not None else None
    if error is not None or payload is None or not isinstance(summary, dict):
        entry.update(status="failed", error=error or "결과 파일에 summary가 없어요.", model=None, metrics=[], labels_pending=0)
        return entry
    metrics, pending = headline(step, summary)
    entry.update(
        status="ok" if payload.get("complete", True) is not False else "partial",
        error=None,
        model=payload.get("model"),
        metrics=metrics,
        labels_pending=pending,
    )
    return entry


def list_summaries(summary_dir: Path) -> list[dict[str, object]]:
    """요약 파일을 새 회차부터 읽는다. 깨진 파일은 건너뛴다(리포트 한 칸 때문에 화면 전체가 죽지 않게)."""
    if not summary_dir.is_dir():
        return []
    runs: list[dict[str, object]] = []
    for path in sorted(summary_dir.glob("run-*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("version") == SUMMARY_VERSION:
            runs.append(data)
    return runs


# 데이터 규모 칸 이름 · 순서. README 표와 리포트 API(data_items)가 같이 쓴다 — 화면은 API가 준 이름을 그대로 보인다.
DATA_LABELS = {
    "quiz_notes": "퀴즈 노트", "card_notes": "경험 노트", "experiences": "심은 경험",
    "postings": "공고", "requirements": "요구 역량", "draft_questions": "자소서 문항",
}


def format_value(metric: dict[str, object], labels_pending: int) -> str:
    """수치 한 칸을 글자로(리포트 화면 · 랜딩 · README · 콘솔 요약 공용). 값이 없으면 판정 대기인지 그냥 없는지 구분한다."""
    value = metric.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "판정 대기" if labels_pending > 0 else "—"
    try:
        if metric.get("kind") == "rate":
            return f"{value * 100:.1f}%"
        if metric.get("kind") == "per":
            return f"{value:.2f}"
        count = int(value) if float(value).is_integer() else value  # 요약 파일에 5.0으로 적혀 있어도 "5개"
    except OverflowError:  # 실수로 바꿀 수 없을 만큼 큰 정수 — 회차 하나 때문에 리포트 전체가 500이 되지 않게
        return "—"
    return f"{count}개"


def pending_of(entry: dict[str, object]) -> int:
    """평가 칸의 판정 대기 수. 숫자가 아니면 0(요약 파일이 틀려도 표시에서 터지지 않게)."""
    pending = entry.get("labels_pending")
    return pending if isinstance(pending, int) and not isinstance(pending, bool) else 0


def data_items(data: dict[str, object]) -> list[dict[str, object]]:
    """데이터 규모를 정해 둔 이름 · 순서로, 화면 · README에 그대로 보일 글자(display — '심은 경험 20개')와 함께.
    모르는 칸 · 숫자가 아닌 값은 뺀다."""
    items: list[dict[str, object]] = []
    for key, label in DATA_LABELS.items():
        count = data.get(key)
        if isinstance(count, int) and not isinstance(count, bool):
            items.append({"key": key, "label": label, "count": count, "display": f"{label} {count}개"})
    return items


def with_display(run: dict[str, object]) -> dict[str, object]:
    """리포트 API가 내려 줄 표시 글자(수치마다 display, 회차마다 data_items)를 더한 사본.
    모양 검사는 API 모델이 한다 — 여기서는 모양이 틀린 칸을 고치지 않고 그대로 둔다(그 회차는 검사에서 빠진다)."""
    shown = dict(run)
    data = run.get("data")
    shown["data_items"] = data_items(data) if isinstance(data, dict) else []
    evals = run.get("evals")
    if isinstance(evals, list):
        shown["evals"] = [_eval_with_display(entry) for entry in evals]
    return shown


def _eval_with_display(entry: object) -> object:
    if not isinstance(entry, dict) or not isinstance(entry.get("metrics"), list):
        return entry
    pending = pending_of(entry)
    metrics = [{**metric, "display": format_value(metric, pending)} if isinstance(metric, dict) else metric for metric in entry["metrics"]]
    return {**entry, "metrics": metrics}
