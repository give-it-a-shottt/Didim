"""문제 만들기 테스트 (F-004 완료 기준 1 · 2 · 6, D-018).

AI는 MockLLMClient로 바꿔 끼운다(키 없이, 답을 미리 정해 둠).
확인하는 것:
- 보낼 조각 고르기: 짧은 조각(공백 뺀 80자 미만) 건너뜀, 10개보다 많으면 노트 전체에서 고르게, 항상 같은 결과.
- 보내는 내용: 고른 조각만(원칙 6), 다른 노트 · 짧은 조각은 안 보냄.
- 내용 검사: 이유별로 버림 — 특히 인용 문장이 조각 안에 글자 그대로 없으면 버림(D-003). 조각마다 1개.
- 저장: 문제 · 근거 위치(노트 원문[시작:끝] == 인용) · 복습 상태(오늘, 한국 날짜) · 평가 로그 · 사용량.
- AI를 부르지 않는 경우: 남의 노트 404, 이미 문제 있음 409, 긴 조각 없음 422, 하루 상한 429.
- AI 오류: 형식 오류 502 · 연결 안 됨 503 — 문제는 저장하지 않고 평가 로그 · 사용량은 남김. 다시 누를 수 있음.
- mock 설정(LLM_PROVIDER=mock)이면 키 없이도 문제가 만들어짐.
"""

import json
import os
import threading
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.quizzes import get_quiz_llm_client
from app.config import DEFAULT_DAILY_LIMIT, QUIZ_CLAIM_STALE_SECONDS, SESSION_COOKIE_NAME, Settings
from app.db.models import AIUsageLog, Chunk, Note, NoteQuizClaim, Quiz, QuizGenerationLog, QuizReview
from app.korea_time import korea_today
from app.llm import (
    LLMConfigError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMReply,
    LLMUnavailable,
    LLMUsage,
    MockLLMClient,
    StructuredReply,
)
from app.main import app
from app.services.auth_service import GoogleProfile, create_session_token, get_or_create_google_user
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user, delete_user_account
from app.services.quiz_generation import (
    DROP_BAD_ANSWER_INDEX,
    DROP_BAD_CHOICES,
    DROP_DUPLICATE_CHUNK,
    DROP_EMPTY_TEXT,
    DROP_QUOTE_NOT_FOUND,
    DROP_QUOTE_TOO_SHORT,
    DROP_TOO_LONG,
    DROP_UNKNOWN_CHUNK,
    GenerationInProgress,
    OtherNoteInProgress,
    QuizBatchIn,
    QuizDraftIn,
    build_messages,
    check_drafts,
    prepare_generation,
    save_generation,
    select_chunks,
)
from app.services.usage_service import FEATURE_QUIZ_GENERATE, record_usage

TCP_QUOTE = "TCP는 연결을 먼저 맺고 데이터를 보내는 연결 지향 프로토콜이라서, 보낸 순서대로 도착하는 것을 보장해요."
UDP_QUOTE = "UDP는 연결을 맺지 않고 바로 보내서 빠르지만, 순서와 도착을 보장하지 않아요."

NETWORK_NOTE = f"""# 네트워크

## TCP
{TCP_QUOTE}
세 번 악수(3-way handshake)로 연결을 맺고, 잃어버린 조각은 다시 보내서 믿을 수 있게 전달해요.

## UDP
{UDP_QUOTE}
실시간 영상이나 온라인 게임처럼 조금 잃어도 빨라야 하는 곳에 쓰고, 머리말이 8바이트로 아주 작아요.

## 짧음
짧은 메모.
"""

SHORT_NOTE = """# 메모

## 하나
짧아요.

## 둘
이것도 짧아요.
"""


def _login(client: TestClient, db: Session, settings: Settings, sub: str) -> int:
    user = get_or_create_google_user(db, GoogleProfile(sub=sub, email=f"{sub}@example.com", name=sub))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user.id, settings.session_secret))
    return user.id


