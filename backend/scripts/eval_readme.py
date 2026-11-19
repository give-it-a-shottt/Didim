"""README 평가 표 — scripts/eval_all.py --readme만 쓴다(F-010 완료 기준 3).

리포트 화면과 같은 요약 파일 · 같은 표시 규칙(app/services/eval_report.py format_value · data_items)을 쓴다.
README의 표시(README_START · README_END) 사이만 바꾸고, 사람이 쓴 나머지 글은 건드리지 않는다.
"""

from __future__ import annotations

from app.services.eval_report import data_items, format_value, pending_of

README_START = "<!-- eval-report:start -->"
README_END = "<!-- eval-report:end -->"


def readme_table(run: dict[str, object]) -> str:
    """최근 회차를 README에 넣을 마크다운 표로."""
    raw_data = run.get("data")
    sizes = " · ".join(str(item["display"]) for item in data_items(raw_data if isinstance(raw_data, dict) else {}))
    started = str(run.get("started_at") or "")[:10] or str(run.get("run_id"))
    lines = [
        f"회차 {started} · 모델 {run.get('model') or '—'}" + (f" · {sizes}" if sizes else ""),
        "",
        "| 평가 | 수치 | 값 |",
        "|---|---|---|",
    ]
    evals = run.get("evals")
    for entry in evals if isinstance(evals, list) else []:
        pending = pending_of(entry)
        if entry.get("status") == "failed":
            lines.append(f"| {entry.get('title')} | — | 이번 회차에 돌리지 못함 |")
            continue
        for metric in entry.get("metrics") or []:
            lines.append(f"| {entry.get('title')} | {metric.get('label')} | {format_value(metric, pending)} |")
    return "\n".join(lines)


def replace_readme_block(text: str, table: str) -> str:
    """README의 표시 사이만 바꾼다. 표시가 없으면 ValueError — README의 나머지(사람이 쓴 글)는 건드리지 않는다."""
    start = text.find(README_START)
    end = text.find(README_END)
    if start < 0 or end < 0 or end < start:
        raise ValueError(f"README에 {README_START} … {README_END} 표시가 없어요.")
    return text[: start + len(README_START)] + "\n" + table + "\n" + text[end:]
