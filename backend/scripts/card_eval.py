"""경험 카드 평가 실행 — 가상 노트로 '찾은 비율' · '없는 경험으로 만든 후보 수' · '인용 검사로 빈칸이 된 칸 비율'을 잰다
(F-006 완료 기준 7, D-005).

backend 폴더에서:
    uv run --env-file .env python -m scripts.card_eval exaone             # 경험 노트 8개 + 경험 없는 노트 10개
    uv run --env-file .env python -m scripts.card_eval exaone --limit 1   # 앞에서부터 노트 1개로 먼저 시험
    (퀴즈 평가와 같이 호출 사이 기본 20초, 500 · 429면 60초 쉬고 2번까지 다시 — 느려도 끝까지)

- 경험 노트: eval/cards/notes/*.md, 정답지: eval/cards/answers.json (지어낸 기록이라 레포에 둔다, 사용자 확인 2026-11-11).
- 경험 없는 노트: 퀴즈 평가의 가상 노트 eval/quiz/notes/*.md를 그대로 쓴다(개념 정리만 있는 기록).
- 임시 SQLite DB에 평가용 사용자와 노트를 올려 돌린다. 개발 DB · 내 계정은 건드리지 않는다.
- 판정은 채점 AI 없이 인용 위치로 한다(app/services/card_evaluation.py). AI는 노트당 1번만 부른다.
- 결과는 eval/cards/results/cards-<provider>-<시각>.json (후보마다 칸 · 인용 · 구간 — 사람이 골라 검수).
  노트 하나가 끝날 때마다 덮어써서 중간에 멈춰도 그때까지의 결과가 남는다("complete": false).
- mock이면 멈춘다(첫 줄을 베끼는 가짜 후보라 수치에 뜻이 없음). 키 · 주소는 출력하지 않는다. pytest에는 넣지 않는다.
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
from app.services.card_evaluation import (
    NoteEvalResult,
    NoteKey,
    evaluate_note,
    parse_answer_key,
    result_to_dict,
    summarize,
)
from app.services.card_generation import mock_card_responder
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user
from app.services.quiz_evaluation import PatientClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BACKEND_DIR / "eval" / "cards"
NOTES_DIR = EVAL_DIR / "notes"
ANSWERS_PATH = EVAL_DIR / "answers.json"
RESULTS_DIR = EVAL_DIR / "results"
EVAL_PROFILE = GoogleProfile(sub="card-eval", email="card-eval@example.invalid", name="카드 평가")
EVAL_DAILY_LIMIT = 1000  # 평가용 가상 사용자의 하루 상한(임시 DB라 서비스에는 영향 없음)

Plan = list[tuple[Path, NoteKey | None]]


def _title_of(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _pct(value: object) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, float) else "-"


def _load_plan() -> Plan:
    """(노트 파일, 정답) — 경험 노트 먼저, 그다음 경험 없는 노트. 정답지와 노트가 어긋나면 AI를 부르기 전에 멈춘다."""
    raw = json.loads(ANSWERS_PATH.read_text(encoding="utf-8"))
    keys = parse_answer_key(raw)
    experience_paths = sorted(NOTES_DIR.glob("*.md"))
    names = {path.name for path in experience_paths}
    if names != set(keys):
        raise ValueError(
            f"정답지와 노트가 달라요 — 정답 없는 노트 {sorted(names - set(keys))}, 노트 없는 정답 {sorted(set(keys) - names)}"
        )
    none_dir = BACKEND_DIR / str(raw["no_experience_notes"])
    none_paths = sorted(none_dir.glob("*.md"))
    if not none_paths:  # 비면 '없는 경험 후보 0개'가 검사 안 함인지 통과인지 구분되지 않는다(F-006 1차 리뷰 R3)
        raise ValueError(f"경험 없는 노트가 없어요: {none_dir}")
    return [(path, keys[path.name]) for path in experience_paths] + [(path, None) for path in none_paths]


def _status_line(result: NoteEvalResult) -> str:
    if result.error:
        status = f"실패 {result.error}"
    else:
        score = result.score
        status = f"후보 {len(score.verdicts)}개 · {result.seconds:.1f}초"
        if result.has_experience:
            status += f" · 찾음 {len(score.found)}/{len(score.seeded)}"
        if score.false_candidates:
            status += f" · 없는 경험 {len(score.false_candidates)}"
        if result.emptied_fields:
            status += f" · 빈칸으로 돌림 {result.emptied_fields}"
    if result.retries:
        status += f" · 다시 시도 {result.retries}번"
    return status


def _print_summary(provider: str, s: dict[str, object], waits: list[float]) -> None:
    lines = [
        f"AI {provider} · 노트 {s['notes']}개(경험 노트 {s['notes_with_experience']}) · "
        f"보낸 조각 {s['chunks_sent']}개 · 후보 {s['candidates']}개",
        f"찾은 비율: {s['found_experiences']}/{s['seeded_experiences']} = {_pct(s['found_rate'])}  "
        f"못 찾음 {s['missed_experiences']}",
        f"없는 경험으로 만든 후보: {s['false_candidates']}개  {s['false_candidates_by_kind']}  {s['false_candidates_by_trap']}",
        f"인용 검사로 빈칸이 된 칸: {s['quotes_emptied']}/{s['quotes_given']} = {_pct(s['emptied_rate'])}  "
        f"이유 {s['drop_reasons']}",
        f"(덤) 기록에 없는 칸을 빈칸으로 남김: {s['missing_slots_kept_blank']}/{s['missing_slots_checked']} "
        f"= {_pct(s['missing_kept_blank_rate'])}",
        f"중복 후보 {s['duplicate_candidates']}개 · 섞인 후보 {s['mixed_candidates']}개 · 실패 {s['failures']}번",
        f"시간: 평균 {s['seconds_avg']}초 · 최대 {s['seconds_max']}초 · 사용량 {s['usage']}",
    ]
    if waits:
        lines.append(f"429로 기다림: {len(waits)}번 · 합계 {sum(waits):.0f}초")
    print("\n" + "\n".join(lines))


def _write_results(
    out: Path, *, provider: str, model: str, results: list[NoteEvalResult], waits: list[float], done: bool
) -> None:
    """노트 하나가 끝날 때마다 덮어쓴다 — 중간에 멈춰도(Ctrl+C · 오류) 그때까지의 결과가 남는다(F-006 1차 리뷰 R3)."""
    payload = {
        "provider": provider,
        "model": model,
        "complete": done,  # False면 중간에 멈춘 부분 결과
        "summary": summarize(results),
        "rate_limit_waits": waits,
        "notes": [result_to_dict(r) for r in results],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def _evaluate_all(
    plan: Plan,
    finder: LLMClient,
    *,
    retries: int,
    retry_wait: float,
    on_result: Callable[[list[NoteEvalResult]], None],
) -> list[NoteEvalResult]:
    """임시 SQLite에 평가용 사용자와 노트를 올려 하나씩 돈다. 개발 DB · 내 계정은 건드리지 않는다."""
    results: list[NoteEvalResult] = []
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_db_engine(f"sqlite:///{Path(tmp) / 'card_eval.db'}")
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        try:
            user = get_or_create_google_user(db, EVAL_PROFILE)
            user.daily_limit = EVAL_DAILY_LIMIT
            db.commit()
            for index, (path, key) in enumerate(plan, start=1):
                content = path.read_text(encoding="utf-8")
                note = create_note_for_user(
                    db, user_id=user.id, title=_title_of(content, path.stem), content=content, chunks=split_markdown(content)
                )
                label = "경험" if key is not None else "경험 없음"
                print(f"[{index}/{len(plan)}] ({label}) {note.title} …", flush=True)
                try:
                    result = await evaluate_note(
                        db,
                        user_id=user.id,
                        note=note,
                        file_name=path.name,
                        key=key,
                        client=finder,
                        retries=retries,
                        retry_wait=retry_wait,
                    )
                except Exception as exc:  # 한 노트의 예상 못 한 오류로 평가 전체를 멈추지 않는다(종류만 기록)
                    db.rollback()
                    result = NoteEvalResult(
                        file_name=path.name, note_title=note.title, has_experience=key is not None, error=type(exc).__name__
                    )
                    if key is not None:
                        result.score.seeded = [experience.id for experience in key.experiences]
                print(f"    {_status_line(result)}", flush=True)
                results.append(result)
                on_result(results)
        finally:
            db.close()
            engine.dispose()
    return results


async def _run(
    provider: str | None, limit: int | None, allow_mock: bool, pause: float, retries: int, retry_wait: float
) -> int:
    try:
        plan = _load_plan()
    except (ValueError, KeyError, OSError) as exc:  # OSError: 정답지 · 노트 파일을 못 읽음(F-006 2차 리뷰 R3)
        print(f"정답지 오류: {exc}")
        return 1
    try:
        settings = load_llm_settings(provider)
        client = get_llm_client(settings)
    except LLMConfigError as exc:
        print(f"AI 설정 오류: {exc}")
        return 1
    patient = PatientClient(client, min_interval=pause)  # 호출 사이 간격 · 429면 기다렸다 다시(평가 전용)
    finder: LLMClient = patient
    if settings.provider == "mock":
        if not allow_mock:
            print("mock으로는 평가 수치에 뜻이 없어요. 예) python -m scripts.card_eval exaone")
            return 1
        finder = MockLLMClient(responder=mock_card_responder)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"cards-{settings.provider}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

    def save(results: list[NoteEvalResult], *, done: bool = False) -> None:
        _write_results(out, provider=settings.provider, model=settings.model, results=results, waits=patient.waits, done=done)

    results = await _evaluate_all(plan[:limit], finder, retries=retries, retry_wait=retry_wait, on_result=save)
    save(results, done=True)
    _print_summary(settings.provider, summarize(results), patient.waits)
    print(f"결과 파일: {out.relative_to(BACKEND_DIR) if out.is_relative_to(BACKEND_DIR) else out}")
    return 0


def main() -> None:
    # Windows에서 출력을 파이프로 넘기면 기본 인코딩(cp949)이 일부 글자를 못 써서 멈춘다(T-003)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="경험 카드 평가(F-006 완료 기준 7)")
    parser.add_argument("provider", nargs="?", default=None, help="exaone · local (빼면 LLM_PROVIDER 설정)")
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 노트 몇 개만(경험 노트 먼저, 1 이상)")
    parser.add_argument("--allow-mock", action="store_true", help="흐름 확인용으로 mock도 허용(수치는 뜻 없음)")
    parser.add_argument("--pause", type=float, default=20.0, help="AI 호출 사이 최소 간격(초)")
    parser.add_argument("--retries", type=int, default=2, help="AI 서버 오류(500 · 429)면 노트마다 다시 해 볼 횟수(0 이상)")
    parser.add_argument("--retry-wait", type=float, default=60.0, help="다시 해 보기 전에 쉬는 시간(초)")
    args = parser.parse_args()
    if args.retries < 0 or args.pause < 0 or args.retry_wait < 0:
        parser.error("--retries · --pause · --retry-wait는 0 이상이어야 해요.")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit은 1 이상이어야 해요.")
    raise SystemExit(
        asyncio.run(_run(args.provider, args.limit, args.allow_mock, args.pause, args.retries, args.retry_wait))
    )


if __name__ == "__main__":
    main()