def _add_note(db: Session, user_id: int, content: str = NETWORK_NOTE, title: str = "네트워크") -> Note:
    return create_note_for_user(db, user_id=user_id, title=title, content=content, chunks=split_markdown(content))


def _chunks(db: Session, note: Note) -> dict[str, Chunk]:
    """제목 경로의 마지막 제목 → 조각. 예) "TCP" → TCP 조각."""
    rows = db.scalars(select(Chunk).where(Chunk.note_id == note.id).order_by(Chunk.position)).all()
    return {row.heading_path.split("## ")[-1]: row for row in rows}


def _draft(chunk_id: int, quote: str, **overrides: object) -> dict[str, object]:
    draft: dict[str, object] = {
        "chunk_id": chunk_id,
        "kind": "mcq",
        "question": "다음 중 맞는 설명은?",
        "choices": ["보기 1", "보기 2", "보기 3", "보기 4"],
        "answer_index": 0,
        "explanation": "기록에 그렇게 적혀 있어요.",
        "quote": quote,
    }
    draft.update(overrides)
    return draft


def _reply(*drafts: dict[str, object]) -> str:
    return json.dumps({"quizzes": list(drafts)}, ensure_ascii=False)


def _use_mock(*replies: str | Exception) -> MockLLMClient:
    mock = MockLLMClient(replies, default_reply=None)
    app.dependency_overrides[get_quiz_llm_client] = lambda: mock
    return mock


def _count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


# --- 보낼 조각 고르기 (DB 없음) ---


def _fake_chunk(position: int, content: str) -> Chunk:
    return Chunk(id=position + 1, position=position, content=content, heading_path="", start_offset=0, end_offset=len(content))


def test_short_chunks_are_skipped_by_visible_characters() -> None:
    """공백 · 줄바꿈은 세지 않는다. 79자는 빠지고 80자는 남는다."""
    chunks = [_fake_chunk(0, "가 " * 79), _fake_chunk(1, "나\n" * 80)]

    assert [chunk.position for chunk in select_chunks(chunks)] == [1]


def test_more_than_ten_chunks_are_spread_over_the_whole_note() -> None:
    chunks = [_fake_chunk(position, "가" * 80) for position in reversed(range(30))]  # 순서가 섞여 들어와도

    picked = [chunk.position for chunk in select_chunks(chunks)]

    assert picked == [0, 3, 6, 9, 12, 15, 18, 21, 24, 27]
    assert [chunk.position for chunk in select_chunks(chunks)] == picked  # 항상 같은 결과


def test_ten_or_fewer_chunks_are_all_sent_in_order() -> None:
    chunks = [_fake_chunk(position, "가" * 80) for position in (2, 0, 1)]

    assert [chunk.position for chunk in select_chunks(chunks)] == [0, 1, 2]


# --- 내용 검사 ---


