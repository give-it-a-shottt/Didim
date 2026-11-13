"""공고 분석 평가(F-007 완료 기준 6) 채점 테스트 — 채점 AI 없이 위치 · 카드 번호로 판정하는지, 정답지 오타를 먼저 막는지."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ApplicationClaim, Card, CardField
from app.llm import LLMUnavailable, MockLLMClient
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.card_evaluation import ExperienceKey, NoteKey, parse_answer_key
from app.services.posting_evaluation import (
    ExtractedRequirement,
    PostingKey,
    RequirementKey,
    build_eval_cards,
    check_card_references,
    evaluate_posting,
    key_spans,
    parse_posting_key,
    score_posting,
    summarize,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
POSTING = "자격 요건\n- React 화면 개발 경험\n- 쿠버네티스 운영 경험\n"
KEY = PostingKey(
    requirements=(
        RequirementKey(quote="React 화면 개발 경험", kind="required", cards=("e1",)),
        RequirementKey(quote="쿠버네티스 운영 경험", kind="preferred", cards=()),
    )
)
NOTE = "# 노트\n\n## 화면 만들기\n상품 목록이 느렸다.\n\nReact.memo로 카드를 감쌌다.\n\n렌더링이 40ms로 줄었다.\n\n## 개념\nmemo는 다시 그리기를 막는다.\n"


def _extracted(rid: int, quote: str, kind: str, cards: tuple[int, ...] = ()) -> ExtractedRequirement:
    start = POSTING.index(quote)
    return ExtractedRequirement(id=rid, name=quote[:5], kind=kind, quote_start=start, quote_end=start + len(quote), matched_cards=cards)


def test_score_maps_requirements_by_quote_overlap_and_counts_false_matches() -> None:
    extracted = [
        _extracted(1, "React 화면", "required", (10,)),  # 줄 일부만 인용해도 그 줄로 잇는다
        _extracted(2, "쿠버네티스 운영 경험", "required", (11,)),  # 근거 없어야 할 역량에 매칭 · 필수/우대 틀림
        _extracted(3, "자격 요건", "required"),  # 정답지에 없는 줄
    ]
    score = score_posting(POSTING, KEY, extracted, {1: [10, 11], 2: [11]}, {10: "e1", 11: "e2"})
    react, k8s = score.verdicts
    assert (react.found, react.hit, react.kind_correct, react.candidates, react.wrong) == (True, True, True, ["e1", "e2"], [])
    assert (k8s.found, k8s.kind_correct, k8s.matched, k8s.wrong) == (True, False, ["e2"], ["e2"])
    assert score.extra_requirements == [{"name": "자격 요건", "matched": []}]


def test_summary_rates() -> None:
    from app.services.posting_evaluation import PostingEvalResult

    hit = PostingEvalResult(file_name="a.md", company="a", score=score_posting(POSTING, KEY, [_extracted(1, "React 화면 개발 경험", "required", (10,))], {1: [10]}, {10: "e1"}))
    miss = PostingEvalResult(file_name="b.md", company="b", score=score_posting(POSTING, KEY, [], {}, {}), error="LLMUnavailable")
    summary = summarize([hit, miss])
    assert summary["match_hit_rate"] == 0.5  # 못 뽑은 역량도 놓친 것으로 센다
    assert summary["match_hit_rate_among_found"] == 1.0
    assert (summary["false_matches"], summary["failures"], summary["requirements_found"]) == (0, 1, 1)


def test_answer_key_typos_stop_before_any_ai_call() -> None:
    with pytest.raises(ValueError):
        key_spans(POSTING, PostingKey(requirements=(RequirementKey(quote="없는 줄", kind="required", cards=()),)))
    with pytest.raises(ValueError):
        parse_posting_key({"postings": {"a.md": {"requirements": [{"quote": "x", "kind": "필수", "cards": []}]}}})
    with pytest.raises(ValueError):
        check_card_references({"a.md": KEY}, {"n.md": NoteKey(experiences=(ExperienceKey(id="e9", sections=("s",)),))})


def test_repo_answer_keys_match_the_postings_and_cards() -> None:
    """레포의 정답지 · 공고 · 카드 정답지가 서로 맞는다(평가를 돌리기 전에 깨진 걸 알 수 있게)."""
    raw = json.loads((BACKEND_DIR / "eval/postings/answers.json").read_text(encoding="utf-8"))
    keys = parse_posting_key(raw)
    card_keys = parse_answer_key(json.loads((BACKEND_DIR / raw["cards_from"]).read_text(encoding="utf-8")))
    check_card_references(keys, card_keys)
    paths = sorted((BACKEND_DIR / "eval/postings/postings").glob("*.md"))
    assert {path.name for path in paths} == set(keys)
    for path in paths:
        key_spans(path.read_text(encoding="utf-8").strip(), keys[path.name])


def _user(db: Session) -> int:
    user = get_or_create_google_user(db, GoogleProfile(sub="posting-eval-test", email="p@example.com", name="p"))
    user.daily_limit = 1000
    db.commit()
    return user.id


def test_build_eval_cards_quotes_experience_paragraphs(db_session: Session, tmp_path: Path) -> None:
    (tmp_path / "n.md").write_text(NOTE, encoding="utf-8")
    user_id = _user(db_session)
    mapping = build_eval_cards(
        db_session, user_id=user_id, notes_dir=tmp_path,
        card_keys={"n.md": NoteKey(experiences=(ExperienceKey(id="e1", sections=("화면 만들기",)),))},
    )
    assert list(mapping.values()) == ["e1"]
    fields = {row.slot: row.quote for row in db_session.scalars(select(CardField)).all()}
    assert fields == {"situation": "상품 목록이 느렸다.", "task": None, "action": "React.memo로 카드를 감쌌다.", "result": "렌더링이 40ms로 줄었다."}
    assert db_session.scalar(select(Card.status)) == "saved"


def test_evaluate_posting_runs_the_real_flow_and_retries(db_session: Session, tmp_path: Path) -> None:
    (tmp_path / "n.md").write_text(NOTE, encoding="utf-8")
    user_id = _user(db_session)
    mapping = build_eval_cards(
        db_session, user_id=user_id, notes_dir=tmp_path,
        card_keys={"n.md": NoteKey(experiences=(ExperienceKey(id="e1", sections=("화면 만들기",)),))},
    )
    card_id = next(iter(mapping))
    extract = json.dumps({"requirements": [
        {"name": "React", "kind": "required", "quote": "React 화면 개발 경험"},
        {"name": "쿠버네티스", "kind": "preferred", "quote": "쿠버네티스 운영 경험"},
    ]}, ensure_ascii=False)
    # 매칭: 요구 역량 번호는 저장 뒤에 정해지므로 mock 답을 보낸 내용에서 만든다
    def match_responder(messages):  # noqa: ANN001, ANN202
        payload = json.loads(messages[1].content)
        react = next(item for item in payload["requirements"] if item["name"] == "React")
        return json.dumps({"matches": [{"requirement_id": react["requirement_id"], "card_id": card_id, "slot": "action",
                                        "quote": "React.memo로 카드를 감쌌다.", "reason": "React 경험이에요."}]}, ensure_ascii=False)

    client = MockLLMClient([LLMUnavailable("down"), extract], responder=match_responder)
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    result = asyncio.run(evaluate_posting(
        db_session, user_id=user_id, file_name="p.md", posting_text=POSTING.strip(), key=KEY,
        card_experience=mapping, client=client, retries=1, retry_wait=5, sleep=fake_sleep,
    ))
    assert result.error is None and result.retries == 1 and waits == [5]
    react, k8s = result.score.verdicts
    assert react.hit and react.candidates == ["e1"]
    assert k8s.found and k8s.matched == []
    assert result.usage.calls == 3
    assert db_session.scalar(select(func.count()).select_from(Card)) == 1


# --- 평가의 실패 경로(F-007 3차 R3): 실패한 공고가 점수에 어떻게 들어가는지 · 선점이 풀리는지 고정 ---

EXTRACT_REPLY = json.dumps({"requirements": [
    {"name": "React", "kind": "required", "quote": "React 화면 개발 경험"},
    {"name": "쿠버네티스", "kind": "preferred", "quote": "쿠버네티스 운영 경험"},
]}, ensure_ascii=False)


def _eval_cards(db: Session, user_id: int, tmp_path: Path) -> dict[int, str]:
    (tmp_path / "n.md").write_text(NOTE, encoding="utf-8")
    return build_eval_cards(
        db, user_id=user_id, notes_dir=tmp_path,
        card_keys={"n.md": NoteKey(experiences=(ExperienceKey(id="e1", sections=("화면 만들기",)),))},
    )


def _run(db: Session, user_id: int, mapping: dict[int, str], client: MockLLMClient, retries: int = 0) -> tuple:  # type: ignore[type-arg]
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    result = asyncio.run(evaluate_posting(
        db, user_id=user_id, file_name="p.md", posting_text=POSTING.strip(), key=KEY,
        card_experience=mapping, client=client, retries=retries, retry_wait=5, sleep=fake_sleep,
    ))
    return result, waits


def test_extract_failure_after_retries_counts_as_not_found(db_session: Session, tmp_path: Path) -> None:
    user_id = _user(db_session)
    mapping = _eval_cards(db_session, user_id, tmp_path)
    client = MockLLMClient([LLMUnavailable("down"), LLMUnavailable("down")])
    result, waits = _run(db_session, user_id, mapping, client, retries=1)
    assert (result.error, result.error_step, result.retries, waits) == ("LLMUnavailable", "extract", 1, [5])
    assert [verdict.found for verdict in result.score.verdicts] == [False, False]  # 못 뽑은 역량은 놓친 것으로 셈
    assert result.usage.calls == 2
    assert db_session.scalar(select(func.count()).select_from(ApplicationClaim)) == 0


def test_match_failure_scores_extracted_requirements_without_matches(db_session: Session, tmp_path: Path) -> None:
    user_id = _user(db_session)
    mapping = _eval_cards(db_session, user_id, tmp_path)
    client = MockLLMClient([EXTRACT_REPLY, LLMUnavailable("down")])
    result, waits = _run(db_session, user_id, mapping, client)
    assert (result.error, result.error_step, waits) == ("LLMUnavailable", "match", [])
    react, k8s = result.score.verdicts
    assert react.found and not react.hit and react.matched == [] and react.candidates == ["e1"]
    assert k8s.found and k8s.matched == []
    assert db_session.scalar(select(func.count()).select_from(ApplicationClaim)) == 0


def test_no_candidates_skips_the_match_call(db_session: Session) -> None:
    user_id = _user(db_session)  # 카드 없음 — 키워드 후보가 없어 ②는 AI를 부르지 않는다
    client = MockLLMClient([EXTRACT_REPLY], default_reply=None)
    result, _ = _run(db_session, user_id, {}, client)
    assert result.error is None and len(client.calls) == 1 and result.usage.calls == 1
    assert [verdict.found for verdict in result.score.verdicts] == [True, True]
    assert all(verdict.matched == [] for verdict in result.score.verdicts)


def test_unexpected_error_releases_the_claim_and_raises(db_session: Session, tmp_path: Path) -> None:
    user_id = _user(db_session)
    mapping = _eval_cards(db_session, user_id, tmp_path)
    client = MockLLMClient([RuntimeError("boom")])
    with pytest.raises(RuntimeError):
        _run(db_session, user_id, mapping, client, retries=2)
    assert db_session.scalar(select(func.count()).select_from(ApplicationClaim)) == 0
