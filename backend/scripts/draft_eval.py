"""자소서 초안 평가 실행 — '지어낸 문장을 검사가 잡은 비율' · '근거 없이 남은 문장 수'를 잰다 (F-008 완료 기준 4, D-005).

backend 폴더에서:
    uv run python -m scripts.draft_eval --planted                                   # 심은 문장 평가(D-005, AI 안 부름) — 핵심 수치
    uv run --env-file .env python -m scripts.draft_eval exaone --pause 40            # AI 초안 평가: 공고 6개 × 문항 2개 — AI 12번
    uv run --env-file .env python -m scripts.draft_eval exaone --limit 1 --pause 40  # 앞에서부터 공고 1개(문항 2개)로 먼저 시험
    uv run python -m scripts.draft_eval --score eval/drafts/results/<파일>.json     # 사람 판정(human)을 적은 뒤 다시 채점(AI 안 부름)

- 공고 · 정답 카드: F-007 평가 세트(eval/postings), 문항: eval/drafts/questions.json(공고마다 보통 1 · 함정 1).
- 카드: F-006 평가 노트로 AI 없이 만든다(posting_evaluation.build_eval_cards). 매칭은 정답지 카드로 고정(AI 없이).
- 임시 SQLite DB에 평가용 사용자 · 노트 · 카드를 올려 돌린다. 개발 DB · 내 계정은 건드리지 않는다.
- --planted: 문항마다 진짜 문장 7 + 일부러 지어낸 문장 3(종류를 돌아가며)을 실제 저장 · 검사 흐름에 넣는다(D-005).
  종류별 잡은 수. 판정이 들어가지 않는다.
- AI 초안 평가의 '지어냄' 판정은 채점 AI 없이 규칙 + 사람(app/services/draft_evaluation.py). 결과 파일의 문장마다
  human에 true(지어냄) · false(아님)를 적고 --score로 다시 채점한다. summary.labels_pending이 0이 되면 최종 수치.
- 결과는 eval/drafts/results/drafts-<planted | provider>-<시각>.json. 문항 하나가 끝날 때마다 다시 쓴다
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

from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
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
from app.services.draft_evaluation import (
    RULE_INVENTED,
    QuestionEvalResult,
    QuestionKey,
    create_eval_application,
    evaluate_planted_question,
    evaluate_question,
    parse_question_key,
    result_from_dict,
    result_to_dict,
    seed_fixed_matches,
    summarize,
    summarize_planted,
)
from app.services.draft_mock import mock_draft_responder
from app.services.eval_retry import RetryPolicy
from app.services.posting_evaluation import (
    PostingKey,
    build_eval_cards,
    check_card_references,
    key_spans,
    parse_posting_key,
)
from app.services.quiz_evaluation import PatientClient
from scripts.eval_files import PROVIDER_HELP, REAL_PROVIDERS, write_json_atomic

BACKEND_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BACKEND_DIR / "eval" / "drafts"
QUESTIONS_PATH = EVAL_DIR / "questions.json"
RESULTS_DIR = EVAL_DIR / "results"
EVAL_PROFILE = GoogleProfile(sub="draft-eval", email="draft-eval@example.invalid", name="자소서 평가")
EVAL_DAILY_LIMIT = 1000  # 임시 DB의 가상 사용자라 서비스에는 영향 없음
MODE_AI = "ai"  # 실제 AI가 쓴 초안(참고 수치)
MODE_PLANTED = "planted"  # 심은 문장(D-005, 핵심 수치)
ERROR_DETAIL_CHARS = 300  # 결과 파일에 남기는 예상 못 한 오류 메시지 길이


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

Plan = list[tuple[Path, str, PostingKey, tuple[QuestionKey, ...]]]
CardKeys = dict[str, NoteKey]
Summary = Mapping[str, Any]


def _pct(value: object) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, float) else "-"


def _load() -> tuple[Plan, CardKeys, Path]:
    """(공고 파일, 본문, 공고 정답, 문항) 목록과 카드 정답지. 파일끼리 어긋나면 AI를 부르기 전에 멈춘다."""
    raw = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    posting_answers = BACKEND_DIR / str(raw["postings_from"])
    posting_raw = json.loads(posting_answers.read_text(encoding="utf-8"))
    posting_keys = parse_posting_key(posting_raw)
    question_keys = parse_question_key(raw, posting_keys)
    card_answers_path = BACKEND_DIR / str(posting_raw["cards_from"])
    card_keys = parse_answer_key(json.loads(card_answers_path.read_text(encoding="utf-8")))
    check_card_references(posting_keys, card_keys)
    postings_dir = posting_answers.parent / "postings"
    plan: Plan = []
    for name in sorted(posting_keys):
        path = postings_dir / name
        text = path.read_text(encoding="utf-8").strip()
        key_spans(text, posting_keys[name])
        plan.append((path, text, posting_keys[name], question_keys[name]))
    return plan, card_keys, card_answers_path.parent / "notes"


# --- 출력 ---


def _status_line(result: QuestionEvalResult) -> str:
    if result.error and not result.sentences:
        detail = f" — {result.error_detail}" if result.error_detail else ""
        return f"실패 {result.error}{detail}" + (f" · 다시 시도 {result.retries}번" if result.retries else "")
    records = result.sentences
    planted = [record for record in records if record.planted]
    if planted:
        verdicts = ", ".join(f"{record.planted}={'놓침' if record.supported else '잡음'}" for record in planted)
        caught = sum(1 for record in planted if not record.supported)
        return f"문장 {len(records)} · 심음 {len(planted)} · 잡음 {caught} · {verdicts}"
    parts = [
        f"문장 {len(records)}",
        f"근거 없음 {sum(1 for record in records if not record.supported)}",
        f"규칙상 지어냄 {sum(1 for record in records if record.rule == RULE_INVENTED)}",
        f"{result.chars}/{result.char_limit or '-'}자",
    ]
    if result.seconds is not None:
        parts.append(f"{result.seconds:.0f}초")
    if result.retries:
        parts.append(f"다시 시도 {result.retries}번")
    return " · ".join(parts)


def _print_summary(provider: str, s: Summary, waits: list[float]) -> None:
    rule = s["rule_only"]
    kinds = s["by_kind"]
    lines = [
        f"AI {provider} · 문항 {s['questions']}개(초안 {s['drafts_written']}) · 문장 {s['sentences']}개",
        f"근거 없이 남은 문장: {s['unsupported_sentences']}개 (초안당 {s['unsupported_per_draft']})",
        f"지어낸 문장을 검사가 잡은 비율: {s['fabricated_caught']}/{s['fabricated']} = {_pct(s['catch_rate'])}"
        f"  · 사람 확인 전 {s['labels_pending']}문장" + ("  ← 아직 최종 아님" if s["labels_pending"] else ""),
        f"검사를 통과한 지어낸 문장(놓침): {s['fabricated_missed']} · 지어내지 않았는데 근거 없음: {s['unsupported_not_fabricated']}",
        f"규칙만: 지어냄 {rule['fabricated']} · 잡음 {rule['caught']} ({_pct(rule['catch_rate'])}) · 문항 말만 겹침 {rule['from_question']}",
        "문항 종류별: "
        + " · ".join(
            f"{kind} 문장 {c['sentences']} 근거 없음 {c['unsupported']} 지어냄 {c['fabricated']} 잡음 {c['caught']}"
            for kind, c in kinds.items()
        ),
        f"근거를 못 붙인 이유: {s['drop_reasons']} · 글자 수 넘음 {s['over_limit']}",
        f"실패 {s['failures']}번 · 시간 평균 {s['seconds_avg']}초 · 최대 {s['seconds_max']}초 · 사용량 {s['usage']}",
    ]
    if waits:
        lines.append(f"429로 기다림: {len(waits)}번 · 합계 {sum(waits):.0f}초")
    print("\n" + "\n".join(lines))


def _print_planted_summary(s: Summary) -> None:
    lines = [
        f"심은 문장 평가(AI 없음) · 문항 {s['questions']}개 · 문장 {s['sentences']}개(진짜 {s['genuine']} · 심음 {s['planted']})",
        f"심은 지어낸 문장을 검사가 잡은 비율: {s['planted_caught']}/{s['planted']} = {_pct(s['catch_rate'])}",
        "종류별: " + " · ".join(f"{kind} {c['caught']}/{c['planted']}" for kind, c in s["by_type"].items()),
        f"진짜 문장을 '근거 없음'으로 잘못 경고: {s['genuine_flagged']}/{s['genuine']}",
        f"근거를 못 붙인 이유: {s['drop_reasons']} · 실패 {s['failures']}번",
    ]
    print("\n" + "\n".join(lines))


def _summary(mode: str, results: list[QuestionEvalResult]) -> dict[str, object]:
    return summarize_planted(results) if mode == MODE_PLANTED else summarize(results)


def _print(mode: str, provider: str, summary: Summary, waits: list[float]) -> None:
    if mode == MODE_PLANTED:
        _print_planted_summary(summary)
    else:
        _print_summary(provider, summary, waits)
    if summary.get("failures"):  # 실패한 문항은 분모에서 빠진다 — 정상 결과로 읽지 않게(6차 리뷰 R3)
        print(f"⚠️ 실패한 문항 {summary['failures']}개 — 위 수치는 나머지 문항만 반영해요. 결과 파일의 error · error_detail을 보세요.")


# --- 결과 파일 ---




def _write_results(
    out: Path, *, mode: str, provider: str, model: str, results: list[QuestionEvalResult], waits: list[float], done: bool
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
            "questions": [result_to_dict(result) for result in results],
        },
    )


# --- 평가 ---


def _failed(path: Path, index: int, key: QuestionKey, exc: BaseException) -> QuestionEvalResult:
    """예상 못 한 오류로 멈춘 문항. 종류와 메시지 앞부분을 남긴다(평가 세트 · 코드 오류의 원인을 보려고)."""
    return QuestionEvalResult(
        file_name=path.name, index=index, kind=key.kind, question=key.text, char_limit=key.char_limit,
        error=type(exc).__name__, error_detail=str(exc)[:ERROR_DETAIL_CHARS] or None,
    )


async def _evaluate_all(
    plan: Plan,
    card_keys: CardKeys,
    notes_dir: Path,
    *,
    mode: str,
    client: LLMClient | None,
    policy: RetryPolicy,
    on_result: Callable[[list[QuestionEvalResult]], None],
) -> list[QuestionEvalResult]:
    """공고마다 공고 · 문항 저장 → 매칭 고정 → 문항마다 평가. 심은 문장 평가는 문항 순서대로 심는 종류를 돌린다.

    한 공고 · 한 문항의 예상 못 한 오류로 평가 전체를 멈추지 않는다(종류만 실패로 기록).
    """
    results: list[QuestionEvalResult] = []

    async def evaluate(db: Session, user_id: int, ids: tuple[int, int], path: Path, index: int, key: QuestionKey,
                       card_experience: dict[int, str]) -> QuestionEvalResult:
        application_id, question_id = ids
        if mode == MODE_PLANTED:
            return await evaluate_planted_question(
                db, user_id=user_id, application_id=application_id, question_id=question_id, file_name=path.name,
                index=index, key=key, card_experience=card_experience, rotation=len(results),
            )
        assert client is not None
        return await evaluate_question(
            db, user_id=user_id, application_id=application_id, question_id=question_id, file_name=path.name,
            index=index, key=key, card_experience=card_experience, client=client, policy=policy,
        )

    with tempfile.TemporaryDirectory() as tmp:
        engine = create_db_engine(f"sqlite:///{Path(tmp) / 'draft_eval.db'}")
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        try:
            user = get_or_create_google_user(db, EVAL_PROFILE)
            user.daily_limit = EVAL_DAILY_LIMIT
            db.commit()
            card_experience = build_eval_cards(db, user_id=user.id, notes_dir=notes_dir, card_keys=card_keys)
            experience_card = {experience: card_id for card_id, experience in card_experience.items()}
            print(f"평가 카드 {len(card_experience)}장을 만들었어요(AI 없이, 경험 구간 문단으로).", flush=True)
            for number, (path, text, posting_key, questions) in enumerate(plan, start=1):
                try:
                    application_id, question_ids = create_eval_application(
                        db, user_id=user.id, file_name=path.name, posting_text=text, questions=questions
                    )
                    seed_fixed_matches(
                        db, user_id=user.id, application_id=application_id, posting_text=text,
                        key=posting_key, experience_card=experience_card,
                    )
                except Exception as exc:  # noqa: BLE001 — 공고 준비가 틀리면 그 공고의 문항만 실패로 남긴다
                    db.rollback()
                    print(f"[{number}/{len(plan)}] {path.name} 준비 실패: {type(exc).__name__} {exc}", flush=True)
                    results.extend(_failed(path, index, key, exc) for index, key in enumerate(questions, start=1))
                    on_result(results)
                    continue
                for index, (question_id, key) in enumerate(zip(question_ids, questions, strict=True), start=1):
                    print(f"[{number}/{len(plan)}] {path.name} 문항 {index}({key.kind}) …", flush=True)
                    try:
                        result = await evaluate(
                            db, user.id, (application_id, question_id), path, index, key, card_experience
                        )
                    except Exception as exc:  # noqa: BLE001 — 한 문항의 예상 못 한 오류로 평가 전체를 멈추지 않는다
                        db.rollback()
                        result = _failed(path, index, key, exc)
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
        plan, card_keys, notes_dir = _load()
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
                print(f"mock으로는 평가 수치에 뜻이 없어요. 제공자를 넘겨 주세요({REAL_PROVIDERS}). 예) python -m scripts.draft_eval nvidia")
                return 1
            writer = MockLLMClient(responder=mock_draft_responder)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"drafts-{provider_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

    def save(results: list[QuestionEvalResult], *, done: bool = False) -> None:
        _write_results(out, mode=mode, provider=provider_name, model=model, results=results, waits=waits, done=done)

    results = await _evaluate_all(
        plan[: options.limit], card_keys, notes_dir,
        mode=mode, client=writer, policy=RetryPolicy(retries=options.retries, wait=options.retry_wait), on_result=save,
    )
    save(results, done=True)
    _print(mode, provider_name, _summary(mode, results), waits)
    print(f"결과 파일: {out.relative_to(BACKEND_DIR) if out.is_relative_to(BACKEND_DIR) else out}")
    return 0


def _rescore(path: Path) -> int:
    """사람 판정(human)을 적은 결과 파일을 다시 채점해 summary를 바꿔 쓴다. AI는 부르지 않는다."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        results = [result_from_dict(item) for item in payload["questions"]]
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"결과 파일 오류: {exc}")
        return 1
    mode = str(payload.get("mode") or MODE_AI)
    payload["summary"] = _summary(mode, results)
    write_json_atomic(path, payload)
    _print(mode, str(payload.get("provider")), payload["summary"], list(payload.get("rate_limit_waits") or []))
    return 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # Windows cp949 파이프 출력(T-003)
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="자소서 초안 평가(F-008 완료 기준 4)")
    parser.add_argument("provider", nargs="?", default=None, help=PROVIDER_HELP)
    parser.add_argument("--planted", action="store_true", help="심은 문장 평가(D-005, AI 안 부름)")
    parser.add_argument("--score", type=Path, default=None, help="사람 판정을 적은 결과 파일을 다시 채점(AI 안 부름)")
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 공고 몇 개만(1 이상, 공고마다 문항 2개)")
    parser.add_argument("--allow-mock", action="store_true", help="흐름 확인용으로 mock도 허용(수치는 뜻 없음)")
    parser.add_argument("--pause", type=float, default=20.0, help="AI 호출 사이 최소 간격(초)")
    parser.add_argument("--retries", type=int, default=2, help="AI 서버 오류(500 · 429)면 문항마다 다시 해 볼 횟수(0 이상)")
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
