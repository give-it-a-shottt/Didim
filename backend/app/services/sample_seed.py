"""샘플 체험 데이터 넣기 (F-010, D-025 · D-029 · D-005) — 평가 회차의 AI 결과를 샘플 계정에 그대로 넣는다.

방식: 평가 결과 파일에 남은 AI 출력을 원래 AI 답 모양으로 되돌려 MockLLMClient로 '다시 들려준다'. 저장은 실제
서비스의 prepare → request → save를 그대로 지나간다(근거 검사 · 스키마 검사 같은 저장 규칙이 같음, AI 호출 없음).
그래서 샘플 화면이 리포트 수치를 잰 것과 같은 데이터가 된다. 끝나면 결과 파일과 저장 개수를 비교해 어긋나면 알린다.

- 카드: 평가와 같은 build_eval_cards(경험 구간 문단 → 저장 카드 20장). 초안 · 면접 결과의 인용이 이 카드 글에 맞는다.
- 자소서: 초안 평가처럼 정답지 매칭을 깔고 초안을 다시 들려준 뒤, 역량 줄을 지우고 AI 공고 분석(역량 뽑기 · 매칭)을
  다시 들려준다 — 분석 탭은 AI 결과(리포트 매칭 수치), 초안은 초안 평가와 같은 카드 묶음(사용자 선택 2026-11-18).
- 새 데이터는 공개되지 않는 임시 계정(google_sub SAMPLE_SEEDING_SUB)에 채우고, 다 채운 뒤 한 commit에서 옛 샘플을
  지우고(모든 표가 ON DELETE CASCADE) 임시 계정을 샘플로 바꿔 끼우며 하루 AI 상한을 0으로 둔다.
  그래서 시드 도중 · 실패 · 강제 종료에도 반쯤 채운 샘플이 공개되지 않고, 옛 샘플은 바꿔 끼우는 순간까지 그대로다.
  채우는 동안의 임시 계정 상한은 넉넉히(60번 넘게 상한 확인을 지나감). 남은 임시 계정은 다음 시드가 처음에 지운다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from app.config import SAMPLE_GOOGLE_SUB, SAMPLE_SEEDING_SUB
from app.db.models import (
    Application,
    Draft,
    DraftSentence,
    InterviewQuestion,
    PostingRequirement,
    Quiz,
    RequirementMatch,
    User,
)
from app.llm import Message, MockLLMClient
from app.services.card_evaluation import parse_answer_key
from app.services.chunking import split_markdown
from app.services.draft_evaluation import (
    create_eval_application,
    parse_question_key,
    seed_fixed_matches,
)
from app.services.draft_service import prepare_draft, save_draft
from app.services.draft_writing import request_draft
from app.services.interview_service import prepare_interview, save_interview
from app.services.interview_writing import request_interview_questions
from app.services.note_service import create_note_for_user
from app.services.posting_analysis import (
    prepare_extract,
    prepare_match,
    save_extract,
    save_match,
)
from app.services.posting_evaluation import build_eval_cards, parse_posting_key
from app.services.posting_extraction import request_requirements
from app.services.posting_matching import request_matches
from app.services.quiz_generation import (
    prepare_generation,
    request_quiz_drafts,
    save_generation,
)

SAMPLE_EMAIL = "sample@didim.local"
SAMPLE_NAME = "샘플 지원자"
SAMPLE_DAILY_LIMIT = 10_000  # 임시 계정에 채우는 동안만 — 60번 넘게 상한 확인을 지나간다
SAMPLE_DAILY_LIMIT_AFTER = 0  # 시드가 끝나면 0 — 읽기 전용 가드에 빈틈이 생겨도 공개 계정으로 AI를 못 부르게

# 요약 파일의 평가 칸 → 시드가 읽는 결과 파일
SOURCE_KEYS = {"quiz": "quiz", "postings": "postings", "drafts": "drafts_ai", "interview": "interview_ai"}


class SeedError(Exception):
    """시드를 할 수 없음(요약 · 결과 파일이 없거나 모양이 다름)."""


@dataclass(frozen=True)
class SeedSources:
    quiz: Path
    postings: Path
    drafts: Path
    interview: Path


@dataclass
class SeedReport:
    user_id: int = 0
    notes: int = 0
    cards: int = 0
    # 종류 → (결과 파일 개수, 저장된 개수)
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)

    def add(self, kind: str, expected: int, saved: int) -> None:
        old_expected, old_saved = self.counts.get(kind, (0, 0))
        self.counts[kind] = (old_expected + expected, old_saved + saved)

    @property
    def mismatches(self) -> list[str]:
        return [f"{kind}: 결과 {e} · 저장 {s}" for kind, (e, s) in self.counts.items() if e != s]


def sources_from_summary(summary: Mapping[str, Any], backend_dir: Path) -> SeedSources:
    """회차 요약에서 시드가 읽을 결과 파일을 고른다. 칸이 없거나 'ok'가 아니면 SeedError."""
    by_key = {entry.get("key"): entry for entry in summary.get("evals") or [] if isinstance(entry, dict)}
    paths: dict[str, Path] = {}
    for name, key in SOURCE_KEYS.items():
        entry = by_key.get(key)
        if not entry or entry.get("status") != "ok" or not isinstance(entry.get("result_file"), str):
            raise SeedError(f"요약에 '{key}' 결과가 없거나 끝나지 않았어요.")
        if entry.get("labels_pending"):
            raise SeedError(f"'{key}'에 사람 판정이 남아 있어요. 판정 뒤 --rescore를 먼저 해 주세요.")
        paths[name] = backend_dir / entry["result_file"]
    return SeedSources(**paths)


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SeedError(f"결과 파일을 읽지 못했어요: {path.name}") from exc
    if not isinstance(data, dict):
        raise SeedError(f"결과 파일 모양이 달라요: {path.name}")
    return data


def _title_of(markdown: str, fallback: str) -> str:
    return next((line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")), fallback)


def _reply(payload: object) -> MockLLMClient:
    return MockLLMClient([json.dumps(payload, ensure_ascii=False)])


def new_staging_user(db: Session) -> int:
    """남은 임시 계정을 지우고(딸린 데이터는 DB 외래키가 함께 지움) 새 임시 계정을 만든다. 새 사용자 번호."""
    db.execute(delete(User).where(User.google_sub == SAMPLE_SEEDING_SUB))
    user = User(google_sub=SAMPLE_SEEDING_SUB, email=SAMPLE_EMAIL, name=SAMPLE_NAME, daily_limit=SAMPLE_DAILY_LIMIT)
    db.add(user)
    db.commit()
    return user.id


def promote_staging_user(db: Session, user_id: int) -> None:
    """한 commit에서: 옛 샘플 지우기 → 임시 계정을 샘플로 → 하루 AI 상한 0. 중간에 실패하면 아무것도 바뀌지 않는다."""
    db.execute(delete(User).where(User.google_sub == SAMPLE_GOOGLE_SUB))
    db.flush()  # 옛 샘플이 먼저 지워져야 google_sub UNIQUE에 걸리지 않는다
    user = db.get(User, user_id)
    if user is None or user.google_sub != SAMPLE_SEEDING_SUB:
        raise SeedError("임시 계정이 없어요.")
    user.google_sub = SAMPLE_GOOGLE_SUB
    user.daily_limit = SAMPLE_DAILY_LIMIT_AFTER
    db.commit()


def _discard_staging(db: Session) -> str | None:
    """실패한 임시 계정을 지운다. 정리도 실패하면 그 이유(원래 실패를 덮지 않게 돌려준다)."""
    try:
        db.rollback()
        db.execute(delete(User).where(User.google_sub == SAMPLE_SEEDING_SUB))
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 정리 실패는 원래 실패와 함께 알린다(임시 계정은 공개 안 되고 다음 시드가 지움)
        return type(exc).__name__
    return None


# --- 퀴즈 ---


def quiz_reply(saved: Sequence[Mapping[str, Any]], chunks: Sequence[Any]) -> dict[str, object]:
    """저장된 문제 → AI 답. 조각 번호는 인용이 들어 있는 조각으로 되찾는다(못 찾으면 0 → 검사가 버려 개수가 어긋남)."""
    items = []
    for quiz in saved:
        quote = str(quiz.get("quote") or "")
        chunk_id = next((chunk.id for chunk in chunks if quote and quote in chunk.content), 0)
        items.append({
            "chunk_id": chunk_id, "kind": quiz["kind"], "question": quiz["question"], "choices": quiz["choices"],
            "answer_index": quiz["answer_index"], "explanation": quiz["explanation"], "quote": quote,
        })
    return {"quizzes": items}


async def _seed_quizzes(db: Session, report: SeedReport, *, user_id: int, notes_dir: Path, result: Mapping[str, Any]) -> None:
    by_title = {item["note_title"]: item for item in result.get("notes") or []}
    for path in sorted(notes_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        note = create_note_for_user(db, user_id=user_id, title=_title_of(content, path.stem), content=content, chunks=split_markdown(content))
        report.notes += 1
        saved = (by_title.get(note.title) or {}).get("quizzes") or []
        if not saved:
            continue
        plan = prepare_generation(db, user_id=user_id, note_id=note.id)
        reply = await request_quiz_drafts(_reply(quiz_reply(saved, plan.chunks)), plan.messages)
        save_generation(db, plan, reply)
        stored = db.scalar(select(func.count()).select_from(Quiz).where(Quiz.user_id == user_id, Quiz.note_id == note.id)) or 0
        report.add("퀴즈", len(saved), stored)


# --- 자소서 · 공고 분석 ---


def draft_reply(sentences: Sequence[Mapping[str, Any]], experience_card: Mapping[str, int]) -> dict[str, object]:
    """저장된 문장 → AI 답. 근거 없던 문장은 근거 없이(card_id null) 다시 넣는다."""
    items = []
    for sentence in sentences:
        card = sentence.get("card")
        supported = bool(sentence.get("supported")) and isinstance(card, str) and card in experience_card
        items.append({
            "text": sentence["text"],
            "card_id": experience_card[card] if supported and isinstance(card, str) else None,
            "slot": sentence.get("slot") if supported else None,
            "quote": sentence.get("quote") if supported else None,
        })
    return {"sentences": items}


def match_reply(saved: Sequence[Mapping[str, Any]], messages: Sequence[Message], experience_card: Mapping[str, int]) -> dict[str, object]:
    """저장된 매칭 줄 → AI 답. 역량 번호는 새로 저장된 번호라 보낸 내용에서 이름 · 인용으로 되찾는다."""
    payload = json.loads(messages[-1].content)
    # 보낸 역량은 posting_matching이 posting_quote로 싣는다(이름만으로는 겹칠 수 있어 인용까지 본다)
    ids = {(item.get("name"), item.get("posting_quote")): item.get("requirement_id") for item in payload.get("requirements", [])}
    items = []
    for requirement in saved:
        requirement_id = ids.get((requirement.get("name"), requirement.get("quote")))
        for match in requirement.get("matches") or []:
            card = match.get("card")
            if requirement_id is None or card not in experience_card:
                continue
            items.append({
                "requirement_id": requirement_id, "card_id": experience_card[card], "slot": match["slot"],
                "quote": match["quote"], "reason": match["reason"],
            })
    return {"matches": items}


def _reset_analysis(db: Session, *, user_id: int, application_id: int) -> None:
    """초안을 쓰려고 깔았던 정답지 역량 · 매칭을 지우고 '분석 전'으로 돌린다(초안 문장은 카드를 가리켜 그대로 남는다)."""
    db.execute(delete(PostingRequirement).where(PostingRequirement.user_id == user_id, PostingRequirement.application_id == application_id))
    application = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user_id))
    if application is None:
        raise SeedError("공고가 없어요.")
    application.extracted_at = application.matched_at = None
    db.commit()


def _count(db: Session, statement: Select[tuple[int]]) -> int:
    """select(func.count()) 결과(없으면 0) — 저장 개수를 결과 파일과 맞춰 보려고."""
    return int(db.scalar(statement) or 0)


async def _seed_applications(
    db: Session, report: SeedReport, *, user_id: int, eval_dir: Path, experience_card: Mapping[str, int],
    drafts: Mapping[str, Any], postings: Mapping[str, Any],
) -> None:
    """공고마다 ① 자소서 초안을 깔고 ② 분석 탭(역량 · 매칭)을 AI가 뽑았던 대로 다시 채운다."""
    posting_keys = parse_posting_key(json.loads((eval_dir / "postings" / "answers.json").read_text(encoding="utf-8")))
    question_keys = parse_question_key(json.loads((eval_dir / "drafts" / "questions.json").read_text(encoding="utf-8")), posting_keys)
    draft_items = {(item["file"], item["index"]): item for item in drafts.get("questions") or []}
    posting_items = {item["file"]: item for item in postings.get("postings") or []}

    for file_name, key in posting_keys.items():
        posting_text = (eval_dir / "postings" / "postings" / file_name).read_text(encoding="utf-8").strip()
        application_id, question_ids = create_eval_application(
            db, user_id=user_id, file_name=file_name, posting_text=posting_text, questions=question_keys.get(file_name, ())
        )
        # ① 초안: 초안 평가처럼 정답지 매칭을 깔고 다시 들려준다
        seed_fixed_matches(
            db, user_id=user_id, application_id=application_id, posting_text=posting_text, key=key, experience_card=experience_card
        )
        sentences_by_question = {
            question_id: (draft_items.get((file_name, index)) or {}).get("sentences") or []
            for index, question_id in enumerate(question_ids, start=1)
        }
        await _seed_drafts(db, report, user_id=user_id, application_id=application_id, sentences_by_question=sentences_by_question,
                           experience_card=experience_card)
        # ② 분석 탭: 역량 줄을 지우고 AI가 뽑은 역량 · 매칭을 다시 들려준다
        saved = (posting_items.get(file_name) or {}).get("saved")
        if saved is None:
            raise SeedError(f"{file_name}: 매칭 결과에 저장 줄(saved)이 없어요. 매칭 평가를 다시 돌려 주세요.")
        _reset_analysis(db, user_id=user_id, application_id=application_id)
        await _seed_analysis(db, report, user_id=user_id, application_id=application_id, saved=saved, experience_card=experience_card)


async def _seed_drafts(
    db: Session, report: SeedReport, *, user_id: int, application_id: int,
    sentences_by_question: Mapping[int, Sequence[Mapping[str, Any]]], experience_card: Mapping[str, int],
) -> None:
    """문항마다 평가 때 AI가 쓴 초안 문장을 다시 들려줘 저장한다(문장이 없는 문항은 건너뜀)."""
    for question_id, sentences in sentences_by_question.items():
        if not sentences:
            continue
        plan = prepare_draft(db, user_id=user_id, application_id=application_id, question_id=question_id, overwrite=True)
        save_draft(db, plan, await request_draft(_reply(draft_reply(sentences, experience_card)), plan.messages))
        rows = db.scalars(
            select(DraftSentence).join(Draft, Draft.id == DraftSentence.draft_id)
            .where(Draft.user_id == user_id, Draft.question_id == question_id)
        ).all()
        report.add("자소서 문장", len(sentences), len(rows))
        report.add("근거 붙은 문장", sum(1 for s in sentences if s.get("supported")), sum(1 for r in rows if r.card_id is not None))


async def _seed_analysis(
    db: Session, report: SeedReport, *, user_id: int, application_id: int,
    saved: Sequence[Mapping[str, Any]], experience_card: Mapping[str, int],
) -> None:
    """평가 때 AI가 뽑은 요구 역량과 매칭을 다시 들려줘 분석 탭을 채운다(뽑은 역량이 없으면 '분석 전' 그대로)."""
    if not saved:
        return
    extract_plan = prepare_extract(db, user_id=user_id, application_id=application_id)
    requirements = [{"name": r["name"], "kind": r["kind"], "quote": r["quote"]} for r in saved]
    save_extract(db, extract_plan, await request_requirements(_reply({"requirements": requirements}), extract_plan.messages))
    report.add("요구 역량", len(saved), _count(
        db, select(func.count()).select_from(PostingRequirement).where(PostingRequirement.application_id == application_id)
    ))
    match_plan = prepare_match(db, user_id=user_id, application_id=application_id)
    reply_payload = match_reply(saved, match_plan.messages, experience_card) if match_plan.needs_ai else None
    match_answer = await request_matches(_reply(reply_payload), match_plan.messages) if reply_payload is not None else None
    save_match(db, match_plan, match_answer)
    report.add("매칭", sum(len(r.get("matches") or []) for r in saved), _count(
        db, select(func.count()).select_from(RequirementMatch).join(PostingRequirement, PostingRequirement.id == RequirementMatch.requirement_id)
        .where(PostingRequirement.application_id == application_id)
    ))


# --- 면접 질문 ---


async def _seed_interview(
    db: Session, report: SeedReport, *, user_id: int, experience_card: Mapping[str, int], result: Mapping[str, Any]
) -> None:
    for item in result.get("cards") or []:
        card_id = experience_card.get(item.get("card"))
        kept = [q for q in item.get("questions") or [] if q.get("kept")]
        if card_id is None or not kept:
            continue
        plan = prepare_interview(db, user_id=user_id, card_id=card_id)
        payload = {"questions": [{"slot": q["slot"], "question": q["question"], "quote": q["quote"]} for q in kept]}
        save_interview(db, plan, await request_interview_questions(_reply(payload), plan.messages))
        report.add("면접 질문", len(kept), _count(
            db, select(func.count()).select_from(InterviewQuestion).where(InterviewQuestion.user_id == user_id, InterviewQuestion.card_id == card_id)
        ))


async def seed_sample(db: Session, *, eval_dir: Path, sources: SeedSources) -> SeedReport:
    """임시 계정에 평가 회차 결과를 다시 들려줘 채운 뒤 한 번에 샘플과 바꿔 끼운다. 실패 · 중단하면 지금 샘플은 그대로다
    (사용자 선택 2026-11-18 — D-029 덧붙임). 저장 개수가 결과와 다르면 report.mismatches에 남는다."""
    quiz, postings, drafts, interview = (_load(p) for p in (sources.quiz, sources.postings, sources.drafts, sources.interview))
    report = SeedReport()
    report.user_id = user_id = new_staging_user(db)
    try:
        await _fill(db, report, user_id=user_id, eval_dir=eval_dir, quiz=quiz, postings=postings, drafts=drafts, interview=interview)
        promote_staging_user(db, user_id)
    except Exception as exc:
        cleanup_error = _discard_staging(db)
        note = f" 임시 계정 정리도 실패했어요({cleanup_error}) — 다음 시드가 지워요." if cleanup_error else ""
        # 시드가 직접 낸 SeedError는 할 일 안내('매칭 평가를 다시 돌려 주세요' 등)를 그대로 보여 준다
        reason = str(exc) if isinstance(exc, SeedError) else f"샘플을 넣다가 멈췄어요({type(exc).__name__})."
        raise SeedError(f"{reason} 지금 샘플은 그대로예요.{note}") from exc
    except BaseException:
        _discard_staging(db)  # 중단 · 취소는 그대로 올린다
        raise
    return report


async def _fill(
    db: Session, report: SeedReport, *, user_id: int, eval_dir: Path,
    quiz: Mapping[str, Any], postings: Mapping[str, Any], drafts: Mapping[str, Any], interview: Mapping[str, Any],
) -> None:
    card_keys = parse_answer_key(json.loads((eval_dir / "cards" / "answers.json").read_text(encoding="utf-8")))
    card_experience = build_eval_cards(db, user_id=user_id, notes_dir=eval_dir / "cards" / "notes", card_keys=card_keys)
    experience_card = {experience: card_id for card_id, experience in card_experience.items()}
    report.cards = len(experience_card)
    report.notes = len(card_keys)

    await _seed_quizzes(db, report, user_id=user_id, notes_dir=eval_dir / "quiz" / "notes", result=quiz)
    await _seed_applications(
        db, report, user_id=user_id, eval_dir=eval_dir, experience_card=experience_card, drafts=drafts, postings=postings
    )
    await _seed_interview(db, report, user_id=user_id, experience_card=experience_card, result=interview)