def test_drafts_are_checked_one_by_one_with_a_reason(db_session: Session) -> None:
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="c", email="c@example.com", name="c")).id
    note = _add_note(db_session, user_id)
    tcp, udp = _chunks(db_session, note)["TCP"], _chunks(db_session, note)["UDP"]
    drafts = [
        QuizDraftIn.model_validate(item)
        for item in (
            _draft(9999, TCP_QUOTE),  # 보내지 않은 조각
            _draft(tcp.id, "TCP는 연결 없이 보내는 빠른 프로토콜이에요."),  # 기록에 없는 문장 — 지어낸 근거
            _draft(tcp.id, "TCP"),  # 너무 짧은 인용
            _draft(tcp.id, TCP_QUOTE, choices=["1", "2", "3"]),  # 객관식 보기 3개
            _draft(tcp.id, TCP_QUOTE, choices=["1", "1", "2", "3"]),  # 같은 보기
            _draft(tcp.id, TCP_QUOTE, kind="ox", choices=["맞다", "틀리다"]),  # OX 보기가 O/X가 아님
            _draft(tcp.id, TCP_QUOTE, answer_index=4),  # 정답 번호 범위 밖
            _draft(tcp.id, TCP_QUOTE, question="  "),  # 빈 문제
            _draft(tcp.id, TCP_QUOTE, explanation="가" * 1001),  # 너무 긴 해설
            _draft(tcp.id, f"  {TCP_QUOTE}\n", kind="ox", choices=["o", "x"], answer_index=1),  # 통과(공백 · 소문자 정리)
            _draft(tcp.id, TCP_QUOTE),  # 같은 조각 두 번째
            _draft(udp.id, UDP_QUOTE),  # 통과
        )
    ]

    result = check_drafts(drafts, [tcp, udp])

    assert dict(result.drop_reasons) == {
        DROP_UNKNOWN_CHUNK: 1,
        DROP_QUOTE_NOT_FOUND: 1,
        DROP_QUOTE_TOO_SHORT: 1,
        DROP_BAD_CHOICES: 3,
        DROP_BAD_ANSWER_INDEX: 1,
        DROP_EMPTY_TEXT: 1,
        DROP_TOO_LONG: 1,
        DROP_DUPLICATE_CHUNK: 1,
    }
    assert [(item.chunk.id, item.kind, item.choices, item.answer_index) for item in result.kept] == [
        (tcp.id, "ox", ["O", "X"], 1),
        (udp.id, "mcq", ["보기 1", "보기 2", "보기 3", "보기 4"], 0),
    ]
    for item in result.kept:  # 근거 위치는 노트 원문 기준
        assert note.content[item.quote_start : item.quote_end] == item.quote


def test_quote_must_match_exactly_not_after_rewording(db_session: Session) -> None:
    """띄어쓰기 · 문장 부호 하나만 달라도 근거로 인정하지 않는다(글자 그대로, D-003)."""
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="e", email="e@example.com", name="e")).id
    tcp = _chunks(db_session, _add_note(db_session, user_id))["TCP"]
    reworded = TCP_QUOTE.replace("연결 지향", "연결지향")

    result = check_drafts([QuizDraftIn.model_validate(_draft(tcp.id, reworded))], [tcp])

    assert result.kept == [] and dict(result.drop_reasons) == {DROP_QUOTE_NOT_FOUND: 1}


def test_only_selected_chunks_are_sent(db_session: Session) -> None:
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="m", email="m@example.com", name="m")).id
    note = _add_note(db_session, user_id)
    _add_note(db_session, user_id, content=NETWORK_NOTE.replace("네트워크", "다른 노트") + "\n비밀 메모 내용", title="다른")
    chunks = select_chunks(db_session.scalars(select(Chunk).where(Chunk.note_id == note.id)).all())

    messages = build_messages(note, chunks)

    payload = json.loads(messages[-1].content)
    assert [item["chunk_id"] for item in payload["chunks"]] == [chunk.id for chunk in chunks]
    assert len(chunks) == 2  # TCP · UDP. "짧음"은 빠짐
    assert "짧은 메모" not in messages[-1].content
    assert "비밀 메모" not in messages[-1].content
    assert "글자 하나 바꾸지 않고" in messages[0].content


# --- API: 만들기 성공 ---


def test_generate_saves_checked_quizzes_with_evidence_and_review_state(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "q-ok")
    note = _add_note(db_session, user_id)
    chunks = _chunks(db_session, note)
    mock = _use_mock(
        _reply(
            _draft(chunks["TCP"].id, TCP_QUOTE),
            _draft(chunks["UDP"].id, "UDP는 항상 순서를 보장해요."),  # 지어낸 근거 → 버림
        )
    )

    response = client.post(f"/api/notes/{note.id}/quizzes")

    assert response.status_code == 201
    assert response.json() == {
        "note_id": note.id,
        "created": 1,
        "dropped": 1,
        "drop_reasons": {DROP_QUOTE_NOT_FOUND: 1},
        "remaining_today": DEFAULT_DAILY_LIMIT - 1,
    }
    assert len(mock.calls) == 1

    quiz = db_session.scalars(select(Quiz)).one()
    assert (quiz.user_id, quiz.note_id, quiz.chunk_id) == (user_id, note.id, chunks["TCP"].id)
    assert note.content[quiz.quote_start : quiz.quote_end] == quiz.quote == TCP_QUOTE
    review = db_session.scalars(select(QuizReview)).one()
    assert (review.quiz_id, review.interval_step, review.correct_streak, review.in_wrong_notes) == (quiz.id, 0, 0, False)
    assert review.next_review_on == korea_today()

    log = db_session.scalars(select(QuizGenerationLog)).one()
    assert (log.note_id, log.chunks_sent, log.kept, log.dropped, log.drop_reasons, log.outcome) == (
        note.id,
        2,
        1,
        1,
        {DROP_QUOTE_NOT_FOUND: 1},
        "ok",
    )
    usage = db_session.scalars(select(AIUsageLog)).one()
    assert (usage.user_id, usage.feature, usage.calls, usage.outcome) == (user_id, FEATURE_QUIZ_GENERATE, 1, "ok")


