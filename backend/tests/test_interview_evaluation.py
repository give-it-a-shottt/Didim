"""면접 질문 평가(F-009 완료 기준 4) 테스트 — 심은 질문을 실제 검사 흐름에 넣는지, 규칙 + 사람 판정으로 세는지, 실패 경로,
실행 스크립트의 다시 채점 · 카드 실패 처리."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CardInterviewClaim
from app.llm import LLMUnavailable, MockLLMClient
from app.services import interview_evaluation
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.card_evaluation import ExperienceKey, NoteKey
from app.services.draft_evaluation import SentText
from app.services.eval_retry import RetryPolicy
from app.services.interview_evaluation import (
    PLANT_ADDED_PREMISE,
    PLANT_FAKE_QUOTE,
    PLANT_NO_EVIDENCE,
    PLANT_OTHER_SLOT,
    PLANT_TYPES,
    RULE_PREMISE,
    CardEvalResult,
    QuestionRecord,
    evaluate_card,
    evaluate_planted_card,
    planted_questions,
    result_from_dict,
    result_to_dict,
    rule_verdict,
    summarize,
    summarize_planted,
)
from app.services.interview_writing import SentFields
from app.services.posting_evaluation import build_eval_cards
from app.services.posting_matching import CardText
from scripts import interview_eval

NOTE = "# 노트\n\n## 화면 만들기\n상품 목록이 느렸다.\n\nReact.memo로 카드를 감쌌다.\n\n렌더링이 40ms로 줄었다.\n"
CARD_KEYS = {"n.md": NoteKey(experiences=(ExperienceKey(id="e1", sections=("화면 만들기",)),))}


def _setup(db: Session, tmp_path: Path) -> tuple[int, int]:
    user = get_or_create_google_user(db, GoogleProfile(sub="interview-eval-test", email="i@example.com", name="i"))
    user.daily_limit = 1000
    db.commit()
    (tmp_path / "n.md").write_text(NOTE, encoding="utf-8")
    mapping = build_eval_cards(db, user_id=user.id, notes_dir=tmp_path, card_keys=CARD_KEYS)
    return user.id, next(iter(mapping))


def _claims(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(CardInterviewClaim)) or 0


# --- 규칙 판정 ---


def test_rule_flags_numbers_and_words_missing_from_the_card() -> None:
    card = SentText.of(["화면 만들기", "React.memo로 카드를 감쌌다.", "렌더링이 40ms로 줄었다."])
    assert rule_verdict("팀원 5명과 Kubernetes를 썼다는데 어땠나요?", card) == (RULE_PREMISE, ["5", "kubernetes"])
    assert rule_verdict("React.memo로 40ms까지 줄인 방법은요?", card) == (None, [])  # 카드에 있는 말만
    assert rule_verdict("팀장과 갈등이 있었을 때 어떻게 했나요?", card) == (None, [])  # 한글 전제는 규칙이 못 잡음 → 사람


# --- 심은 질문 만들기 ---


def _sent(fields: dict[str, tuple[str | None, str | None]]) -> SentFields:
    card = CardText(id=1, title="t", fields=fields)
    return SentFields(card=card, slots=tuple(slot for slot in ("situation", "task", "action", "result") if slot in fields))


def test_planted_questions_put_one_of_each_kind_between_three_genuine_ones() -> None:
    sent = _sent({"situation": ("상품 목록이 느렸다.", None), "action": (None, "React.memo로 카드를 감쌌다.")})
    items, labels = planted_questions(sent)
    assert labels == [None, PLANT_NO_EVIDENCE, None, PLANT_FAKE_QUOTE, None, PLANT_OTHER_SLOT, PLANT_ADDED_PREMISE]
    by_label = dict(zip(labels, items, strict=False))
    genuine = [item for item, label in zip(items, labels, strict=True) if label is None]
    for item in genuine:  # 진짜 질문의 인용은 그 칸 글에 글자 그대로 있다
        assert any(item["quote"] in (text or "") for text in sent.card.fields[item["slot"]])
    assert len({item["question"] for item in items}) == len(items)  # 저장된 질문을 글로 짝짓는다
    assert by_label[PLANT_NO_EVIDENCE]["quote"] == ""
    other = by_label[PLANT_OTHER_SLOT]  # 진짜 조각이지만 붙인 칸에는 없다
    assert any(other["quote"] in (text or "") for slot in sent.slots for text in sent.card.fields[slot])
    assert all(other["quote"] not in (text or "") for text in sent.card.fields[other["slot"]])


def test_other_slot_uses_an_unsent_slot_when_the_card_has_one_slot() -> None:
    items, labels = planted_questions(_sent({"situation": ("상품 목록이 느렸다.", None)}))
    assert items[labels.index(PLANT_OTHER_SLOT)]["slot"] == "task"  # 보내지 않은 칸 → 검사기가 버려야 한다


# --- 심은 질문 평가 (실제 검사 · 저장 흐름) ---


def test_planted_card_runs_the_real_check_and_finds_the_premise_blind_spot(db_session: Session, tmp_path: Path) -> None:
    user_id, card_id = _setup(db_session, tmp_path)
    result = asyncio.run(evaluate_planted_card(db_session, user_id=user_id, card_id=card_id, experience="e1", title="화면 만들기"))
    kept = {record.planted: record.kept for record in result.questions}
    assert [record.kept for record in result.questions if record.planted is None] == [True, True, True]
    assert kept == {None: True, PLANT_NO_EVIDENCE: False, PLANT_FAKE_QUOTE: False, PLANT_OTHER_SLOT: False, PLANT_ADDED_PREMISE: True}
    summary = summarize_planted([result])
    assert (summary["planted"], summary["planted_caught"], summary["genuine_dropped"]) == (4, 3, 0)
    assert {kind: summary["by_type"][kind]["caught"] for kind in PLANT_TYPES} == {  # type: ignore[index]
        PLANT_NO_EVIDENCE: 1, PLANT_FAKE_QUOTE: 1, PLANT_OTHER_SLOT: 1, PLANT_ADDED_PREMISE: 0,
    }
    assert _claims(db_session) == 0


def test_planted_failure_before_saving_releases_the_claim(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user_id, card_id = _setup(db_session, tmp_path)

    def broken(_sent: SentFields) -> None:
        raise ValueError("평가 세트 오류")

    monkeypatch.setattr(interview_evaluation, "planted_questions", broken)
    with pytest.raises(ValueError):
        asyncio.run(evaluate_planted_card(db_session, user_id=user_id, card_id=card_id, experience="e1", title="t"))
    assert _claims(db_session) == 0


# --- AI 질문 평가 (실제 서비스 흐름) ---


def _evaluate(db: Session, ids: tuple[int, int], client: MockLLMClient, retries: int = 0) -> tuple[CardEvalResult, list[float]]:
    user_id, card_id = ids
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    result = asyncio.run(evaluate_card(
        db, user_id=user_id, card_id=card_id, experience="e1", title="화면 만들기", client=client,
        policy=RetryPolicy(retries=retries, wait=5, sleep=fake_sleep),
    ))
    return result, waits


def test_evaluate_card_runs_the_real_flow_and_labels_saved_questions(db_session: Session, tmp_path: Path) -> None:
    ids = _setup(db_session, tmp_path)
    reply = json.dumps({"questions": [
        {"slot": "situation", "question": "팀원 5명이 함께 겪은 문제였나요?", "quote": "상품 목록이 느렸다."},
        {"slot": "action", "question": "React.memo를 고른 이유는 무엇인가요?", "quote": "React.memo로 카드를 감쌌다."},
        {"slot": "result", "question": "성능을 어떻게 쟀나요?", "quote": "렌더링이 10ms로 줄었다."},  # 바꿔 쓴 인용 → 버림
    ]}, ensure_ascii=False)
    result, waits = _evaluate(db_session, ids, MockLLMClient([LLMUnavailable("down"), reply]), retries=1)

    assert (result.error, result.retries, waits, result.usage.calls) == (None, 1, [5], 2)
    assert (result.received, result.fields_sent, result.drop_reasons) == (3, 3, {"quote_not_found": 1})
    premise, clean = result.questions
    assert (premise.id, premise.kept, premise.rule, premise.rule_tokens) == ("e1-q1", True, RULE_PREMISE, ["5"])
    assert (clean.rule, clean.needs_human) == (None, True)  # 규칙으로 못 가름 → 사람 확인
    assert _claims(db_session) == 0


def test_failure_after_retries_counts_as_no_questions_and_releases_the_claim(db_session: Session, tmp_path: Path) -> None:
    ids = _setup(db_session, tmp_path)
    result, waits = _evaluate(db_session, ids, MockLLMClient([LLMUnavailable("down"), LLMUnavailable("down")]), retries=1)
    assert (result.error, result.retries, waits, result.questions) == ("LLMUnavailable", 1, [5], [])
    assert _claims(db_session) == 0


def test_no_questions_left_is_recorded_as_an_error(db_session: Session, tmp_path: Path) -> None:
    ids = _setup(db_session, tmp_path)
    reply = json.dumps({"questions": [{"slot": "situation", "question": "왜요?", "quote": "카드에 없는 글이다."}]}, ensure_ascii=False)
    result, _ = _evaluate(db_session, ids, MockLLMClient([reply]))
    assert (result.error, result.questions, result.drop_reasons) == ("no_questions", [], {"quote_not_found": 1})


# --- 요약 · 결과 파일 ---


def _record(rid: str, *, rule: str | None = None, human: bool | None = None, kept: bool = True) -> QuestionRecord:
    return QuestionRecord(id=rid, question="q", slot="action", quote="인용 글이다.", kept=kept, rule=rule, human=human)


def test_summary_counts_premise_questions_and_pending_labels() -> None:
    results = [
        CardEvalResult(card="e1", title="a", received=4, questions=[
            _record("e1-q1", rule=RULE_PREMISE),  # 규칙으로 전제 있음
            _record("e1-q2", human=True),  # 사람이 전제 있음
            _record("e1-q3", rule=RULE_PREMISE, human=False),  # 사람이 규칙을 뒤집음
            _record("e1-q4"),  # 아직 사람 확인 전
        ], drop_reasons={"quote_not_found": 1}),
        CardEvalResult(card="e2", title="b", error="LLMUnavailable"),
    ]
    summary = summarize(results)
    assert (summary["saved"], summary["premise"], summary["premise_rate"], summary["labels_pending"]) == (4, 2, 0.5, 1)
    assert (summary["cards_written"], summary["premise_per_card"], summary["premise_by_rule"], summary["failures"]) == (1, 2.0, 2, 1)


def test_result_file_round_trip_keeps_human_labels_and_rejects_bad_values() -> None:
    result = CardEvalResult(card="e1", title="a", received=1, questions=[_record("e1-q1", human=True)])
    raw = json.loads(json.dumps(result_to_dict(result)))
    assert result_from_dict(raw).questions[0].human is True
    raw["questions"][0]["human"] = "yes"
    with pytest.raises(ValueError):
        result_from_dict(raw)


def test_rescore_reports_broken_files_and_keeps_them(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert interview_eval._rescore(broken) == 1
    bad = tmp_path / "bad.json"
    card = {"card": "e1", "questions": [{"id": "e1-q1", "question": "q", "kept": True, "human": "yes"}]}
    bad.write_text(json.dumps({"mode": "ai", "cards": [card]}), encoding="utf-8")
    assert interview_eval._rescore(bad) == 1
    assert json.loads(bad.read_text(encoding="utf-8"))["cards"][0]["questions"][0]["human"] == "yes"  # 그대로


def test_one_failed_card_does_not_stop_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "n.md").write_text(NOTE + "\n## 두 번째\n배포가 자주 실패했다.\n\n스크립트를 고쳤다.\n", encoding="utf-8")
    keys = {"n.md": NoteKey(experiences=(
        ExperienceKey(id="e1", sections=("화면 만들기",)), ExperienceKey(id="e2", sections=("두 번째",)),
    ))}
    real = interview_evaluation.evaluate_planted_card

    async def first_breaks(db: Session, *, experience: str, **kwargs: object) -> CardEvalResult:
        if experience == "e1":
            raise RuntimeError("카드 하나 고장")
        return await real(db, experience=experience, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(interview_eval, "evaluate_planted_card", first_breaks)
    saved: list[int] = []
    results = asyncio.run(interview_eval._evaluate_all(
        keys, tmp_path, mode=interview_eval.MODE_PLANTED, limit=None, client=None, policy=RetryPolicy(),
        on_result=lambda done: saved.append(len(done)),
    ))
    assert [(result.card, result.error) for result in results] == [("e1", "RuntimeError"), ("e2", None)]
    assert saved == [1, 2]  # 카드마다 결과 파일을 다시 쓴다


# --- 4차 리뷰 R3: 다시 채점 · 실행 종료 코드 · 심은 질문 세트 오류 ---


def test_rescore_applies_human_labels_and_rejects_wrong_shapes(tmp_path: Path) -> None:
    card = {"card": "e1", "title": "t", "questions": [
        {"id": "e1-q1", "question": "q", "slot": "action", "quote": "인용 글이다.", "kept": True, "rule": None, "human": True},
        {"id": "e1-q2", "question": "q2", "slot": "action", "quote": "인용 글이다.", "kept": True, "rule": None, "human": None},
    ]}
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"mode": "ai", "provider": "nvidia", "cards": [card]}), encoding="utf-8")
    assert interview_eval._rescore(good) == 0
    summary = json.loads(good.read_text(encoding="utf-8"))["summary"]
    assert (summary["premise"], summary["labels_pending"]) == (1, 1)

    for broken in ([1], [{"card": "e1", "questions": ["질문"]}]):  # 손으로 고치다 모양이 틀림 → 트레이스백 대신 1
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"mode": "ai", "cards": broken}), encoding="utf-8")
        assert interview_eval._rescore(bad) == 1


def test_rescore_reports_a_locked_file_instead_of_crashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"mode": "ai", "cards": []}), encoding="utf-8")

    def locked(_path: Path, _payload: object) -> None:
        raise PermissionError("편집기가 잡고 있음")

    monkeypatch.setattr(interview_eval, "write_json_atomic", locked)
    assert interview_eval._rescore(path) == 1


def _options(provider: str | None, *, allow_mock: bool = False) -> interview_eval.EvalOptions:
    return interview_eval.EvalOptions(
        mode=interview_eval.MODE_AI, provider=provider, limit=None, allow_mock=allow_mock, pause=0, retries=0, retry_wait=0
    )


def test_run_stops_before_any_ai_call_on_bad_settings_or_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert asyncio.run(interview_eval._run(_options("nvidia"))) == 1  # 키 없음 → LLMConfigError → 1
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert asyncio.run(interview_eval._run(_options(None))) == 1  # 기본 mock → 수치에 뜻이 없어 멈춤


def _planted_card_with(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: list[dict[str, str]]) -> None:
    user_id, card_id = _setup(db, tmp_path)
    monkeypatch.setattr(interview_evaluation, "planted_questions", lambda _sent: (items, [None] * len(items)))
    asyncio.run(evaluate_planted_card(db, user_id=user_id, card_id=card_id, experience="e1", title="t"))


def test_planted_set_over_the_save_limit_stops(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = [{"slot": "situation", "question": f"질문 {index}인가요?", "quote": "상품 목록이 느렸다."} for index in range(6)]
    with pytest.raises(ValueError, match="상한"):  # 상한에 걸려 버린 질문은 '잡음'과 구별할 수 없다
        _planted_card_with(db_session, tmp_path, monkeypatch, items)


def test_planted_questions_that_cannot_be_paired_stop(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    long_question = "가" * 400  # 저장할 때 잘려서 글로 짝지을 수 없다
    items = [{"slot": "situation", "question": long_question, "quote": "상품 목록이 느렸다."}]
    with pytest.raises(ValueError, match="짝"):
        _planted_card_with(db_session, tmp_path, monkeypatch, items)
