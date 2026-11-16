"""면접 질문 평가 실행 — '카드에 없는 내용을 전제로 한 질문 수'를 잰다 (F-009 완료 기준 4, D-005).

backend 폴더에서:
    uv run python -m scripts.interview_eval --planted                                   # 심은 질문 평가(D-005, AI 안 부름) — 핵심 수치
    uv run --env-file .env python -m scripts.interview_eval nvidia --pause 3             # AI 질문 평가: 카드 12장 — AI 12번(모델은 NVIDIA_MODEL)
    uv run --env-file .env python -m scripts.interview_eval exaone --pause 40            # EXAONE으로 비교(D-027)
    uv run --env-file .env python -m scripts.interview_eval nvidia --limit 2             # 앞에서부터 카드 2장으로 먼저 시험
    uv run python -m scripts.interview_eval --score eval/interview/results/<파일>.json   # 사람 판정(human)을 적은 뒤 다시 채점

- 카드: F-006 평가 노트(eval/cards)로 AI 없이 만든 저장 카드(posting_evaluation.build_eval_cards — F-008 평가와 같은 카드).
- 임시 SQLite DB에 평가용 사용자 · 노트 · 카드를 올려 돌린다. 개발 DB · 내 계정은 건드리지 않는다.
- --planted: 카드마다 진짜 질문 3 + 일부러 만든 질문 4(종류마다 1)를 실제 검사 · 저장 흐름에 넣는다(D-005). 판정이 없다.
- AI 질문 평가의 '전제 있음' 판정은 채점 AI 없이 규칙 + 사람(app/services/interview_evaluation.py). 결과 파일의 저장된
  질문마다 human에 true(전제 있음) · false(없음)를 적고 --score로 다시 채점한다. summary.labels_pending이 0이 되면 최종 수치.
- 결과는 eval/interview/results/interview-<planted | provider>-<시각>.json. 카드 하나가 끝날 때마다 다시 쓴다
  ("complete": false면 중간에 멈춤). 임시 파일에 쓴 뒤 바꿔 끼워, 쓰다 멈춰도 이전 내용(사람 판정)이 남는다.
- mock이면 멈춘다(--allow-mock은 흐름 확인용). 키 · 주소는 출력하지 않는다. pytest에는 넣지 않는다.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Card
from app.db.session import create_db_engine
from app.llm import (
    LLMClient,
    LLMConfigError,
    MockLLMClient,
    get_llm_client,
    load_llm_settings,
)
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.card_evaluation import NoteKey, parse_answer_key
from app.services.eval_retry import RetryPolicy
from app.services.interview_evaluation import (
    RULE_PREMISE,
    CardEvalResult,
    evaluate_card,
    evaluate_planted_card,
    result_from_dict,
    result_to_dict,
    summarize,
    summarize_planted,
)
from app.services.interview_mock import mock_interview_responder
from app.services.posting_evaluation import build_eval_cards
from app.services.quiz_evaluation import PatientClient
from scripts.eval_files import PROVIDER_HELP, REAL_PROVIDERS, write_json_atomic

BACKEND_DIR = Path(__file__).resolve().parent.parent
CARD_ANSWERS_PATH = BACKEND_DIR / "eval" / "cards" / "answers.json"
NOTES_DIR = CARD_ANSWERS_PATH.parent / "notes"
RESULTS_DIR = BACKEND_DIR / "eval" / "interview" / "results"
EVAL_PROFILE = GoogleProfile(sub="interview-eval", email="interview-eval@example.invalid", name="면접 질문 평가")
EVAL_DAILY_LIMIT = 1000  # 임시 DB의 가상 사용자라 서비스에는 영향 없음
MODE_AI = "ai"  # 실제 AI가 만든 질문(참고 수치)
MODE_PLANTED = "planted"  # 심은 질문(D-005, 핵심 수치)
ERROR_DETAIL_CHARS = 300  # 결과 파일에 남기는 예상 못 한 오류 메시지 길이

Summary = Mapping[str, Any]


@dataclass(frozen=True)
class EvalOptions:
    """명령줄 옵션(실행 한 번)."""

    mode: str
    provider: str | None
    limit: int | None
    allow_mock: bool
    pause: float
    retries: int
    retry_wait: float


def _pct(value: object) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, float) else "-"


def _load_card_keys() -> dict[str, NoteKey]:
    """카드 정답지(F-006 평가). 틀리면 AI를 부르기 전에 멈춘다."""
    return parse_answer_key(json.loads(CARD_ANSWERS_PATH.read_text(encoding="utf-8")))


# --- 출력 ---


def _status_line(result: CardEvalResult) -> str:
    if result.error and not result.questions:
        detail = f" — {result.error_detail}" if result.error_detail else ""
        return f"실패 {result.error}{detail}" + (f" · 다시 시도 {result.retries}번" if result.retries else "")
    planted = [record for record in result.questions if record.planted]
    if planted:
        verdicts = ", ".join(f"{record.planted}={'놓침' if record.kept else '잡음'}" for record in planted)
        genuine = [record for record in result.questions if not record.planted]
        return f"진짜 {sum(1 for r in genuine if r.kept)}/{len(genuine)} 저장 · {verdicts}"
    parts = [
        f"받음 {result.received}",
        f"저장 {len(result.questions)}",
        f"규칙상 전제 {sum(1 for record in result.questions if record.rule == RULE_PREMISE)}",
    ]
    if result.seconds is not None:
        parts.append(f"{result.seconds:.0f}초")
    if result.retries:
        parts.append(f"다시 시도 {result.retries}번")
    return " · ".join(parts)


def _print_summary(provider: str, s: Summary, waits: list[float]) -> None:
    lines = [
        f"AI {provider} · 카드 {s['cards']}장(질문 저장 {s['cards_written']}) · 받은 질문 {s['received']} · 저장 {s['saved']}",
        f"카드에 없는 내용을 전제로 한 질문: {s['premise']}/{s['saved']} = {_pct(s['premise_rate'])} (카드당 {s['premise_per_card']})"
        f"  · 사람 확인 전 {s['labels_pending']}개" + ("  ← 아직 최종 아님" if s["labels_pending"] else ""),
        f"규칙만으로 전제 있음: {s['premise_by_rule']}",
        f"검사가 버린 이유: {s['drop_reasons']}",
        f"실패 {s['failures']}번 · 시간 평균 {s['seconds_avg']}초 · 최대 {s['seconds_max']}초 · 사용량 {s['usage']}",
    ]
    if waits:
        lines.append(f"429로 기다림: {len(waits)}번 · 합계 {sum(waits):.0f}초")
    print("\n" + "\n".join(lines))


def _print_planted_summary(s: Summary) -> None:
    lines = [
        f"심은 질문 평가(AI 없음) · 카드 {s['cards']}장 · 질문 {s['questions']}개(진짜 {s['genuine']} · 심음 {s['planted']})",
        f"심은 질문을 검사가 잡은 비율: {s['planted_caught']}/{s['planted']} = {_pct(s['catch_rate'])}",
        "종류별: " + " · ".join(f"{kind} {c['caught']}/{c['planted']}" for kind, c in s["by_type"].items()),
        f"진짜 질문을 검사가 잘못 버림: {s['genuine_dropped']}/{s['genuine']}",
        f"검사가 버린 이유: {s['drop_reasons']} · 실패 {s['failures']}번",
    ]
    print("\n" + "\n".join(lines))


def _summary(mode: str, results: list[CardEvalResult]) -> dict[str, object]:
    return summarize_planted(results) if mode == MODE_PLANTED else summarize(results)


def _print(mode: str, provider: str, summary: Summary, waits: list[float]) -> None:
    if mode == MODE_PLANTED:
        _print_planted_summary(summary)
    else:
        _print_summary(provider, summary, waits)
    if summary.get("failures"):  # 실패한 카드는 분모에서 빠진다 — 정상 결과로 읽지 않게
        print(f"⚠️ 실패한 카드 {summary['failures']}장 — 위 수치는 나머지 카드만 반영해요. 결과 파일의 error · error_detail을 보세요.")


# --- 결과 파일 ---


def _write_results(
    out: Path, *, mode: str, provider: str, model: str, results: list[CardEvalResult], waits: list[float], done: bool
) -> None:
    write_json_atomic(
        out,
        {
            "mode": mode,
            "provider": provider,
            "model": model,
            "complete": done,
            "summary": _summary(mode, results),
            "rate_limit_waits": waits,
            "cards": [result_to_dict(result) for result in results],
        },
    )


# --- 평가 ---


def _failed(experience: str, title: str, exc: BaseException) -> CardEvalResult:
    """예상 못 한 오류로 멈춘 카드. 종류와 메시지 앞부분을 남긴다(평가 세트 · 코드 오류의 원인을 보려고)."""
    return CardEvalResult(
        card=experience, title=title, error=type(exc).__name__, error_detail=str(exc)[:ERROR_DETAIL_CHARS] or None
    )


async def _evaluate_all(
    card_keys: Mapping[str, NoteKey],
    notes_dir: Path,
    *,
    mode: str,
    limit: int | None,
    client: LLMClient | None,
    policy: RetryPolicy,
    on_result: Callable[[list[CardEvalResult]], None],
) -> list[CardEvalResult]:
    """평가 카드를 만들고 카드마다 평가한다. 한 카드의 예상 못 한 오류로 평가 전체를 멈추지 않는다(종류만 실패로 기록)."""
    results: list[CardEvalResult] = []
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_db_engine(f"sqlite:///{Path(tmp) / 'interview_eval.db'}")
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        try:
            user = get_or_create_google_user(db, EVAL_PROFILE)
            user.daily_limit = EVAL_DAILY_LIMIT
            db.commit()
            card_experience = build_eval_cards(db, user_id=user.id, notes_dir=notes_dir, card_keys=card_keys)
            targets = sorted(card_experience.items(), key=lambda item: item[1])[:limit]
            print(f"평가 카드 {len(card_experience)}장을 만들었어요(AI 없이). 이번에 {len(targets)}장을 평가해요.", flush=True)
            for number, (card_id, experience) in enumerate(targets, start=1):
                card = db.get(Card, card_id)
                title = card.title if card is not None else ""
                print(f"[{number}/{len(targets)}] {experience} · {title} …", flush=True)
                try:
                    if mode == MODE_PLANTED:
                        result = await evaluate_planted_card(
                            db, user_id=user.id, card_id=card_id, experience=experience, title=title
                        )
                    else:
                        assert client is not None
                        result = await evaluate_card(
                            db, user_id=user.id, card_id=card_id, experience=experience, title=title,
                            client=client, policy=policy,
                        )
                except Exception as exc:  # noqa: BLE001 — 한 카드의 예상 못 한 오류로 평가 전체를 멈추지 않는다
                    db.rollback()
                    result = _failed(experience, title, exc)
                print(f"    {_status_line(result)}", flush=True)
                results.append(result)
                on_result(results)
        finally:
            db.close()
            engine.dispose()
    return results


async def _run(options: EvalOptions) -> int:
    mode = options.mode
    try:
        card_keys = _load_card_keys()
    except (ValueError, KeyError, OSError) as exc:
        print(f"평가 세트 오류: {exc}")
        return 1
    writer: LLMClient | None = None
    waits: list[float] = []
    provider_name, model = MODE_PLANTED, "none"
    if mode == MODE_AI:
        try:
            settings = load_llm_settings(options.provider)
            client = get_llm_client(settings)
        except LLMConfigError as exc:
            print(f"AI 설정 오류: {exc}")
            return 1
        patient = PatientClient(client, min_interval=options.pause)
        waits = patient.waits
        writer = patient
        provider_name, model = settings.provider, settings.model
        if settings.provider == "mock":
            if not options.allow_mock:
                print(f"mock으로는 평가 수치에 뜻이 없어요. 제공자를 넘겨 주세요({REAL_PROVIDERS}). 예) python -m scripts.interview_eval nvidia")
                return 1
            writer = MockLLMClient(responder=mock_interview_responder)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"interview-{provider_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

    def save(results: list[CardEvalResult], *, done: bool = False) -> None:
        _write_results(out, mode=mode, provider=provider_name, model=model, results=results, waits=waits, done=done)

    results = await _evaluate_all(
        card_keys, NOTES_DIR, mode=mode, limit=options.limit, client=writer,
        policy=RetryPolicy(retries=options.retries, wait=options.retry_wait), on_result=save,
    )
    save(results, done=True)
    _print(mode, provider_name, _summary(mode, results), waits)
    print(f"결과 파일: {out.relative_to(BACKEND_DIR) if out.is_relative_to(BACKEND_DIR) else out}")
    return 0


def _rescore(path: Path) -> int:
    """사람 판정(human)을 적은 결과 파일을 다시 채점해 summary를 바꿔 쓴다. AI는 부르지 않는다."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        results = [result_from_dict(item) for item in payload["cards"]]
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"결과 파일 오류: {exc}")
        return 1
    mode = str(payload.get("mode") or MODE_AI)
    payload["summary"] = _summary(mode, results)
    try:
        write_json_atomic(path, payload)
    except OSError as exc:  # Windows에서 편집기가 파일을 잡고 있으면 바꿔 끼우기가 막힌다(4차 리뷰 R3)
        print(f"결과 파일을 못 썼어요({type(exc).__name__}) — 파일을 연 프로그램을 닫고 다시 해 주세요. 원래 파일은 그대로예요.")
        return 1
    _print(mode, str(payload.get("provider")), payload["summary"], list(payload.get("rate_limit_waits") or []))
    return 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # Windows cp949 파이프 출력(T-003)
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="면접 질문 평가(F-009 완료 기준 4)")
    parser.add_argument("provider", nargs="?", default=None, help=PROVIDER_HELP)
    parser.add_argument("--planted", action="store_true", help="심은 질문 평가(D-005, AI 안 부름)")
    parser.add_argument("--score", type=Path, default=None, help="사람 판정을 적은 결과 파일을 다시 채점(AI 안 부름)")
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 카드 몇 장만(1 이상)")
    parser.add_argument("--allow-mock", action="store_true", help="흐름 확인용으로 mock도 허용(수치는 뜻 없음)")
    parser.add_argument("--pause", type=float, default=20.0, help="AI 호출 사이 최소 간격(초)")
    parser.add_argument("--retries", type=int, default=2, help="AI 서버 오류(500 · 429)면 카드마다 다시 해 볼 횟수(0 이상)")
    parser.add_argument("--retry-wait", type=float, default=60.0, help="다시 해 보기 전에 쉬는 시간(초)")
    args = parser.parse_args()
    if args.score is not None:
        raise SystemExit(_rescore(args.score))
    if args.retries < 0 or args.pause < 0 or args.retry_wait < 0:
        parser.error("--retries · --pause · --retry-wait는 0 이상이어야 해요.")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit은 1 이상이어야 해요.")
    options = EvalOptions(
        mode=MODE_PLANTED if args.planted else MODE_AI,
        provider=args.provider,
        limit=args.limit,
        allow_mock=args.allow_mock,
        pause=args.pause,
        retries=args.retries,
        retry_wait=args.retry_wait,
    )
    raise SystemExit(asyncio.run(_run(options)))


if __name__ == "__main__":
    main()
