"""퀴즈 평가 실행 — 가상 노트로 '버려진 문제 비율' · '정답 일치율' · '해설 일치율'을 잰다 (F-004 완료 기준 7, D-005).

backend 폴더에서:
    uv run --env-file .env python -m scripts.quiz_eval exaone             # 노트 10개 전부
    uv run --env-file .env python -m scripts.quiz_eval exaone --limit 1   # 노트 1개로 먼저 시험
    (무료 API라 짧은 간격으로 이어 부르면 막는 것 같아 기본으로 호출 사이 20초, 500 · 429면 60초 쉬고 2번까지 다시 — 느려도 끝까지)

- 가상 노트: eval/quiz/notes/*.md (지어낸 공부 기록이라 레포에 둔다, 사용자 확인 2026-11-11).
- 임시 SQLite DB에 평가용 사용자와 노트를 올려 돌린다. 개발 DB · 내 계정은 건드리지 않는다.
- 문제 만들기는 실제 서비스 함수, 정답 · 해설 판정은 채점 AI(app/services/quiz_evaluation.py). 같은 AI 설정을 쓴다.
- 결과는 eval/quiz/results/quiz-<provider>-<시각>.json (문제마다 판정 이유 포함 — 사람이 골라 검수).
- mock이면 멈춘다(원문을 그대로 베끼는 가짜 문제라 수치에 뜻이 없음). 키 · 주소는 출력하지 않는다. pytest에는 넣지 않는다.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import create_db_engine
from app.llm import LLMClient, LLMConfigError, MockLLMClient, get_llm_client, load_llm_settings
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user
from app.services.quiz_evaluation import (
    NoteEvalResult,
    PatientClient,
    evaluate_note,
    mock_judge_responder,
    result_to_dict,
    summarize,
)
from app.services.quiz_generation import mock_quiz_responder

BACKEND_DIR = Path(__file__).resolve().parent.parent
NOTES_DIR = BACKEND_DIR / "eval" / "quiz" / "notes"
RESULTS_DIR = BACKEND_DIR / "eval" / "quiz" / "results"
EVAL_PROFILE = GoogleProfile(sub="quiz-eval", email="quiz-eval@example.invalid", name="퀴즈 평가")


def _title_of(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _pct(value: object) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, float) else "-"


# 평가용 가상 사용자의 하루 상한. 재시도로 서비스 상한(30)에 걸려 평가가 멈추지 않게(임시 DB라 서비스에는 영향 없음)
EVAL_DAILY_LIMIT = 1000


async def _run(
    provider: str | None, limit: int | None, allow_mock: bool, pause: float, retries: int, retry_wait: float
) -> int:
    try:
        settings = load_llm_settings(provider)
        client = get_llm_client(settings)
    except LLMConfigError as exc:
        print(f"AI 설정 오류: {exc}")
        return 1
    patient = PatientClient(client, min_interval=pause)  # 호출 사이 간격 · 429면 기다렸다 다시(평가 전용)
    generator: LLMClient = patient
    judge: LLMClient = patient
    if settings.provider == "mock":
        if not allow_mock:
            print("mock으로는 평가 수치에 뜻이 없어요. 예) python -m scripts.quiz_eval exaone")
            return 1
        generator = MockLLMClient(responder=mock_quiz_responder)
        judge = MockLLMClient(responder=mock_judge_responder)

    paths = sorted(NOTES_DIR.glob("*.md"))[:limit]
    if not paths:
        print(f"가상 노트가 없어요: {NOTES_DIR}")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        engine = create_db_engine(f"sqlite:///{Path(tmp) / 'quiz_eval.db'}")
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        try:
            user = get_or_create_google_user(db, EVAL_PROFILE)
            user.daily_limit = EVAL_DAILY_LIMIT
            db.commit()
            results = []
            for index, path in enumerate(paths, start=1):
                content = path.read_text(encoding="utf-8")
                note = create_note_for_user(
                    db, user_id=user.id, title=_title_of(content, path.stem), content=content, chunks=split_markdown(content)
                )
                print(f"[{index}/{len(paths)}] {note.title} …", flush=True)
                try:
                    result = await evaluate_note(
                        db,
                        user_id=user.id,
                        note=note,
                        generator=generator,
                        judge=judge,
                        retries=retries,
                        retry_wait=retry_wait,
                    )
                except Exception as exc:  # 한 노트의 예상 못 한 오류로 평가 전체를 멈추지 않는다(종류만 기록)
                    db.rollback()
                    result = NoteEvalResult(note_title=note.title, generation_error=type(exc).__name__)
                status = result.generation_error or f"남김 {result.kept} · 버림 {result.dropped} · {result.generation_seconds:.1f}초"
                if result.retries:
                    status += f" · 다시 시도 {result.retries}번"
                if result.judge_error:
                    status += f" · 채점 실패 {result.judge_error}"
                print(f"    {status}", flush=True)
                results.append(result)
        finally:
            db.close()
            engine.dispose()

    summary = summarize(results)
    print()
    print(f"AI {settings.provider} · 노트 {summary['notes']}개 · 보낸 조각 {summary['chunks_sent']}개 · AI가 낸 문제 {summary['produced']}개")
    print(f"버려진 문제 비율: {summary['dropped']}/{summary['produced']} = {_pct(summary['drop_rate'])}  이유 {summary['drop_reasons']}")
    print(f"정답 일치율: {_pct(summary['answer_match_rate'])} · 해설 일치율: {_pct(summary['explanation_match_rate'])}  (판정 {summary['judged']}개, 판정 못 받음 {summary['unjudged']}개)")
    print(f"문제 만들기 시간: 평균 {summary['generation_seconds_avg']}초 · 최대 {summary['generation_seconds_max']}초")
    print(f"실패: 문제 만들기 {summary['generation_failures']}번 · 채점 {summary['judge_failures']}번")
    print(f"사용량: {summary['usage']}")
    if patient.waits:
        print(f"429로 기다림: {len(patient.waits)}번 · 합계 {sum(patient.waits):.0f}초")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"quiz-{settings.provider}-{stamp}.json"
    out.write_text(
        json.dumps(
            {"provider": settings.provider, "model": settings.model, "summary": summary, "rate_limit_waits": patient.waits, "notes": [result_to_dict(r) for r in results]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"결과 파일: {out.relative_to(BACKEND_DIR)}")
    return 0


def main() -> None:
    # Windows에서 출력을 파이프로 넘기면 기본 인코딩(cp949)이 일부 글자를 못 써서 멈춘다(T-003)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="퀴즈 평가(F-004 완료 기준 7)")
    parser.add_argument("provider", nargs="?", default=None, help="exaone · local (빼면 LLM_PROVIDER 설정)")
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 노트 몇 개만")
    parser.add_argument("--allow-mock", action="store_true", help="흐름 확인용으로 mock도 허용(수치는 뜻 없음)")
    parser.add_argument("--pause", type=float, default=20.0, help="AI 호출 사이 최소 간격(초)")
    parser.add_argument("--retries", type=int, default=2, help="AI 서버 오류(500 · 429)면 노트마다 다시 해 볼 횟수(0 이상)")
    parser.add_argument("--retry-wait", type=float, default=60.0, help="다시 해 보기 전에 쉬는 시간(초)")
    args = parser.parse_args()
    if args.retries < 0 or args.pause < 0 or args.retry_wait < 0:
        parser.error("--retries · --pause · --retry-wait는 0 이상이어야 해요.")
    raise SystemExit(
        asyncio.run(_run(args.provider, args.limit, args.allow_mock, args.pause, args.retries, args.retry_wait))
    )


if __name__ == "__main__":
    main()