def test_format_retry_counts_both_calls(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    user_id = _login(client, db_session, test_settings, "q-retry")
    note = _add_note(db_session, user_id)
    mock = _use_mock("JSON이 아니에요", _reply(_draft(_chunks(db_session, note)["TCP"].id, TCP_QUOTE)))

    response = client.post(f"/api/notes/{note.id}/quizzes")

    assert response.status_code == 201
    assert response.json()["remaining_today"] == DEFAULT_DAILY_LIMIT - 2
    assert len(mock.calls) == 2
    assert db_session.scalar(select(AIUsageLog.calls)) == 2


def test_all_dropped_is_logged_and_the_note_can_be_tried_again(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "q-none")
    note = _add_note(db_session, user_id)
    _use_mock(_reply(_draft(_chunks(db_session, note)["TCP"].id, "기록에 없는 문장이에요.")), _reply())

    first = client.post(f"/api/notes/{note.id}/quizzes")
    second = client.post(f"/api/notes/{note.id}/quizzes")

    assert first.status_code == 201 and first.json()["created"] == 0
    assert second.status_code == 201  # 문제가 0개면 "이미 있음"이 아니다
    assert db_session.scalars(select(QuizGenerationLog.outcome).order_by(QuizGenerationLog.id)).all() == [
        "all_dropped",
        "all_dropped",
    ]


# --- API: AI를 부르지 않는 경우 ---


def test_second_generate_on_the_same_note_is_refused_without_calling_ai(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "q-twice")
    note = _add_note(db_session, user_id)
    mock = _use_mock(_reply(_draft(_chunks(db_session, note)["TCP"].id, TCP_QUOTE)))
    assert client.post(f"/api/notes/{note.id}/quizzes").status_code == 201

    response = client.post(f"/api/notes/{note.id}/quizzes")

    assert response.status_code == 409
    assert response.json()["detail"] == "이 노트에는 이미 문제가 있어요."
    assert len(mock.calls) == 1
    assert _count(db_session, AIUsageLog) == 1


@pytest.mark.parametrize("path_id", ["other", "2147483648", "0"])
def test_someone_elses_or_missing_note_is_404_without_calling_ai(
    client: TestClient, db_session: Session, test_settings: Settings, path_id: str
) -> None:
    owner = get_or_create_google_user(db_session, GoogleProfile(sub="owner", email="o@example.com", name="o"))
    others_note = _add_note(db_session, owner.id)
    _login(client, db_session, test_settings, "q-intruder")
    mock = _use_mock()

    note_id = others_note.id if path_id == "other" else path_id
    response = client.post(f"/api/notes/{note_id}/quizzes")

    assert response.status_code == 404
    assert mock.calls == []
    assert _count(db_session, Quiz) == 0


def test_note_without_long_enough_chunks_is_422_without_calling_ai(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "q-short")
    note = _add_note(db_session, user_id, content=SHORT_NOTE, title="메모")
    mock = _use_mock()

    response = client.post(f"/api/notes/{note.id}/quizzes")

    assert response.status_code == 422
    assert mock.calls == []


def test_daily_limit_reached_is_429_without_calling_ai(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "q-limit")
    note = _add_note(db_session, user_id)
    record_usage(
        db_session,
        user_id=user_id,
        feature=FEATURE_QUIZ_GENERATE,
        usage=LLMUsage(calls=DEFAULT_DAILY_LIMIT),
        outcome="ok",
    )
    mock = _use_mock()

    response = client.post(f"/api/notes/{note.id}/quizzes")

    assert response.status_code == 429
    assert response.json()["detail"] == f"오늘 AI 사용량({DEFAULT_DAILY_LIMIT}회)을 다 썼어요. 한국 시간 0시에 다시 쓸 수 있어요."
    assert mock.calls == []
    assert _count(db_session, QuizGenerationLog) == 0


def test_login_is_required(client: TestClient) -> None:
    assert client.post("/api/notes/1/quizzes").status_code == 401


# --- API: AI 오류 ---


@pytest.mark.parametrize(
    ("replies", "status_code", "outcome", "calls"),
    [
        (["깨진 답", "또 깨진 답"], 502, "invalid_output", 2),
        ([LLMUnavailable("down")], 503, "unavailable", 1),
        ([LLMRateLimited("429")], 503, "rate_limited", 1),  # AI 서버 한도 — 사용자가 고칠 수 없어 503
        ([LLMConfigError("키 거절")], 500, "config_error", 1),  # 설정 오류 — 설정 내용은 화면에 안 보냄
    ],
)
def test_ai_failure_saves_no_quiz_but_logs_usage(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
    replies: Sequence[str | Exception],
    status_code: int,
    outcome: str,
    calls: int,
) -> None:
    user_id = _login(client, db_session, test_settings, f"q-fail-{status_code}")
    note = _add_note(db_session, user_id)
    _use_mock(*replies)

    response = client.post(f"/api/notes/{note.id}/quizzes")

    assert response.status_code == status_code
    assert "깨진" not in response.text  # AI 답 원문을 화면에 보내지 않는다
    assert _count(db_session, Quiz) == 0
    assert db_session.scalar(select(QuizGenerationLog.outcome)) == outcome
    usage = db_session.scalars(select(AIUsageLog)).one()
    assert (usage.calls, usage.outcome) == (calls, outcome)


def test_invalid_output_error_keeps_the_raw_reply_out_of_the_log(
    client: TestClient, db_session: Session, test_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    user_id = _login(client, db_session, test_settings, "q-raw")
    note = _add_note(db_session, user_id)
    _use_mock(LLMInvalidOutput("형식", attempts=2, raw_content="비밀 원문 답"))

    assert client.post(f"/api/notes/{note.id}/quizzes").status_code == 502
    assert "비밀 원문" not in caplog.text


# --- mock 설정으로 키 없이 ---


def test_mock_provider_makes_quizzes_without_a_key(
    client: TestClient, db_session: Session, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    user_id = _login(client, db_session, test_settings, "q-mock")
    note = _add_note(db_session, user_id)

    response = client.post(f"/api/notes/{note.id}/quizzes")

    assert response.status_code == 201
    assert response.json()["created"] == 2 and response.json()["dropped"] == 0
    for quiz in db_session.scalars(select(Quiz)).all():
        assert note.content[quiz.quote_start : quiz.quote_end] == quiz.quote


# --- 사용자 삭제 ---


def test_deleting_the_user_deletes_quizzes_reviews_and_logs(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "q-delete")
    note = _add_note(db_session, user_id)
    _use_mock(_reply(_draft(_chunks(db_session, note)["TCP"].id, TCP_QUOTE)))
    assert client.post(f"/api/notes/{note.id}/quizzes").status_code == 201

    delete_user_account(db_session, user_id=user_id)

    for model in (Quiz, QuizReview, QuizGenerationLog, AIUsageLog):
        assert _count(db_session, model) == 0, model.__name__


def test_first_review_day_is_the_korea_date(db_session: Session) -> None:
    """UTC 날짜와 한국 날짜가 다른 시각(UTC 15시 이후)에 만들어도 첫 복습일은 한국 날짜다."""
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="k", email="k@example.com", name="k")).id
    note = _add_note(db_session, user_id)
    late_utc = datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc)  # 한국 11-11 01:00
    plan = prepare_generation(db_session, user_id=user_id, note_id=note.id, now=late_utc)
    batch = QuizBatchIn.model_validate_json(_reply(_draft(_chunks(db_session, note)["TCP"].id, TCP_QUOTE)))
    reply = StructuredReply(value=batch, reply=LLMReply(content="", model="mock"), attempts=1, usage=LLMUsage(calls=1))

    save_generation(db_session, plan, reply, now=late_utc)

    assert db_session.scalar(select(QuizReview.next_review_on)) == date(2026, 11, 11)


