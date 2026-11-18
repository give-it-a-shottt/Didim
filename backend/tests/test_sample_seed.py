"""샘플 체험 시드 테스트 (F-010) — 평가 회차 결과를 다시 들려줘 넣으면 결과 파일과 저장 개수가 같은지."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import SAMPLE_GOOGLE_SUB
from app.db.models import Application, Card, Note, PostingRequirement, User
from app.llm import Message
from app.services.chunking import split_markdown
from app.services.eval_report import EVAL_SUMMARY_DIR, list_summaries
from app.services.note_service import create_note_for_user
from app.services.sample_seed import (
    SAMPLE_SEEDING_SUB,
    SeedError,
    SeedReport,
    SeedSources,
    draft_reply,
    match_reply,
    new_staging_user,
    promote_staging_user,
    quiz_reply,
    seed_sample,
    sources_from_summary,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BACKEND_DIR / "eval"


def test_quiz_reply_finds_the_chunk_by_quote() -> None:
    chunks = [SimpleNamespace(id=7, content="앞 글. 근거 문장이다. 뒤 글."), SimpleNamespace(id=8, content="다른 글")]
    saved = [{"kind": "ox", "question": "q", "choices": ["O", "X"], "answer_index": 0, "explanation": "e", "quote": "근거 문장이다."}]
    assert quiz_reply(saved, chunks)["quizzes"][0]["chunk_id"] == 7  # type: ignore[index]


def test_draft_reply_keeps_unsupported_sentences_without_evidence() -> None:
    sentences = [
        {"text": "근거 있음", "supported": True, "card": "c01-1", "slot": "action", "quote": "인용"},
        {"text": "맺음말", "supported": False, "card": None, "slot": None, "quote": None},
        {"text": "모르는 카드", "supported": True, "card": "c99-9", "slot": "action", "quote": "인용"},
    ]
    items = draft_reply(sentences, {"c01-1": 11})["sentences"]
    assert items == [  # type: ignore[comparison-overlap]
        {"text": "근거 있음", "card_id": 11, "slot": "action", "quote": "인용"},
        {"text": "맺음말", "card_id": None, "slot": None, "quote": None},
        {"text": "모르는 카드", "card_id": None, "slot": None, "quote": None},
    ]


def test_match_reply_maps_new_requirement_ids_by_name_and_quote() -> None:
    sent = {"requirements": [{"requirement_id": 5, "name": "React", "posting_quote": "React 경험"}]}
    messages = [Message(role="system", content="s"), Message(role="user", content=json.dumps(sent, ensure_ascii=False))]
    saved = [{"name": "React", "quote": "React 경험", "matches": [{"card": "c02-1", "slot": "action", "quote": "q", "reason": "r"}]},
             {"name": "없는 역량", "quote": "x", "matches": [{"card": "c02-1", "slot": "action", "quote": "q", "reason": "r"}]}]
    assert match_reply(saved, messages, {"c02-1": 3}) == {
        "matches": [{"requirement_id": 5, "card_id": 3, "slot": "action", "quote": "q", "reason": "r"}]
    }


def test_sources_need_finished_and_judged_runs() -> None:
    ok = {"status": "ok", "result_file": "x.json", "labels_pending": 0}
    summary = {"evals": [{"key": k, **ok} for k in ("quiz", "postings", "drafts_ai", "interview_ai")]}
    assert sources_from_summary(summary, BACKEND_DIR).drafts == BACKEND_DIR / "x.json"
    pending = {"evals": [*summary["evals"][:3], {"key": "interview_ai", **ok, "labels_pending": 2}]}
    with pytest.raises(SeedError, match="사람 판정"):
        sources_from_summary(pending, BACKEND_DIR)
    with pytest.raises(SeedError, match="postings"):
        sources_from_summary({"evals": [e for e in summary["evals"] if e["key"] != "postings"]}, BACKEND_DIR)


def _old_sample_with_note(db: Session) -> int:
    """이미 공개 중인 옛 샘플(노트 1개)을 흉내 낸다."""
    user = User(google_sub=SAMPLE_GOOGLE_SUB, email="old@didim.local", name="옛 샘플", daily_limit=0)
    db.add(user)
    db.commit()
    content = "# 옛 노트\n\n본문"
    create_note_for_user(db, user_id=user.id, title="옛 노트", content=content, chunks=split_markdown(content))
    return user.id


def test_promote_swaps_in_the_new_sample_in_one_step(db_session: Session) -> None:
    """임시 계정을 다 채운 뒤 한 번에: 옛 샘플(과 딸린 데이터) 지움 · 임시 계정이 샘플 · 상한 0(2차 R2)."""
    _old_sample_with_note(db_session)
    staging = new_staging_user(db_session)
    assert db_session.get(User, staging).google_sub == SAMPLE_SEEDING_SUB  # type: ignore[union-attr]
    promote_staging_user(db_session, staging)
    samples = db_session.scalars(select(User).where(User.google_sub == SAMPLE_GOOGLE_SUB)).all()
    assert [u.id for u in samples] == [staging] and samples[0].daily_limit == 0
    assert db_session.scalar(select(func.count()).select_from(Note)) == 0  # 옛 샘플의 노트도 함께 지워짐
    assert db_session.scalar(select(func.count()).select_from(User).where(User.google_sub == SAMPLE_SEEDING_SUB)) == 0


def test_new_staging_user_clears_leftovers(db_session: Session) -> None:
    """강제 종료로 남은 임시 계정은 다음 시드가 처음에 지운다."""
    first = new_staging_user(db_session)
    content = "# t\n\n본문"
    create_note_for_user(db_session, user_id=first, title="t", content=content, chunks=split_markdown(content))
    new_staging_user(db_session)
    assert db_session.scalar(select(func.count()).select_from(User).where(User.google_sub == SAMPLE_SEEDING_SUB)) == 1
    assert db_session.scalar(select(func.count()).select_from(Note)) == 0


def test_seed_from_the_repo_run_matches_the_result_files(db_session: Session) -> None:
    """레포의 최근 회차 결과로 실제 서비스 흐름을 지나 넣는다 — 저장 개수가 결과 파일과 모두 같아야 한다."""
    runs = list_summaries(EVAL_SUMMARY_DIR)
    if not runs:
        pytest.skip("레포에 평가 회차 요약이 없어요.")
    sources = sources_from_summary(runs[0], BACKEND_DIR)
    report = asyncio.run(seed_sample(db_session, eval_dir=EVAL_DIR, sources=sources))

    assert report.mismatches == []
    assert set(report.counts) >= {"퀴즈", "자소서 문장", "근거 붙은 문장", "요구 역량", "매칭", "면접 질문"}
    user_id = report.user_id
    assert db_session.scalar(select(func.count()).select_from(Card).where(Card.user_id == user_id)) == 20
    assert db_session.scalar(select(func.count()).select_from(Note).where(Note.user_id == user_id)) == 24
    assert db_session.scalar(select(func.count()).select_from(Application).where(Application.user_id == user_id)) == 10
    # 분석 탭은 AI 결과로 바뀌어 있다(정답지 줄이 남아 있지 않음 — 정답지 역량 이름은 공고 줄 그대로라 AI 이름과 다르다)
    names = db_session.scalars(select(PostingRequirement.name).where(PostingRequirement.user_id == user_id)).all()
    assert names and not all(len(name) > 25 for name in names)


# --- F-010 1차 리뷰 반영 ---


def test_seed_leaves_the_sample_with_no_ai_budget(db_session: Session) -> None:
    """시드가 끝나면 공개 샘플 계정의 하루 AI 상한은 0(R2 — 가드에 빈틈이 생겨도 AI를 못 부르게)."""
    runs = list_summaries(EVAL_SUMMARY_DIR)
    if not runs:
        pytest.skip("레포에 평가 회차 요약이 없어요.")
    report = asyncio.run(seed_sample(db_session, eval_dir=EVAL_DIR, sources=sources_from_summary(runs[0], BACKEND_DIR)))
    user = db_session.get(User, report.user_id)
    assert user is not None and user.daily_limit == 0


def _broken_sources(tmp_path: Path) -> SeedSources:
    runs = list_summaries(EVAL_SUMMARY_DIR)
    if not runs:
        pytest.skip("레포에 평가 회차 요약이 없어요.")
    sources = sources_from_summary(runs[0], BACKEND_DIR)
    broken = tmp_path / "interview.json"
    broken.write_text(json.dumps({"cards": [{"card": "c01-1", "questions": [{"kept": True}]}]}), encoding="utf-8")  # 필수 키 없음
    return SeedSources(sources.quiz, sources.postings, sources.drafts, broken)


def _assert_old_sample_kept(db: Session, old_id: int) -> None:
    samples = db.scalars(select(User.id).where(User.google_sub == SAMPLE_GOOGLE_SUB)).all()
    assert list(samples) == [old_id]  # 옛 샘플은 그대로 공개 중
    assert db.scalar(select(func.count()).select_from(User).where(User.google_sub == SAMPLE_SEEDING_SUB)) == 0
    # 반쯤 채운 임시 계정의 노트 · 카드도 함께 지워짐(옛 샘플의 노트 1개만 남음)
    assert db.scalar(select(func.count()).select_from(Note)) == 1
    assert db.scalar(select(func.count()).select_from(Card)) == 0


def test_failed_seed_keeps_the_old_sample_and_drops_the_half_filled_one(db_session: Session, tmp_path: Path) -> None:
    """중간에 실패해도 공개 중인 샘플은 그대로, 반쯤 채운 임시 계정과 딸린 데이터는 지운다(2차 R2 · R3)."""
    old_id = _old_sample_with_note(db_session)
    with pytest.raises(SeedError, match="지금 샘플은 그대로예요"):
        asyncio.run(seed_sample(db_session, eval_dir=EVAL_DIR, sources=_broken_sources(tmp_path)))
    _assert_old_sample_kept(db_session, old_id)


@pytest.mark.parametrize("signal", [KeyboardInterrupt, asyncio.CancelledError])
def test_interrupted_seed_cleans_up_and_reraises(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signal: type[BaseException]) -> None:
    """중단 · 취소는 일반 실패로 바꾸지 않고 그대로 올린다 — 정리는 한다(2차 R3)."""
    from app.services import sample_seed

    old_id = _old_sample_with_note(db_session)

    async def stop(db: Session, _report: object, *, user_id: int, **_kwargs: object) -> None:
        # 반쯤 채운 상태를 만든 뒤 멈춘다 — 정리가 데이터까지 지우는지 보려고(3차 R3)
        content = "# 반쯤\n\n본문"
        create_note_for_user(db, user_id=user_id, title="반쯤", content=content, chunks=split_markdown(content))
        raise signal

    monkeypatch.setattr(sample_seed, "_fill", stop)
    with pytest.raises(signal):
        asyncio.run(seed_sample(db_session, eval_dir=EVAL_DIR, sources=_broken_sources(tmp_path)))
    _assert_old_sample_kept(db_session, old_id)


# --- F-010 3차 리뷰 반영 ---


def test_inner_seed_error_keeps_its_advice(db_session: Session, tmp_path: Path) -> None:
    """시드가 직접 낸 SeedError의 할 일 안내가 일반 문구에 묻히지 않는다(3차 R3 · R1)."""
    sources = _broken_sources(tmp_path)
    postings = json.loads(sources.postings.read_text(encoding="utf-8"))
    for item in postings["postings"]:
        item.pop("saved", None)
    no_saved = tmp_path / "postings.json"
    no_saved.write_text(json.dumps(postings, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SeedError) as caught:
        asyncio.run(seed_sample(db_session, eval_dir=EVAL_DIR, sources=SeedSources(sources.quiz, no_saved, sources.drafts, sources.interview)))
    assert "매칭 평가를 다시 돌려 주세요" in str(caught.value) and "지금 샘플은 그대로예요" in str(caught.value)


def test_failed_promote_rolls_back_the_old_sample_delete(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """바꿔 끼우기가 옛 샘플을 지운 뒤 실패해도 되돌려져 옛 샘플이 남는다(3차 R3)."""
    from app.services import sample_seed

    old_id = _old_sample_with_note(db_session)

    async def fill_nothing(*_args: object, **_kwargs: object) -> None:
        return None

    def promote_then_fail(db: Session, user_id: int) -> None:
        db.execute(delete(User).where(User.google_sub == SAMPLE_GOOGLE_SUB))
        db.flush()  # 옛 샘플 삭제까지 간 뒤
        raise RuntimeError("commit 전에 끊김")

    monkeypatch.setattr(sample_seed, "_fill", fill_nothing)
    monkeypatch.setattr(sample_seed, "promote_staging_user", promote_then_fail)
    with pytest.raises(SeedError, match="지금 샘플은 그대로예요"):
        asyncio.run(seed_sample(db_session, eval_dir=EVAL_DIR, sources=_broken_sources(tmp_path)))
    _assert_old_sample_kept(db_session, old_id)


def test_promote_without_staging_account_changes_nothing(db_session: Session) -> None:
    old_id = _old_sample_with_note(db_session)
    with pytest.raises(SeedError, match="임시 계정이 없어요"):
        promote_staging_user(db_session, 999_999)
    db_session.rollback()
    _assert_old_sample_kept(db_session, old_id)


def test_cleanup_failure_is_reported_without_hiding_the_cause(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """정리도 실패하면 원래 이유와 함께 알리고, 중단 신호는 그대로 올린다(3차 R3)."""
    from app.services import sample_seed

    monkeypatch.setattr(sample_seed, "_discard_staging", lambda db: "OperationalError")

    async def boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("깨진 결과")

    monkeypatch.setattr(sample_seed, "_fill", boom)
    with pytest.raises(SeedError) as caught:
        asyncio.run(seed_sample(db_session, eval_dir=EVAL_DIR, sources=_broken_sources(tmp_path)))
    message = str(caught.value)
    assert "ValueError" in message and "임시 계정 정리도 실패했어요(OperationalError)" in message

    async def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(sample_seed, "_fill", interrupt)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(seed_sample(db_session, eval_dir=EVAL_DIR, sources=_broken_sources(tmp_path)))


def test_discard_staging_reports_its_own_failure(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.sample_seed import _discard_staging

    def broken_commit() -> None:
        raise RuntimeError("연결 끊김")

    monkeypatch.setattr(db_session, "commit", broken_commit)
    assert _discard_staging(db_session) == "RuntimeError"


def test_mismatches_report_counts_that_differ() -> None:
    """저장 개수가 결과와 다르면 mismatches에 남는다(R3) — 인용이 어느 조각에도 없으면 조각 번호 0(검사가 버림)."""
    chunks = [SimpleNamespace(id=7, content="다른 글")]
    saved = [{"kind": "ox", "question": "q", "choices": ["O", "X"], "answer_index": 0, "explanation": "e", "quote": "없는 문장"}]
    assert quiz_reply(saved, chunks)["quizzes"][0]["chunk_id"] == 0  # type: ignore[index]
    report = SeedReport()
    report.add("퀴즈", 5, 5)
    report.add("퀴즈", 1, 0)
    report.add("매칭", 2, 2)
    assert report.mismatches == ["퀴즈: 결과 6 · 저장 5"]
