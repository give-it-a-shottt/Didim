"""공고 분석 평가 실행 — 가상 공고로 '매칭 적중률' · '없는 근거로 만든 매칭 수'를 잰다 (F-007 완료 기준 6, D-005).

backend 폴더에서:
    uv run --env-file .env python -m scripts.posting_eval exaone             # 공고 6개(역량 28개) — AI 최대 12번
    uv run --env-file .env python -m scripts.posting_eval exaone --limit 1   # 앞에서부터 공고 1개로 먼저 시험
    (카드 평가와 같이 호출 사이 기본 20초, 500 · 429면 60초 쉬고 2번까지 다시)

- 공고: eval/postings/postings/*.md, 정답지: eval/postings/answers.json (지어낸 공고라 레포에 둔다).
- 카드: F-006 평가 노트(eval/cards/notes)에 심은 경험 12개로 AI 없이 저장 카드를 만든다(posting_evaluation.build_eval_cards).
- 임시 SQLite DB에 평가용 사용자 · 노트 · 카드를 올려 돌린다. 개발 DB · 내 계정은 건드리지 않는다.
- 판정은 채점 AI 없이 위치 · 카드 번호로 한다(app/services/posting_evaluation.py).
- 결과는 eval/postings/results/postings-<provider>-<시각>.json. 공고 하나가 끝날 때마다 덮어쓴다("complete": false면 중간에 멈춤).
- mock이면 멈춘다(--allow-mock은 흐름 확인용). 키 · 주소는 출력하지 않는다. pytest에는 넣지 않는다.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import create_db_engine
from app.llm import LLMClient, LLMConfigError, MockLLMClient, get_llm_client, load_llm_settings
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.card_evaluation import parse_answer_key
from app.services.posting_evaluation import (
    PostingEvalResult,
    PostingKey,
    build_eval_cards,
    check_card_references,
    evaluate_posting,
    key_spans,
    parse_posting_key,
    result_to_dict,
    summarize,
)
from app.services.posting_mock import mock_analysis_responder
from app.services.quiz_evaluation import PatientClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BACKEND_DIR / "eval" / "postings"
POSTINGS_DIR = EVAL_DIR / "postings"
ANSWERS_PATH = EVAL_DIR / "answers.json"
RESULTS_DIR = EVAL_DIR / "results"
EVAL_PROFILE = GoogleProfile(sub="posting-eval", email="posting-eval@example.invalid", name="공고 평가")
EVAL_DAILY_LIMIT = 1000  # 임시 DB의 가상 사용자라 서비스에는 영향 없음

Plan = list[tuple[Path, str, PostingKey]]


def _pct(value: object) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, float) else "-"


def _load() -> tuple[Plan, dict, Path]:  # type: ignore[type-arg]
    """(공고 파일, 본문, 정답) 목록과 카드 정답지. 정답지와 공고가 어긋나면 AI를 부르기 전에 멈춘다."""
    raw = json.loads(ANSWERS_PATH.read_text(encoding="utf-8"))
    keys = parse_posting_key(raw)
    paths = sorted(POSTINGS_DIR.glob("*.md"))
    names = {path.name for path in paths}
    if names != set(keys):
        raise ValueError(f"정답지와 공고가 달라요 — 정답 없는 공고 {sorted(names - set(keys))}, 공고 없는 정답 {sorted(set(keys) - names)}")
    card_answers_path = BACKEND_DIR / str(raw["cards_from"])
    card_raw = json.loads(card_answers_path.read_text(encoding="utf-8"))
    card_keys = parse_answer_key(card_raw)
    check_card_references(keys, card_keys)
    plan: Plan = []
    for path in paths:
        text = path.read_text(encoding="utf-8").strip()
        key_spans(text, keys[path.name])  # 정답지 줄이 공고에 글자 그대로 한 번씩 있는지
        plan.append((path, text, keys[path.name]))
    return plan, card_keys, card_answers_path.parent / "notes"


def _status_line(result: PostingEvalResult) -> str:
    verdicts = result.score.verdicts
    evidence = [verdict for verdict in verdicts if verdict.has_evidence]
    parts = [
        f"역량 {sum(1 for v in verdicts if v.found)}/{len(verdicts)} 뽑음",
        f"적중 {sum(1 for v in evidence if v.hit)}/{len(evidence)}",
    ]
    false = sum(len(v.wrong) for v in verdicts)
    if false:
        parts.append(f"없는 근거 매칭 {false}")
    if result.score.extra_requirements:
        parts.append(f"정답지 밖 역량 {len(result.score.extra_requirements)}")
    if result.seconds:
        parts.append(" · ".join(f"{step} {value:.0f}초" for step, value in result.seconds.items()))
    if result.error:
        parts.append(f"실패({result.error_step}) {result.error}")
    if result.retries:
        parts.append(f"다시 시도 {result.retries}번")
    return " · ".join(parts)


def _print_summary(provider: str, s: dict[str, object], waits: list[float]) -> None:
    lines = [
        f"AI {provider} · 공고 {s['postings']}개 · 역량 {s['requirements_seeded']}개"
        f"(근거 있음 {s['requirements_with_evidence']} · 근거 없어야 함 {s['requirements_without_evidence']})",
        f"매칭 적중률: {s['match_hits']}/{s['requirements_with_evidence']} = {_pct(s['match_hit_rate'])}"
        f"  (뽑은 역량 안에서 {_pct(s['match_hit_rate_among_found'])})",
        f"없는 근거로 만든 매칭: {s['false_matches']}개 (근거 없어야 할 역량에 {s['false_matches_on_traps']} · "
        f"엉뚱한 카드 {s['false_matches_wrong_card']})",
        f"역량 뽑기: {s['requirements_found']}/{s['requirements_seeded']} = {_pct(s['requirement_found_rate'])} · "
        f"필수/우대 맞힘 {s['kind_correct']} · 정답지 밖 역량 {s['extra_requirements']}",
        f"키워드 후보에 정답 카드: {_pct(s['candidate_recall_among_found'])} · "
        f"근거 없어야 할 역량을 비워 둠 {s['traps_left_empty']}/{s['traps_found']}",
        f"인용 검사로 버림: 공고 {s['extract_drop_reasons']} · 카드 {s['match_drop_reasons']}",
        f"실패 {s['failures']}번 · 시간 평균 {s['seconds_avg']}초 · 최대 {s['seconds_max']}초 · 사용량 {s['usage']}",
    ]
    if waits:
        lines.append(f"429로 기다림: {len(waits)}번 · 합계 {sum(waits):.0f}초")
    print("\n" + "\n".join(lines))


def _write_results(out: Path, *, provider: str, model: str, results: list[PostingEvalResult], waits: list[float], done: bool) -> None:
    payload = {
        "provider": provider,
        "model": model,
        "complete": done,
        "summary": summarize(results),
        "rate_limit_waits": waits,
        "postings": [result_to_dict(result) for result in results],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def _evaluate_all(
    plan: Plan,
    card_keys: dict,  # type: ignore[type-arg]
    notes_dir: Path,
    client: LLMClient,
    *,
    retries: int,
    retry_wait: float,
    on_result: Callable[[list[PostingEvalResult]], None],
) -> list[PostingEvalResult]:
    results: list[PostingEvalResult] = []
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_db_engine(f"sqlite:///{Path(tmp) / 'posting_eval.db'}")
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        try:
            user = get_or_create_google_user(db, EVAL_PROFILE)
            user.daily_limit = EVAL_DAILY_LIMIT
            db.commit()
            card_experience = build_eval_cards(db, user_id=user.id, notes_dir=notes_dir, card_keys=card_keys)
            print(f"평가 카드 {len(card_experience)}장을 만들었어요(AI 없이, 경험 구간 문단으로).", flush=True)
            for index, (path, text, key) in enumerate(plan, start=1):
                print(f"[{index}/{len(plan)}] {path.name} …", flush=True)
                try:
                    result = await evaluate_posting(
                        db,
                        user_id=user.id,
                        file_name=path.name,
                        posting_text=text,
                        key=key,
                        card_experience=card_experience,
                        client=client,
                        retries=retries,
                        retry_wait=retry_wait,
                    )
                except Exception as exc:  # 한 공고의 예상 못 한 오류로 평가 전체를 멈추지 않는다(종류만 기록)
                    db.rollback()
                    result = PostingEvalResult(file_name=path.name, company=path.stem, error=type(exc).__name__)
                print(f"    {_status_line(result)}", flush=True)
                results.append(result)
                on_result(results)
        finally:
            db.close()
            engine.dispose()
    return results


async def _run(provider: str | None, limit: int | None, allow_mock: bool, pause: float, retries: int, retry_wait: float) -> int:
    try:
        plan, card_keys, notes_dir = _load()
    except (ValueError, KeyError, OSError) as exc:
        print(f"정답지 오류: {exc}")
        return 1
    try:
        settings = load_llm_settings(provider)
        client = get_llm_client(settings)
    except LLMConfigError as exc:
        print(f"AI 설정 오류: {exc}")
        return 1
    patient = PatientClient(client, min_interval=pause)
    analyst: LLMClient = patient
    if settings.provider == "mock":
        if not allow_mock:
            print("mock으로는 평가 수치에 뜻이 없어요. 예) python -m scripts.posting_eval exaone")
            return 1
        analyst = MockLLMClient(responder=mock_analysis_responder)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"postings-{settings.provider}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

    def save(results: list[PostingEvalResult], *, done: bool = False) -> None:
        _write_results(out, provider=settings.provider, model=settings.model, results=results, waits=patient.waits, done=done)

    results = await _evaluate_all(
        plan[:limit], card_keys, notes_dir, analyst, retries=retries, retry_wait=retry_wait, on_result=save
    )
    save(results, done=True)
    _print_summary(settings.provider, summarize(results), patient.waits)
    print(f"결과 파일: {out.relative_to(BACKEND_DIR) if out.is_relative_to(BACKEND_DIR) else out}")
    return 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # Windows cp949 파이프 출력(T-003)
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="공고 분석 평가(F-007 완료 기준 6)")
    parser.add_argument("provider", nargs="?", default=None, help="exaone · local (빼면 LLM_PROVIDER 설정)")
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 공고 몇 개만(1 이상)")
    parser.add_argument("--allow-mock", action="store_true", help="흐름 확인용으로 mock도 허용(수치는 뜻 없음)")
    parser.add_argument("--pause", type=float, default=20.0, help="AI 호출 사이 최소 간격(초)")
    parser.add_argument("--retries", type=int, default=2, help="AI 서버 오류(500 · 429)면 단계마다 다시 해 볼 횟수(0 이상)")
    parser.add_argument("--retry-wait", type=float, default=60.0, help="다시 해 보기 전에 쉬는 시간(초)")
    args = parser.parse_args()
    if args.retries < 0 or args.pause < 0 or args.retry_wait < 0:
        parser.error("--retries · --pause · --retry-wait는 0 이상이어야 해요.")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit은 1 이상이어야 해요.")
    raise SystemExit(asyncio.run(_run(args.provider, args.limit, args.allow_mock, args.pause, args.retries, args.retry_wait)))


if __name__ == "__main__":
    main()