# --- 동시 클릭 막기 (선점 행 + 유니크, 사용자 확인 2026-11-11) ---


def _claims(db: Session) -> list[int]:
    db.expire_all()
    return list(db.scalars(select(NoteQuizClaim.note_id)).all())


def test_fresh_claim_by_another_request_is_409_without_calling_ai(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "c-busy")
    note = _add_note(db_session, user_id)
    db_session.add(NoteQuizClaim(user_id=user_id, note_id=note.id, claimed_at=datetime.now(timezone.utc)))
    db_session.commit()
    mock = _use_mock()

    response = client.post(f"/api/notes/{note.id}/quizzes")

    assert response.status_code == 409
    assert response.json()["detail"] == "이 노트의 문제를 만드는 중이에요. 잠시 뒤 다시 확인해 주세요."
    assert mock.calls == []
    assert _count(db_session, AIUsageLog) == 0


def test_stale_claim_is_taken_over(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    """서버가 도중에 죽어 남은 선점(5분 넘음)은 새 요청이 가져간다."""
    user_id = _login(client, db_session, test_settings, "c-stale")
    note = _add_note(db_session, user_id)
    old = datetime.now(timezone.utc) - timedelta(seconds=QUIZ_CLAIM_STALE_SECONDS + 1)
    db_session.add(NoteQuizClaim(user_id=user_id, note_id=note.id, claimed_at=old))
    db_session.commit()
    _use_mock(_reply(_draft(_chunks(db_session, note)["TCP"].id, TCP_QUOTE)))

    assert client.post(f"/api/notes/{note.id}/quizzes").status_code == 201
    assert _claims(db_session) == [note.id]


def test_claim_stays_after_success_and_is_released_after_failure_or_all_dropped(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "c-release")
    ok_note = _add_note(db_session, user_id)
    failed_note = _add_note(db_session, user_id, content=NETWORK_NOTE + "\n실패할 노트", title="실패")
    empty_note = _add_note(db_session, user_id, content=NETWORK_NOTE + "\n다 버릴 노트", title="버림")
    _use_mock(
        _reply(_draft(_chunks(db_session, ok_note)["TCP"].id, TCP_QUOTE)),
        LLMUnavailable("down"),
        _reply(_draft(_chunks(db_session, empty_note)["TCP"].id, "기록에 없는 문장이에요.")),
    )

    assert client.post(f"/api/notes/{ok_note.id}/quizzes").status_code == 201
    assert client.post(f"/api/notes/{failed_note.id}/quizzes").status_code == 503
    assert client.post(f"/api/notes/{empty_note.id}/quizzes").status_code == 201

    assert _claims(db_session) == [ok_note.id]


def test_save_failure_releases_the_claim_and_still_records_usage(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="c-save", email="s@example.com", name="s")).id
    note = _add_note(db_session, user_id)
    plan = prepare_generation(db_session, user_id=user_id, note_id=note.id)
    batch = QuizBatchIn.model_validate_json(_reply(_draft(_chunks(db_session, note)["TCP"].id, TCP_QUOTE)))
    reply = StructuredReply(value=batch, reply=LLMReply(content="", model="mock"), attempts=1, usage=LLMUsage(calls=1))
    original_commit = db_session.commit
    commits: list[int] = []

    def commit_failing_once() -> None:
        commits.append(1)
        if len(commits) == 1:
            raise OperationalError("INSERT", {}, Exception("db down"))
        original_commit()

    monkeypatch.setattr(db_session, "commit", commit_failing_once)

    with pytest.raises(OperationalError):
        save_generation(db_session, plan, reply)

    monkeypatch.undo()
    assert _count(db_session, Quiz) == 0
    assert _claims(db_session) == []
    assert db_session.scalar(select(AIUsageLog.outcome)) == "save_failed"


