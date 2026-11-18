"""샘플 체험 데이터 넣기 (F-010, D-025 · D-029) — 평가 회차의 AI 결과를 샘플 계정에 다시 들려줘 넣는다. AI는 부르지 않는다.

backend 폴더에서(DATABASE_URL의 DB — 개발 DB · 배포 DB):
    uv run --env-file .env python -m scripts.seed_sample                                          # 가장 최근 회차
    uv run --env-file .env python -m scripts.seed_sample --summary eval/summary/run-<시각>.json   # 회차 고르기

- 새 샘플을 공개되지 않는 임시 계정에 채운 뒤 한 번에 옛 샘플(google_sub 'didim-sample')과 바꿔 끼운다. 실패하면 지금 샘플은
  그대로다. 바꿔 끼우면 체험 중이던 샘플 세션은 로그인 화면으로 돌아간다.
- 저장 개수를 결과 파일과 비교해 다르면 종료 코드 1(샘플 화면과 리포트 수치가 어긋나면 안 됨). 자세한 방식은
  app/services/sample_seed.py. DB 주소 · 키는 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.db.session import dispose_engine, ensure_db_ready, get_session_factory
from app.services.eval_report import EVAL_SUMMARY_DIR, list_summaries
from app.services.sample_seed import SeedError, seed_sample, sources_from_summary

BACKEND_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BACKEND_DIR / "eval"


def _summary(path: Path | None) -> dict[str, object]:
    if path is None:
        runs = list_summaries(EVAL_SUMMARY_DIR)
        if not runs:
            raise SeedError("요약 파일이 없어요. 먼저 평가를 돌려 주세요(scripts.eval_all).")
        return runs[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SeedError(f"요약 파일을 읽지 못했어요: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise SeedError("요약 파일 모양이 달라요.")
    return data


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # Windows cp949 파이프 출력(T-003)
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="샘플 체험 데이터 넣기(F-010)")
    parser.add_argument("--summary", type=Path, default=None, help="평가 회차 요약 파일(빼면 가장 최근 회차)")
    args = parser.parse_args()
    try:
        summary = _summary(args.summary)
        sources = sources_from_summary(summary, BACKEND_DIR)
    except SeedError as exc:
        parser.error(str(exc))
    ensure_db_ready()  # DB가 최신 버전인지(D-015) — 아니면 여기서 멈춘다
    db = get_session_factory()()
    try:
        report = asyncio.run(seed_sample(db, eval_dir=EVAL_DIR, sources=sources))
    except SeedError as exc:
        print(f"시드 실패: {exc}")
        raise SystemExit(1) from exc
    finally:
        db.close()
        dispose_engine()
    print(f"회차 {summary.get('run_id')} → 샘플 사용자 {report.user_id}: 노트 {report.notes} · 카드 {report.cards}")
    for kind, (expected, saved) in report.counts.items():
        print(f"- {kind}: 결과 {expected} · 저장 {saved}{'' if expected == saved else '  ← 어긋남'}")
    if report.mismatches:
        print("저장 개수가 결과 파일과 달라요 — 샘플 화면이 리포트 수치와 어긋날 수 있어요.")
        raise SystemExit(1)
    print("결과 파일과 저장 개수가 모두 같아요.")


if __name__ == "__main__":
    main()
