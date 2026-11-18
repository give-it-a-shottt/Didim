"""샘플 체험 시드 테스트 (F-010) — 평가 회차 결과를 다시 들려줘 넣으면 결과 파일과 저장 개수가 같은지."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import SAMPLE_GOOGLE_SUB
from app.db.models import Application, Card, Note, PostingRequirement, User
from app.llm import Message
from app.services.chunking import split_markdown
from app.services.eval_report import EVAL_SUMMARY_DIR, list_summaries
from app.services.note_service import create_note_for_user
from app.services.sample_seed import (
    SeedError,
    draft_reply,
    match_reply,
    quiz_reply,
    reset_sample_user,
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


def test_reset_replaces_the_sample_user_and_its_data(db_session: Session) -> None:
    first = reset_sample_user(db_session)
    content = "# t\n\n본문"
    create_note_for_user(db_session, user_id=first, title="t", content=content, chunks=split_markdown(content))
    reset_sample_user(db_session)  # SQLite는 지운 마지막 번호를 다시 쓸 수 있어 번호 비교는 하지 않는다
    assert db_session.scalar(select(func.count()).select_from(User).where(User.google_sub == SAMPLE_GOOGLE_SUB)) == 1
    assert db_session.scalar(select(func.count()).select_from(Note)) == 0  # 딸린 데이터도 함께 지워짐


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