def test_two_requests_at_the_same_time_only_one_claims(db_session: Session) -> None:
    """서로 다른 세션 두 개가 동시에 선점해도 하나만 통과한다(유니크 제약)."""
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="c-race", email="r@example.com", name="r")).id
    note_id = _add_note(db_session, user_id).id
    make_session = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt() -> None:
        with make_session() as session:
            barrier.wait()
            try:
                prepare_generation(session, user_id=user_id, note_id=note_id)
                results.append("claimed")
            except GenerationInProgress:
                results.append("busy")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == ["busy", "claimed"]
    assert _claims(db_session) == [note_id]


def test_one_quiz_per_chunk_is_enforced_by_the_db(db_session: Session) -> None:
    """선점이 뚫려도(예: 5분 넘게 걸린 요청) 같은 조각에 문제가 두 개 저장되지 않는 안전망."""
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="c-uq", email="u@example.com", name="u")).id
    note = _add_note(db_session, user_id)
    tcp = _chunks(db_session, note)["TCP"]

    def quiz() -> Quiz:
        start = note.content.index(TCP_QUOTE)
        return Quiz(
            user_id=user_id, note_id=note.id, chunk_id=tcp.id, kind="ox", question="q", choices=["O", "X"],
            answer_index=0, explanation="e", quote=TCP_QUOTE, quote_start=start, quote_end=start + len(TCP_QUOTE),
        )

    db_session.add(quiz())
    db_session.commit()
    db_session.add(quiz())
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_deleting_the_user_deletes_claims(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    user_id = _login(client, db_session, test_settings, "c-delete")
    note = _add_note(db_session, user_id)
    _use_mock(_reply(_draft(_chunks(db_session, note)["TCP"].id, TCP_QUOTE)))
    assert client.post(f"/api/notes/{note.id}/quizzes").status_code == 201

    delete_user_account(db_session, user_id=user_id)

    assert _claims(db_session) == []


# --- 1차 리뷰 반영: 예상 못 한 오류 · 저장 실패 안내 · 사용자당 동시 생성 1개 ---

ON_POSTGRES = bool(os.getenv("TEST_DATABASE_URL", "").strip())


class _ExplodingClient:
    """LLMError가 아닌 예외를 내는 AI(버그 · 요청 취소 흉내)."""

    async def chat(self, messages: Sequence[object]) -> LLMReply:
        raise RuntimeError("예상 못 한 오류")


def test_unexpected_error_records_one_call_logs_and_releases_the_claim(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "c-boom")
    note = _add_note(db_session, user_id)
    app.dependency_overrides[get_quiz_llm_client] = lambda: _ExplodingClient()

    with pytest.raises(RuntimeError):
        client.post(f"/api/notes/{note.id}/quizzes")

    assert _claims(db_session) == []  # 5분 기다리지 않고 다시 누를 수 있다
    usage = db_session.scalars(select(AIUsageLog)).one()
    assert (usage.calls, usage.outcome) == (1, "error")  # 불렀을 수 있으니 1회로 센다(D-018)
    assert db_session.scalar(select(QuizGenerationLog.outcome)) == "error"


def test_save_failure_answers_500_with_a_message(
    client: TestClient, db_session: Session, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = _login(client, db_session, test_settings, "c-save-api")
    note = _add_note(db_session, user_id)
    _use_mock(_reply(_draft(_chunks(db_session, note)["TCP"].id, TCP_QUOTE)))

    def failing_save(*args: object, **kwargs: object) -> None:
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr("app.api.quizzes.save_generation", failing_save)

    response = client.post(f"/api/notes/{note.id}/quizzes")

    assert response.status_code == 500
    assert response.json()["detail"] == "만든 문제를 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요."


def test_one_generation_per_user_at_a_time(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    """다른 노트를 만드는 중이면 AI를 부르지 않고 409(사용자당 동시에 1개, F-004 1차 리뷰 R2)."""
    user_id = _login(client, db_session, test_settings, "c-one")
    busy = _add_note(db_session, user_id)
    other = _add_note(db_session, user_id, content=NETWORK_NOTE + "\n다른 노트", title="다른")
    db_session.add(NoteQuizClaim(user_id=user_id, note_id=busy.id, claimed_at=datetime.now(timezone.utc)))
    db_session.commit()
    mock = _use_mock()

    response = client.post(f"/api/notes/{other.id}/quizzes")

    assert response.status_code == 409
    assert response.json()["detail"] == "다른 노트의 문제를 만드는 중이에요. 끝난 뒤 다시 시도해 주세요."
    assert mock.calls == [] and _claims(db_session) == [busy.id]


def test_stale_or_finished_claims_on_other_notes_do_not_block(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """5분 넘은 선점(서버가 죽음)과 성공해서 남은 선점(그 노트에 문제가 있음)은 진행 중이 아니다."""
    user_id = _login(client, db_session, test_settings, "c-free")
    stale = _add_note(db_session, user_id)
    target = _add_note(db_session, user_id, content=NETWORK_NOTE + "\n대상", title="대상")
    old = datetime.now(timezone.utc) - timedelta(seconds=QUIZ_CLAIM_STALE_SECONDS + 1)
    db_session.add(NoteQuizClaim(user_id=user_id, note_id=stale.id, claimed_at=old))
    db_session.commit()
    _use_mock(_reply(_draft(_chunks(db_session, target)["TCP"].id, TCP_QUOTE)))

    assert client.post(f"/api/notes/{target.id}/quizzes").status_code == 201


def test_another_users_claim_does_not_block(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    other_user = get_or_create_google_user(db_session, GoogleProfile(sub="c-x", email="x@example.com", name="x")).id
    other_note = _add_note(db_session, other_user)
    db_session.add(NoteQuizClaim(user_id=other_user, note_id=other_note.id, claimed_at=datetime.now(timezone.utc)))
    db_session.commit()
    user_id = _login(client, db_session, test_settings, "c-me")
    note = _add_note(db_session, user_id, content=NETWORK_NOTE + "\n내 노트", title="내 노트")
    _use_mock(_reply(_draft(_chunks(db_session, note)["TCP"].id, TCP_QUOTE)))

    assert client.post(f"/api/notes/{note.id}/quizzes").status_code == 201


@pytest.mark.skipif(not ON_POSTGRES, reason="사용자 줄 잠금(FOR UPDATE)은 PostgreSQL에서만 시험한다")
def test_two_notes_at_the_same_time_only_one_claims(db_session: Session) -> None:
    """같은 사용자가 서로 다른 노트를 동시에 선점해도 하나만 통과한다(사용자 줄 잠금)."""
    user_id = get_or_create_google_user(db_session, GoogleProfile(sub="c-race2", email="r2@example.com", name="r")).id
    note_ids = [
        _add_note(db_session, user_id).id,
        _add_note(db_session, user_id, content=NETWORK_NOTE + "\n둘째", title="둘째").id,
    ]
    make_session = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt(note_id: int) -> None:
        with make_session() as session:
            barrier.wait()
            try:
                prepare_generation(session, user_id=user_id, note_id=note_id)
                results.append("claimed")
            except OtherNoteInProgress:
                results.append("busy")

    threads = [threading.Thread(target=attempt, args=(note_id,)) for note_id in note_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == ["busy", "claimed"]
    assert len(_claims(db_session)) == 1
