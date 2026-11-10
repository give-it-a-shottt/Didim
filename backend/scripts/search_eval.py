"""검색 평가 실행 — 내 기록으로 만든 평가 세트로 '상위 5개 안에 정답 조각이 있는 비율'을 잰다 (F-003 완료 기준 5).

backend 폴더에서:
    uv run --env-file .env python -m scripts.search_eval --email 내구글이메일
    uv run --env-file .env python -m scripts.search_eval --email 내구글이메일 --file eval/다른세트.local.json

- 평가 세트는 공부 기록 내용이 들어가서 레포에 올리지 않는다(사용자 확인). 기본 위치 eval/search_eval.local.json,
  모양은 eval/search_eval.example.json 참고. 결과는 eval/results/에 JSON으로 남는다(이것도 레포 밖).
- 개발 DB(DATABASE_URL)의 그 사용자 기록으로 검색한다. 읽기만 하고 검색 로그는 남기지 않는다.
- DB 주소 · 키는 출력하지 않는다. pytest에는 넣지 않는다(내 기록에 기대지 않게). 채점 규칙은 tests/test_search_eval.py가 확인한다.
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import load_settings
from app.db.models import User
from app.db.session import create_db_engine
from app.search import get_searcher
from app.search.evaluation import EvalSetError, evaluate, parse_eval_set

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SET = BACKEND_DIR / "eval" / "search_eval.local.json"
RESULTS_DIR = BACKEND_DIR / "eval" / "results"


def main() -> int:
    # Windows에서 출력을 파이프로 넘기면 기본 인코딩(cp949)이 일부 글자를 못 써서 멈춘다(T-003)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="기록 검색 평가(F-003)")
    parser.add_argument("--email", required=True, help="평가할 기록의 주인(구글 로그인 이메일)")
    parser.add_argument("--file", type=Path, default=DEFAULT_SET, help="평가 세트 JSON 경로")
    args = parser.parse_args()

    try:
        items = parse_eval_set(json.loads(args.file.read_text(encoding="utf-8")))
    except FileNotFoundError:
        print(f"평가 세트가 없어요: {args.file}  (eval/search_eval.example.json을 복사해서 만들어 주세요)")
        return 1
    except (json.JSONDecodeError, EvalSetError) as exc:
        print(f"평가 세트 모양이 틀렸어요: {exc}")
        return 1

    engine = create_db_engine(load_settings().database_url)
    db = sessionmaker(bind=engine)()
    try:
        users = db.execute(select(User).where(User.email == args.email)).scalars().all()
        if len(users) != 1:
            print(f"이 이메일의 사용자가 {len(users)}명이에요. 1명이어야 해요.")
            return 1
        report = evaluate(db, get_searcher(), user_id=users[0].id, items=items)
    finally:
        db.close()
        engine.dispose()

    print(f"방식 {report.method} · 상위 {report.k}개 · 질문 {len(report.items)}개")
    print(f"정답 포함 비율: {report.hits}/{len(report.items)} = {report.hit_rate:.2f}")
    for tag, (got, total) in sorted(report.by_tag.items()):
        print(f"  tag '{tag}': {got}/{total} = {got / total:.2f}")
    misses = [item for item in report.items if item.hit_rank is None]
    if misses:
        print("못 찾은 질문:")
        for item in misses:
            found = ", ".join(f"{hit['note_title']} {hit['heading_path']}" for hit in item.top) or "결과 없음"
            print(f"  - {item.query}  → {found}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"search-{report.method}-{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "method": report.method,
                "k": report.k,
                "hit_rate": report.hit_rate,
                "hits": report.hits,
                "total": len(report.items),
                "by_tag": report.by_tag,
                "items": [asdict(item) for item in report.items],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"결과 파일: {out.relative_to(BACKEND_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
