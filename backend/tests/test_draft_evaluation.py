"""자소서 초안 평가(F-008 완료 기준 4) 테스트 — 채점 AI 없이 규칙 + 사람 판정으로 세는지, 실제 서비스 흐름 · 실패 경로."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ApplicationClaim, CardField, RequirementMatch
from app.llm import LLMUnavailable, MockLLMClient
from app.llm.base import Message
from app.services import draft_evaluation
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.card_evaluation import ExperienceKey, NoteKey
from app.services.draft_evaluation import (
    PLANT_ADDED_FACT,
    PLANT_FAKE_QUOTE,
    PLANT_NO_EVIDENCE,
    PLANT_OTHER_CARD,
    PLANT_TYPES,
    RULE_FROM_QUESTION,
    RULE_INVENTED,
    QuestionEvalResult,
    QuestionKey,
    SentenceRecord,
    SentPayload,
    create_eval_application,
    evaluate_planted_question,
    evaluate_question,
    parse_question_key,
    planted_sentences,
    result_from_dict,
    result_to_dict,
    rule_verdict,
    seed_fixed_matches,
    summarize,
    summarize_planted,
)
from app.services.eval_retry import RetryPolicy
from app.services.posting_evaluation import (
    PostingKey,
    RequirementKey,
    build_eval_cards,
    parse_posting_key,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
POSTING = "자격 요건\n- React 화면 개발 경험\n- 쿠버네티스 운영 경험"
KEY = PostingKey(
    requirements=(
        RequirementKey(quote="React 화면 개발 경험", kind="required", cards=("e1",)),
        RequirementKey(quote="쿠버네티스 운영 경험", kind="preferred", cards=()),
    )
)
NOTE = "# 노트\n\n## 화면 만들기\n상품 목록이 느렸다.\n\nReact.memo와 remark-gfm으로 카드를 감쌌다.\n\n렌더링이 40ms로 줄었다.\n"
QUESTION = QuestionKey(kind="trap", text="Kubernetes로 운영한 경험을 써 주세요.", char_limit=300)


def _payload() -> SentPayload:
    content = {
        "company": "스텝랩",
        "role": "백엔드",
        "question": "Kubernetes로 운영한 경험을 써 주세요.",
        "target_chars": 300,
        "requirements": ["React 화면 개발 경험"],
        "cards": [{"card_id": 1, "title": "화면 만들기", "fields": [{"slot": "result", "quote": "렌더링이 40ms로 줄었다."}]}],
    }
    return SentPayload.from_messages([Message("system", "규칙"), Message("user", json.dumps(content, ensure_ascii=False))])


def test_rule_flags_only_tokens_missing_from_everything_sent() -> None:
    payload = _payload()
    assert rule_verdict("렌더링을 40ms로 줄였습니다.", payload) == (None, [])
    assert rule_verdict("렌더링을 30% 줄여 4ms가 되었습니다.", payload) == (RULE_INVENTED, ["30", "4"])  # '4'는 '40' 안에 있어도 다른 숫자
    assert rule_verdict("Kubernetes 운영 경험은 없지만 배우겠습니다.", payload) == (RULE_FROM_QUESTION, ["kubernetes"])
    assert rule_verdict("REACT 렌더링을 줄였습니다.", payload) == (RULE_FROM_QUESTION, ["react"])  # 대소문자 무시, 역량 이름에만 있음
    assert rule_verdict("1,000명이 썼습니다.", payload) == (RULE_INVENTED, ["1000"])


def test_truncated_word_inside_card_text_is_not_flagged() -> None:
    content = {"cards": [{"card_id": 1, "title": "t", "fields": [{"slot": "action", "quote": "remark-gfm을 붙였다."}]}]}
    payload = SentPayload.from_messages([Message("user", json.dumps(content, ensure_ascii=False))])
    assert rule_verdict("remark-gf로 표를 고쳤습니다.", payload) == (None, [])


def test_question_key_typos_stop_before_any_ai_call() -> None:
    keys = {"a.md": KEY}
    good = {"kind": "trap", "text": "문항", "char_limit": 500}
    assert parse_question_key({"questions": {"a.md": [good]}}, keys)["a.md"][0].char_limit == 500
    for bad in (
        {"questions": {"b.md": [good]}},  # 공고 이름이 다름
        {"questions": {"a.md": []}},
        {"questions": {"a.md": [{**good, "kind": "보통"}]}},
        {"questions": {"a.md": [{**good, "text": " "}]}},
        {"questions": {"a.md": [{**good, "char_limit": True}]}},
        {"questions": {"a.md": [{**good, "char_limit": 0}]}},
    ):
        with pytest.raises(ValueError):
            parse_question_key(bad, keys)


def test_repo_question_file_matches_the_posting_set() -> None:
    """레포의 문항 파일이 공고 정답지와 맞고, 공고마다 보통 1 · 함정 1이다."""
    raw = json.loads((BACKEND_DIR / "eval/drafts/questions.json").read_text(encoding="utf-8"))
    posting_keys = parse_posting_key(json.loads((BACKEND_DIR / raw["postings_from"]).read_text(encoding="utf-8")))
    keys = parse_question_key(raw, posting_keys)
    assert all(sorted(item.kind for item in items) == ["answerable", "trap"] for items in keys.values())


def _record(sid: str, *, supported: bool, rule: str | None = None, human: bool | None = None) -> SentenceRecord:
    return SentenceRecord(id=sid, text=sid, supported=supported, rule=rule, human=human)


def test_summary_counts_caught_missed_and_pending_labels() -> None:
    result = QuestionEvalResult(
        file_name="p01.md", index=1, kind="trap", question="q", char_limit=10, chars=12,
        sentences=[
            _record("s1", supported=False, rule=RULE_INVENTED),  # 규칙 지어냄 · 근거 없음 → 잡음
            _record("s2", supported=True, rule=RULE_INVENTED, human=False),  # 사람이 '아님'으로 뒤집음
            _record("s3", supported=True, human=True),  # 검사를 통과한 지어낸 문장 → 놓침
            _record("s4", supported=False),  # 사람 확인 전 · 근거 없음
            _record("s5", supported=True, rule=RULE_FROM_QUESTION),  # 사람 확인 전
        ],
    )
    failed = QuestionEvalResult(file_name="p02.md", index=1, kind="answerable", question="q", char_limit=None, error="LLMUnavailable")
    summary = summarize([result, failed])
    assert (summary["fabricated"], summary["fabricated_caught"], summary["catch_rate"]) == (2, 1, 0.5)
    assert (summary["fabricated_missed"], summary["unsupported_sentences"], summary["labels_pending"]) == (1, 2, 2)
    assert summary["unsupported_per_draft"] == 2.0  # 실패한 문항은 초안 수에 넣지 않음
    assert summary["rule_only"] == {"fabricated": 2, "caught": 1, "catch_rate": 0.5, "from_question": 1}
    assert (summary["over_limit"], summary["failures"]) == (1, 1)
    assert summary["by_kind"]["trap"]["caught"] == 1


def test_result_file_round_trip_keeps_human_labels_and_rejects_bad_values() -> None:
    result = QuestionEvalResult(
        file_name="p01.md", index=2, kind="trap", question="q", char_limit=None,
        sentences=[_record("s1", supported=True, human=True)],
    )
    raw = json.loads(json.dumps(result_to_dict(result), ensure_ascii=False))
    assert summarize([result_from_dict(raw)]) == summarize([result])
    raw["sentences"][0]["human"] = "yes"
    with pytest.raises(ValueError):
        result_from_dict(raw)


# --- 실제 서비스 흐름 ---


def _setup(db: Session, tmp_path: Path) -> tuple[int, int, int, int, dict[int, str]]:
    user = get_or_create_google_user(db, GoogleProfile(sub="draft-eval-test", email="d@example.com", name="d"))
    user.daily_limit = 1000
    db.commit()
    (tmp_path / "n.md").write_text(NOTE, encoding="utf-8")
    mapping = build_eval_cards(
        db, user_id=user.id, notes_dir=tmp_path,
        card_keys={"n.md": NoteKey(experiences=(ExperienceKey(id="e1", sections=("화면 만들기",)),))},
    )
    application_id, (question_id,) = create_eval_application(
        db, user_id=user.id, file_name="p01.md", posting_text=POSTING, questions=[QUESTION]
    )
    seed_fixed_matches(
        db, user_id=user.id, application_id=application_id, posting_text=POSTING, key=KEY,
        experience_card={experience: card_id for card_id, experience in mapping.items()},
    )
    return user.id, application_id, question_id, next(iter(mapping)), mapping


def _evaluate(db: Session, ids: tuple[int, int, int, int, dict[int, str]], client: MockLLMClient, retries: int = 0) -> tuple[QuestionEvalResult, list[float]]:
    user_id, application_id, question_id, _, mapping = ids
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    result = asyncio.run(evaluate_question(
        db, user_id=user_id, application_id=application_id, question_id=question_id, file_name="p01-backend.md",
        index=1, key=QUESTION, card_experience=mapping, client=client,
        policy=RetryPolicy(retries=retries, wait=5, sleep=fake_sleep),
    ))
    return result, waits


def test_evaluate_question_runs_the_real_flow_and_records_each_sentence(db_session: Session, tmp_path: Path) -> None:
    ids = _setup(db_session, tmp_path)
    card_id = ids[3]
    assert db_session.scalar(select(func.count()).select_from(RequirementMatch)) == 1  # 정답 카드만 매칭(함정 역량은 비움)
    reply = json.dumps({"sentences": [
        {"text": "렌더링을 40ms로 줄였습니다.", "card_id": card_id, "slot": "result", "quote": "렌더링이 40ms로 줄었다."},
        {"text": "Kubernetes 클러스터 3대를 운영했습니다.", "card_id": card_id, "slot": "action", "quote": "쿠버네티스를 운영했다."},
        {"text": "장애를 99% 줄였습니다.", "card_id": None, "slot": None, "quote": None},
    ]}, ensure_ascii=False)
    client = MockLLMClient([LLMUnavailable("down"), reply])
    result, waits = _evaluate(db_session, ids, client, retries=1)

    assert (result.error, result.retries, waits, result.usage.calls) == (None, 1, [5], 2)
    first, second, third = result.sentences
    assert (first.id, first.supported, first.card, first.rule) == ("p01-q1-s1", True, "e1", None)
    assert (second.supported, second.rule, second.rule_tokens) == (False, RULE_INVENTED, ["3"])  # 인용을 지어냄 → 근거 없음
    assert (third.supported, third.rule, third.rule_tokens) == (False, RULE_INVENTED, ["99"])
    assert result.drop_reasons == {"quote_not_found": 1, "no_evidence": 1}
    assert result.chars == len(" ".join(item.text for item in result.sentences)) and result.cards_sent == 1
    sent = json.loads(client.calls[-1][1].content)
    assert sent["requirements"] == ["React 화면 개발 경험"]  # 매칭된 역량 이름만 보낸다
    assert db_session.scalar(select(func.count()).select_from(ApplicationClaim)) == 0


def test_failure_after_retries_counts_as_no_draft_and_releases_the_claim(db_session: Session, tmp_path: Path) -> None:
    ids = _setup(db_session, tmp_path)
    result, waits = _evaluate(db_session, ids, MockLLMClient([LLMUnavailable("down"), LLMUnavailable("down")]), retries=1)
    assert (result.error, result.retries, waits, result.sentences) == ("LLMUnavailable", 1, [5], [])
    assert db_session.scalar(select(func.count()).select_from(ApplicationClaim)) == 0


def test_no_sentences_is_recorded_as_an_error(db_session: Session, tmp_path: Path) -> None:
    ids = _setup(db_session, tmp_path)
    result, _ = _evaluate(db_session, ids, MockLLMClient([json.dumps({"sentences": [{"text": " "}]})]))
    assert (result.error, result.sentences, result.drop_reasons) == ("no_sentences", [], {"empty_sentence": 1})


def test_unexpected_error_releases_the_claim_and_raises(db_session: Session, tmp_path: Path) -> None:
    ids = _setup(db_session, tmp_path)
    with pytest.raises(RuntimeError):
        _evaluate(db_session, ids, MockLLMClient([RuntimeError("boom")]), retries=2)
    assert db_session.scalar(select(func.count()).select_from(ApplicationClaim)) == 0


# --- 심은 문장 평가 (D-005) ---


def _two_card_payload() -> dict:  # type: ignore[type-arg]
    return {
        "cards": [
            {"card_id": 5, "title": "a", "fields": [{"slot": "situation", "quote": "첫째 카드의 상황 글이다.\n둘째 줄"}]},
            {"card_id": 6, "title": "b", "fields": [{"slot": "action", "answer": "둘째 카드의 내 답 글이다."}, {"slot": "task", "quote": "짧"}]},
        ]
    }


def test_planted_sentences_mix_genuine_quotes_and_rotating_fakes() -> None:
    items, labels = planted_sentences(_two_card_payload(), rotation=2)
    assert labels == [None, None, PLANT_OTHER_CARD, PLANT_ADDED_FACT, PLANT_NO_EVIDENCE]  # 진짜 2개뿐이라 남은 건 끝에
    assert items[0] == {"text": "첫째 카드의 상황 글이다.", "card_id": 5, "slot": "situation", "quote": "첫째 카드의 상황 글이다."}
    assert items[1]["quote"] == "둘째 카드의 내 답 글이다."  # 원문 인용이 없으면 내 답, 5글자 미만 칸은 뺌
    assert items[2]["card_id"] == 6 and items[2]["quote"] == "첫째 카드의 상황 글이다."  # 다른 카드 번호에 붙임
    assert items[3]["quote"] == "둘째 카드의 내 답 글이다." and "37%" in str(items[3]["text"])
    assert items[4]["card_id"] is None
    rotations = [planted_sentences(_two_card_payload(), rotation=r)[1] for r in range(4)]
    counts = {kind: sum(labels.count(kind) for labels in rotations) for kind in PLANT_TYPES}
    assert set(counts.values()) == {3}  # 4문항마다 종류별로 같은 수
    with pytest.raises(ValueError):
        planted_sentences({"cards": []}, rotation=0)


def test_evaluate_planted_question_runs_the_real_check_without_ai(db_session: Session, tmp_path: Path) -> None:
    user_id, application_id, question_id, _, mapping = _setup(db_session, tmp_path)
    results = [
        asyncio.run(evaluate_planted_question(
            db_session, user_id=user_id, application_id=application_id, question_id=question_id,
            file_name="p01-backend.md", index=1, key=QUESTION, card_experience=mapping, rotation=rotation,
        ))
        for rotation in (0, 1)
    ]
    # 카드 1장(칸 3개) → 진짜 3 + 심음 3. 카드가 1장뿐이라 other_card는 보내지 않은 번호에 붙는다
    assert [record.planted for record in results[0].sentences] == [None, None, PLANT_NO_EVIDENCE, None, PLANT_FAKE_QUOTE, PLANT_OTHER_CARD]
    summary = summarize_planted(results)
    # 근거 검사는 못 보지만(caught 0) '확인 필요'(D-028 — 카드에 없는 숫자 37)가 잡는다
    assert summary["by_type"][PLANT_ADDED_FACT] == {
        "planted": 1, "caught": 0, "catch_rate": 0.0, "warned": 1, "warn_rate": 1.0,
    }
    assert summary["by_type"][PLANT_FAKE_QUOTE] == {
        "planted": 2, "caught": 2, "catch_rate": 1.0, "warned": 2, "warn_rate": 1.0,
    }
    assert (summary["planted"], summary["planted_caught"], summary["genuine_flagged"]) == (6, 5, 0)
    assert (summary["planted_warned"], summary["genuine_needs_check"]) == (6, 0)  # 진짜 문장은 '확인 필요'도 0
    assert summary["drop_reasons"] == {"no_evidence": 1, "quote_not_found": 2, "card_not_sent": 2}
    assert db_session.scalar(select(func.count()).select_from(ApplicationClaim)) == 0
    raw = json.loads(json.dumps(result_to_dict(results[0]), ensure_ascii=False))
    assert [record.planted for record in result_from_dict(raw).sentences] == [record.planted for record in results[0].sentences]


def test_planted_failure_before_saving_releases_the_claim(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """심을 답을 못 만들면(카드 글 없음 등) 선점을 풀고 올린다 — AI 경로의 abandon과 같은 정리(5차 리뷰 R3)."""
    user_id, application_id, question_id, _, mapping = _setup(db_session, tmp_path)

    def broken(payload, *, rotation):
        raise ValueError("보낸 카드에 인용으로 쓸 글이 없어요.")

    monkeypatch.setattr(draft_evaluation, "planted_sentences", broken)
    with pytest.raises(ValueError):
        asyncio.run(evaluate_planted_question(
            db_session, user_id=user_id, application_id=application_id, question_id=question_id,
            file_name="p01-backend.md", index=1, key=QUESTION, card_experience=mapping, rotation=0,
        ))
    assert db_session.scalar(select(func.count()).select_from(ApplicationClaim)) == 0


def test_planted_labels_must_line_up_with_saved_sentences(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """저장 과정에서 문장이 빠지면(빈 문장) 위치로 정답을 붙일 수 없으니 멈춘다."""
    user_id, application_id, question_id, card_id, mapping = _setup(db_session, tmp_path)
    quote = "렌더링이 40ms로 줄었다."

    def with_blank(payload, *, rotation):
        items = [{"text": quote, "card_id": card_id, "slot": "result", "quote": quote}, {"text": " "}]
        return items, [None, PLANT_NO_EVIDENCE]

    monkeypatch.setattr(draft_evaluation, "planted_sentences", with_blank)
    with pytest.raises(ValueError, match="1문장만"):
        asyncio.run(evaluate_planted_question(
            db_session, user_id=user_id, application_id=application_id, question_id=question_id,
            file_name="p01-backend.md", index=1, key=QUESTION, card_experience=mapping, rotation=0,
        ))
    assert db_session.scalar(select(func.count()).select_from(ApplicationClaim)) == 0


def test_answer_card_without_quote_field_stops_that_posting(db_session: Session, tmp_path: Path) -> None:
    """정답 카드에 원문 인용 칸이 없으면 KeyError 대신 이유를 알리는 ValueError(스크립트가 그 공고만 실패로 남김)."""
    user_id, application_id, _, card_id, mapping = _setup(db_session, tmp_path)
    for row in db_session.scalars(select(CardField).where(CardField.card_id == card_id)):
        row.quote = None
    db_session.commit()
    with pytest.raises(ValueError, match="원문 인용 칸"):
        seed_fixed_matches(
            db_session, user_id=user_id, application_id=application_id, posting_text=POSTING, key=KEY,
            experience_card={experience: cid for cid, experience in mapping.items()},
        )


def test_old_result_file_without_claim_checks_is_scored_without_those_numbers() -> None:
    """D-028 전 결과 파일(needs_check 없음)을 --score로 다시 채점해도 터지지 않고, '확인 필요까지' 수치는 내지 않는다
    — 근거 검사만의 수치와 같게 찍혀 새 규칙을 돌린 것처럼 보이지 않게(7차 리뷰 R3)."""
    raw = {
        "file": "p01-backend.md", "index": 1, "kind": "answerable", "question": "문항", "char_limit": 500,
        "sentences": [
            {"id": "p01-q1-s1", "text": "빌드를 단축했습니다.", "supported": True, "human": True},
            {"id": "p01-q1-s2", "text": "맺음말입니다.", "supported": False, "human": False},
        ],
    }
    old = result_from_dict(raw)
    assert [record.needs_check for record in old.sentences] == [None, None]
    summary = summarize([old])
    assert summary["claims_checked"] is False
    assert (summary["fabricated"], summary["fabricated_caught"]) == (1, 0)
    assert (summary["fabricated_warned"], summary["warn_rate"], summary["needs_check_sentences"]) == (None, None, None)
    assert summary["by_kind"]["answerable"]["warned"] is None


def test_old_planted_file_and_empty_results_do_not_report_claim_numbers() -> None:
    """심은 문장 요약도 옛 결과 파일 · 빈 결과에서는 '확인 필요까지' 수치를 내지 않는다(8차 리뷰 R3 — 빈 목록은 all([])=True였음)."""
    raw = {
        "file": "p01-backend.md", "index": 1, "kind": "answerable", "question": "문항", "char_limit": 500,
        "sentences": [
            {"id": "p01-q1-s1", "text": "진짜 문장.", "supported": True},
            {"id": "p01-q1-s2", "text": "37% 빨라졌습니다.", "supported": True, "planted": "added_fact"},
        ],
    }
    summary = summarize_planted([result_from_dict(raw)])
    assert summary["claims_checked"] is False
    assert (summary["planted_warned"], summary["warn_rate"], summary["genuine_needs_check"]) == (None, None, None)
    assert summary["by_type"]["added_fact"]["warned"] is None
    empty = summarize([])
    assert (empty["claims_checked"], empty["warn_rate"], empty["needs_check_sentences"]) == (False, None, None)
