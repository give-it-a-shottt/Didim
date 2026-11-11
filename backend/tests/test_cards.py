"""경험 카드 (F-006) 테스트.

① 표 구조(버전 0005): 노트 · 조각이 지워져도 카드(사용자 답)는 남고 근거만 끊긴다, 칸은 카드마다 한 줄씩,
   사용자를 지우면 카드 관련 줄이 모두 지워진다(D-004).
② 후보 찾기: 보낼 조각(앞에서부터 상한까지), 칸마다 원문 인용 검사(글자 그대로 없으면 빈칸 + 질문, D-003),
   인용이 하나도 없는 후보는 버림, 노트당 최대 3개, 선점(이미 찾음 409 · 찾는 중 409 · 0개면 다시 누를 수 있음),
   AI 오류, 평가 로그 · 사용량(D-018). AI는 MockLLMClient로 바꿔 끼운다.
③ 카드 API: 목록(빈칸 수 · 근거 수) · 상세 · 저장 · 버리기 · 내 답 · 인용 빼기, 남의 카드는 404(D-004).
"""

import asyncio
import json
import os
import threading
import typing
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api import errors as api_errors
from app.api import cards as cards_api
from app.api.cards import Slot, get_card_llm_client
from app.config import (
    CARD_CLAIM_STALE_SECONDS,
    CARD_DEFAULT_QUESTIONS,
    CARD_MAX_ANSWER_CHARS,
    CARD_MAX_CANDIDATES_PER_NOTE,
    CARD_MAX_QUESTION_CHARS,
    CARD_MAX_QUOTE_CHARS,
    CARD_SLOTS,
    CARD_STATUS_CANDIDATE,
    CARD_STATUS_SAVED,
    CARD_TITLE_MAX_CHARS,
    DEFAULT_DAILY_LIMIT,
    SESSION_COOKIE_NAME,
    Settings,
)
from app.db.models import AIUsageLog, Card, CardField, CardGenerationLog, Chunk, Note, NoteCardClaim, NoteQuizClaim
from app.llm import LLMConfigError, LLMRateLimited, LLMUnavailable, LLMUsage, MockLLMClient
from app.main import app
from app.services.auth_service import GoogleProfile, create_session_token, get_or_create_google_user
from app.services.card_generation import (
    DROP_NO_QUOTE,
    DROP_QUOTE_NOT_FOUND,
    DROP_QUOTE_TOO_LONG,
    DROP_QUOTE_TOO_SHORT,
    DROP_TOO_MANY,
    DROP_UNKNOWN_CHUNK,
    CardDraftIn,
    ClaimLost,
    OtherAIWorkInProgress,
    SearchInProgress,
    abandon_search,
    check_cards,
    mock_card_responder,
    prepare_search,
    request_card_drafts,
    save_search,
    select_chunks,
)
from app.services import note_claim, quiz_generation
from app.services.card_service import InvalidCardInput, update_field
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user, delete_user_account
from app.services.usage_service import FEATURE_CARD_FIND, record_usage

PROJECT_NOTE = """# 주문 서버 개선

## 상황
주문이 몰리는 시간에 상품 목록 응답이 3초 넘게 걸려서 사용자 이탈이 늘었다.

## 행동
자주 읽는 상품 목록을 Redis에 캐시하고, 상품이 바뀌면 캐시를 지우도록 바꿨다.
"""



def _as_utc(value: datetime) -> datetime:
    """SQLite는 시간대 없는 시각을 돌려준다(저장은 UTC) — 비교 전에 맞춘다."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

def _user(db: Session, name: str) -> int:
    return get_or_create_google_user(db, GoogleProfile(sub=name, email=f"{name}@example.com", name=name)).id


def _note(db: Session, user_id: int) -> Note:
    return create_note_for_user(
        db, user_id=user_id, title="주문 서버 개선", content=PROJECT_NOTE, chunks=split_markdown(PROJECT_NOTE)
    )


def _card_with_quote(db: Session, user_id: int, note: Note) -> Card:
    """상황 칸에 원문 인용, 나머지 칸은 빈칸(질문만)인 후보 카드."""
    chunk = db.scalars(select(Chunk).where(Chunk.note_id == note.id).order_by(Chunk.position)).first()
    assert chunk is not None
    quote = "상품 목록 응답이 3초 넘게 걸려서"
    start = note.content.index(quote)
    card = Card(user_id=user_id, note_id=note.id, title="상품 목록 캐시", status=CARD_STATUS_CANDIDATE)
    for slot in CARD_SLOTS:
        if slot == "situation":
            field = CardField(
                user_id=user_id,
                slot=slot,
                quote=quote,
                quote_start=start,
                quote_end=start + len(quote),
                chunk_id=chunk.id,
            )
        else:
            field = CardField(user_id=user_id, slot=slot, question=f"{slot} 칸을 채워 주세요")
        card.fields.append(field)
    db.add(card)
    db.commit()
    return card


def _count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_deleting_the_note_keeps_the_card_and_cuts_only_the_evidence(db_session: Session) -> None:
    """노트가 지워져도 사용자 답이 든 카드는 남고, 근거(노트 · 조각)만 비어 '원문 없음'이 된다."""
    user_id = _user(db_session, "card-note-delete")
    note = _note(db_session, user_id)
    card = _card_with_quote(db_session, user_id, note)
    for field in card.fields:
        field.answer = "내가 쓴 답"
    db_session.commit()

    db_session.execute(delete(Note).where(Note.id == note.id))
    db_session.commit()
    db_session.expire_all()

    kept = db_session.get(Card, card.id)
    assert kept is not None
    assert kept.note_id is None
    assert len(kept.fields) == len(CARD_SLOTS)
    assert all(field.chunk_id is None for field in kept.fields)
    assert all(field.answer == "내가 쓴 답" for field in kept.fields)


def test_deleting_the_card_deletes_its_fields(db_session: Session) -> None:
    user_id = _user(db_session, "card-delete")
    card = _card_with_quote(db_session, user_id, _note(db_session, user_id))

    db_session.execute(delete(Card).where(Card.id == card.id))
    db_session.commit()

    assert _count(db_session, CardField) == 0


def test_a_card_has_only_one_row_per_slot(db_session: Session) -> None:
    user_id = _user(db_session, "card-slot")
    card = _card_with_quote(db_session, user_id, _note(db_session, user_id))

    db_session.add(CardField(user_id=user_id, card_id=card.id, slot="situation", answer="두 번째 상황"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_a_note_has_only_one_card_claim(db_session: Session) -> None:
    user_id = _user(db_session, "card-claim")
    note = _note(db_session, user_id)
    db_session.add(NoteCardClaim(user_id=user_id, note_id=note.id))
    db_session.commit()

    db_session.add(NoteCardClaim(user_id=user_id, note_id=note.id))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_deleting_the_user_deletes_cards_fields_claims_and_logs(db_session: Session) -> None:
    user_id = _user(db_session, "card-user-delete")
    note = _note(db_session, user_id)
    _card_with_quote(db_session, user_id, note)
    db_session.add(NoteCardClaim(user_id=user_id, note_id=note.id))
    db_session.add(
        CardGenerationLog(
            user_id=user_id,
            note_id=note.id,
            chunks_sent=2,
            candidates=1,
            quoted_fields=1,
            emptied_fields=0,
            drop_reasons={},
            outcome="ok",
        )
    )
    db_session.commit()

    delete_user_account(db_session, user_id=user_id)

    for model in (Card, CardField, NoteCardClaim, CardGenerationLog):
        assert _count(db_session, model) == 0, model.__name__


# --- ② 후보 찾기 ---

SITUATION_QUOTE = "주문이 몰리는 시간에 상품 목록 응답이 3초 넘게 걸려서 사용자 이탈이 늘었다."
ACTION_QUOTE = "자주 읽는 상품 목록을 Redis에 캐시하고, 상품이 바뀌면 캐시를 지우도록 바꿨다."


def _login(client: TestClient, db: Session, settings: Settings, sub: str) -> int:
    user_id = _user(db, sub)
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id, settings.session_secret))
    return user_id


def _chunk_ids(db: Session, note: Note) -> dict[str, int]:
    """제목 경로의 마지막 제목 → 조각 번호. 예) "상황" → 상황 조각."""
    rows = db.scalars(select(Chunk).where(Chunk.note_id == note.id).order_by(Chunk.position)).all()
    return {row.heading_path.split("## ")[-1]: row.id for row in rows}


def _field(chunk_id: int | None = None, quote: str | None = None, question: str | None = None) -> dict[str, object]:
    return {"chunk_id": chunk_id, "quote": quote, "question": question}


def _draft(ids: dict[str, int], **overrides: object) -> dict[str, object]:
    """상황 · 행동은 원문 인용, 과제 · 결과는 빈칸 + 질문인 후보."""
    draft: dict[str, object] = {
        "title": "상품 목록 캐시",
        "situation": _field(ids["상황"], SITUATION_QUOTE),
        "task": _field(question="그때 맡은 일은 무엇이었나요?"),
        "action": _field(ids["행동"], ACTION_QUOTE),
        "result": _field(question="캐시를 넣은 뒤 무엇이 달라졌나요?"),
    }
    draft.update(overrides)
    return draft


def _reply(*drafts: dict[str, object]) -> str:
    return json.dumps({"cards": list(drafts)}, ensure_ascii=False)


def _use_mock(*replies: str | Exception) -> MockLLMClient:
    mock = MockLLMClient(replies, default_reply=None)
    app.dependency_overrides[get_card_llm_client] = lambda: mock
    return mock


def _find(client: TestClient, note_id: int):  # noqa: ANN202
    return client.post(f"/api/notes/{note_id}/cards/candidates")


def _claim(db: Session, note_id: int) -> NoteCardClaim | None:
    db.expire_all()
    return db.scalar(select(NoteCardClaim).where(NoteCardClaim.note_id == note_id))


def _fake_chunk(position: int, content: str) -> Chunk:
    return Chunk(
        id=position + 1, position=position, heading_path="", start_offset=0, end_offset=len(content), content=content
    )


def test_select_chunks_keeps_note_order_and_stops_at_the_limits() -> None:
    chunks = [_fake_chunk(position, "가" * 10) for position in (2, 0, 1, 3)]

    assert [chunk.position for chunk in select_chunks(chunks)] == [0, 1, 2, 3]  # 짧은 조각도 보냄
    assert [chunk.position for chunk in select_chunks(chunks, max_chunks=2)] == [0, 1]
    assert [chunk.position for chunk in select_chunks(chunks, max_chars=25)] == [0, 1]


def test_check_cards_keeps_only_quotes_found_word_for_word(db_session: Session) -> None:
    """인용이 조각 안에 글자 그대로 있어야 남는다(D-003). 없거나 · 짧거나 · 길거나 · 모르는 조각이면 빈칸 + 질문."""
    user_id = _user(db_session, "check")
    note = _note(db_session, user_id)
    chunks = list(db_session.scalars(select(Chunk).where(Chunk.note_id == note.id)).all())
    ids = _chunk_ids(db_session, note)
    draft = CardDraftIn.model_validate(
        _draft(
            ids,
            task=_field(ids["상황"], "응답 시간을 90% 줄이는 과제를 맡았다."),  # 기록에 없는 문장(지어냄)
            result=_field(ids["행동"], "캐시"),  # 너무 짧음
        )
    )
    long_draft = CardDraftIn.model_validate(
        _draft(
            ids,
            situation=_field(999_999, SITUATION_QUOTE),  # 보내지 않은 조각
            action=_field(ids["행동"], "가" * (CARD_MAX_QUOTE_CHARS + 1)),
        )
    )

    result = check_cards([draft, long_draft], chunks, note_title=note.title)

    assert len(result.kept) == 1
    kept = {item.slot: item for item in result.kept[0].fields}
    for slot, quote in (("situation", SITUATION_QUOTE), ("action", ACTION_QUOTE)):
        assert kept[slot].quote == quote
        assert note.content[kept[slot].quote_start : kept[slot].quote_end] == quote  # 노트 원문 위치
        assert kept[slot].question is None
    # 지어낸 인용 · 짧은 인용은 빈칸 + 질문(AI가 질문을 안 줬으므로 기본 질문)
    assert kept["task"].quote is None and kept["task"].question == CARD_DEFAULT_QUESTIONS["task"]
    assert kept["result"].quote is None and kept["result"].question == CARD_DEFAULT_QUESTIONS["result"]
    assert result.quoted_fields == 2
    assert result.emptied_fields == 4
    assert dict(result.drop_reasons) == {
        DROP_QUOTE_NOT_FOUND: 1,
        DROP_QUOTE_TOO_SHORT: 1,
        DROP_UNKNOWN_CHUNK: 1,
        DROP_QUOTE_TOO_LONG: 1,
        DROP_NO_QUOTE: 1,
    }


def test_check_cards_keeps_at_most_three_and_cleans_title_and_question(db_session: Session) -> None:
    user_id = _user(db_session, "check-many")
    note = _note(db_session, user_id)
    chunks = list(db_session.scalars(select(Chunk).where(Chunk.note_id == note.id)).all())
    ids = _chunk_ids(db_session, note)
    drafts = [
        CardDraftIn.model_validate(_draft(ids, title="  ", result=_field(question="질" * (CARD_MAX_QUESTION_CHARS + 1)))),
        CardDraftIn.model_validate(_draft(ids, title="가" * (CARD_TITLE_MAX_CHARS + 5))),
    ] + [CardDraftIn.model_validate(_draft(ids)) for _ in range(CARD_MAX_CANDIDATES_PER_NOTE)]

    result = check_cards(drafts, chunks, note_title=note.title)

    assert len(result.kept) == CARD_MAX_CANDIDATES_PER_NOTE
    assert result.drop_reasons[DROP_TOO_MANY] == len(drafts) - CARD_MAX_CANDIDATES_PER_NOTE
    assert result.kept[0].title == note.title  # 빈 제목 → 노트 제목
    assert result.kept[0].fields[3].question == CARD_DEFAULT_QUESTIONS["result"]  # 너무 긴 질문 → 기본 질문
    assert len(result.kept[1].title) == CARD_TITLE_MAX_CHARS and result.kept[1].title.endswith("…")


def test_find_strips_control_characters_from_ai_title_and_question(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """AI가 NUL 같은 제어 문자를 섞어도 저장이 실패하지 않게 지운다(PostgreSQL은 NUL을 받지 않음, F-006 1차 리뷰 R2)."""
    user_id = _login(client, db_session, test_settings, "ai-nul")
    note = _note(db_session, user_id)
    _use_mock(_reply(_draft(_chunk_ids(db_session, note), title="캐시\u0000 도입", task=_field(question="맡은\u0007 일은?"))))

    response = _find(client, note.id)

    assert response.status_code == 201
    card = client.get(f"/api/cards/{response.json()['card_ids'][0]}").json()
    assert card["title"] == "캐시 도입"
    assert card["fields"][1]["question"] == "맡은 일은?"


def test_find_saves_candidates_with_quotes_logs_and_usage(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "find")
    note = _note(db_session, user_id)
    ids = _chunk_ids(db_session, note)
    mock = _use_mock(_reply(_draft(ids)))

    response = _find(client, note.id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["card_ids"]) == 1
    assert body["quoted_fields"] == 2 and body["emptied_fields"] == 0
    assert body["chunks_sent"] == body["chunks_total"] == len(ids)
    assert body["remaining_today"] == DEFAULT_DAILY_LIMIT - 1
    # 보낸 것은 이 노트의 조각뿐(원칙 6)
    sent = json.loads(mock.calls[0][1].content)
    assert [chunk["chunk_id"] for chunk in sent["chunks"]] == list(ids.values())

    card = db_session.get(Card, body["card_ids"][0])
    assert card is not None and card.status == CARD_STATUS_CANDIDATE and card.note_id == note.id
    claim = _claim(db_session, note.id)
    assert claim is not None and claim.finished_at is not None  # '이미 찾음'
    log = db_session.scalar(select(CardGenerationLog))
    assert log is not None
    assert (log.candidates, log.quoted_fields, log.emptied_fields, log.outcome) == (1, 2, 0, "ok")
    usage = db_session.scalar(select(AIUsageLog))
    assert usage is not None
    assert (usage.feature, usage.calls, usage.outcome) == (FEATURE_CARD_FIND, 1, "ok")


def test_cards_hold_only_word_for_word_quotes_and_no_ai_sentences(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """완료 기준 5: 칸 본문(인용)은 노트 원문 그대로이고, 사용자 답은 비어 있으며, AI가 지어낸 문장은 들어가지 않는다."""
    user_id = _login(client, db_session, test_settings, "no-ai-text")
    note = _note(db_session, user_id)
    ids = _chunk_ids(db_session, note)
    made_up = "Redis 캐시로 응답 시간을 3초에서 0.2초로 줄여 매출이 15% 늘었다."
    _use_mock(_reply(_draft(ids, result=_field(ids["행동"], made_up))))

    assert _find(client, note.id).status_code == 201

    fields = db_session.scalars(select(CardField)).all()
    assert len(fields) == len(CARD_SLOTS)
    for item in fields:
        assert item.answer is None
        if item.quote is not None:
            assert note.content[item.quote_start : item.quote_end] == item.quote
    stored = " ".join(filter(None, (item.quote for item in fields)))
    assert made_up not in stored
    result = next(item for item in fields if item.slot == "result")
    assert result.quote is None and result.question == CARD_DEFAULT_QUESTIONS["result"]


def test_second_find_is_409_without_calling_ai_even_after_discarding_all(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "again")
    note = _note(db_session, user_id)
    mock = _use_mock(_reply(_draft(_chunk_ids(db_session, note))))
    card_id = _find(client, note.id).json()["card_ids"][0]

    assert client.delete(f"/api/cards/{card_id}").status_code == 204
    response = _find(client, note.id)

    assert response.status_code == 409
    assert "이미" in response.json()["detail"]
    assert len(mock.calls) == 1


def test_none_found_releases_the_claim_so_it_can_be_tried_again(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """경험을 못 찾았거나 모두 근거 검사에서 버려지면 다시 누를 수 있다(사용자 확인 2026-11-11)."""
    user_id = _login(client, db_session, test_settings, "none")
    note = _note(db_session, user_id)
    ids = _chunk_ids(db_session, note)
    no_quotes = _draft(
        ids, situation=_field(question="상황은?"), action=_field(ids["행동"], "기록에 없는 행동 문장이에요.")
    )
    mock = _use_mock(_reply(), _reply(no_quotes), _reply(_draft(ids)))

    first = _find(client, note.id)
    second = _find(client, note.id)
    third = _find(client, note.id)

    assert (first.status_code, first.json()["card_ids"]) == (201, [])
    assert (second.status_code, second.json()["card_ids"]) == (201, [])
    assert second.json()["drop_reasons"] == {DROP_QUOTE_NOT_FOUND: 1, DROP_NO_QUOTE: 1}
    assert third.status_code == 201 and len(third.json()["card_ids"]) == 1
    assert len(mock.calls) == 3
    outcomes = db_session.scalars(select(CardGenerationLog.outcome).order_by(CardGenerationLog.id)).all()
    assert outcomes == ["none_found", "none_found", "ok"]


@pytest.mark.parametrize(
    ("replies", "status_code", "outcome"),
    [
        ((LLMUnavailable("down"),), 503, "unavailable"),
        (("형식이 아닌 답", "또 형식이 아닌 답"), 502, "invalid_output"),  # 다시 요청해도 틀리면 형식 오류
        ((LLMRateLimited("AI 서버 한도"),), 503, "rate_limited"),
        ((LLMConfigError("키 거절"),), 500, "config_error"),  # 키 거절 등은 부른 뒤에야 안다
    ],
)
def test_ai_error_saves_nothing_logs_and_releases_the_claim(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
    replies: tuple[str | Exception, ...],
    status_code: int,
    outcome: str,
) -> None:
    user_id = _login(client, db_session, test_settings, f"err-{status_code}")
    note = _note(db_session, user_id)
    _use_mock(*replies)

    assert _find(client, note.id).status_code == status_code

    assert _count(db_session, Card) == 0
    assert _claim(db_session, note.id) is None
    assert db_session.scalar(select(CardGenerationLog.outcome)) == outcome
    assert db_session.scalar(select(AIUsageLog.outcome)) == outcome


def test_other_users_note_is_404_and_daily_limit_is_429_without_calling_ai(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    other_note = _note(db_session, _user(db_session, "someone"))
    user_id = _login(client, db_session, test_settings, "limit")
    note = create_note_for_user(
        db_session, user_id=user_id, title="내 노트", content=PROJECT_NOTE + "\n내 것", chunks=split_markdown(PROJECT_NOTE)
    )
    record_usage(
        db_session, user_id=user_id, feature=FEATURE_CARD_FIND, usage=LLMUsage(calls=DEFAULT_DAILY_LIMIT), outcome="ok"
    )
    mock = _use_mock()

    assert _find(client, other_note.id).status_code == 404
    assert _find(client, note.id).status_code == 429
    assert _find(client, 2**31).status_code == 404
    assert mock.calls == []
    assert _claim(db_session, note.id) is None


def test_note_without_chunks_is_422_without_calling_ai(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "empty")
    note = create_note_for_user(db_session, user_id=user_id, title="빈 노트", content="", chunks=[])
    mock = _use_mock()

    assert _find(client, note.id).status_code == 422
    assert mock.calls == []
    assert _claim(db_session, note.id) is None
    assert _count(db_session, AIUsageLog) == 0


def test_ai_not_configured_is_500_without_calling_ai(
    client: TestClient, db_session: Session, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = _login(client, db_session, test_settings, "no-config")
    note = _note(db_session, user_id)
    app.dependency_overrides.pop(get_card_llm_client, None)

    def broken_settings():  # noqa: ANN202
        raise LLMConfigError("키가 없음")

    monkeypatch.setattr(api_errors, "load_llm_settings", broken_settings)

    response = _find(client, note.id)

    assert (response.status_code, response.json()["detail"]) == (500, api_errors.AI_NOT_CONFIGURED_DETAIL)
    assert _claim(db_session, note.id) is None
    assert _count(db_session, AIUsageLog) == 0


def test_claim_in_progress_is_409_and_stale_claim_is_taken_over(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "claims")
    busy = _note(db_session, user_id)
    stale_content = PROJECT_NOTE + "\n오래된 선점"
    stale = create_note_for_user(
        db_session, user_id=user_id, title="오래된", content=stale_content, chunks=split_markdown(stale_content)
    )
    db_session.add(NoteCardClaim(user_id=user_id, note_id=busy.id, claimed_at=datetime.now(timezone.utc)))
    old = datetime.now(timezone.utc) - timedelta(seconds=CARD_CLAIM_STALE_SECONDS + 1)
    db_session.add(NoteCardClaim(user_id=user_id, note_id=stale.id, claimed_at=old))
    db_session.commit()
    mock = _use_mock(_reply(_draft(_chunk_ids(db_session, stale))))

    in_progress = _find(client, busy.id)
    assert in_progress.status_code == 409 and "찾는 중" in in_progress.json()["detail"]
    # busy가 진행 중이라 다른 노트(stale)도 막힘 — 사용자당 AI 작업 1개(Q-023)
    other = _find(client, stale.id)
    assert (other.status_code, other.json()["detail"]) == (409, api_errors.OTHER_AI_WORK_DETAIL)
    assert mock.calls == []

    db_session.execute(delete(NoteCardClaim).where(NoteCardClaim.note_id == busy.id))
    db_session.commit()
    assert _find(client, stale.id).status_code == 201  # 5분 넘은 선점은 가져감
    claim = _claim(db_session, stale.id)
    assert claim is not None and claim.finished_at is not None


def test_mock_responder_makes_a_candidate_whose_quotes_pass_the_check(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """LLM_PROVIDER=mock(키 없이 화면 확인)이어도 후보가 생기고, 인용은 실제 조각 안에 있다."""
    user_id = _login(client, db_session, test_settings, "mock")
    note = _note(db_session, user_id)
    app.dependency_overrides[get_card_llm_client] = lambda: MockLLMClient(responder=mock_card_responder)

    body = _find(client, note.id).json()

    assert len(body["card_ids"]) == 1 and body["emptied_fields"] == 0 and body["quoted_fields"] == 2


# --- ③ 카드 API ---


def _found_card(client: TestClient, db: Session, settings: Settings, sub: str) -> tuple[int, Note]:
    user_id = _login(client, db, settings, sub)
    note = _note(db, user_id)
    _use_mock(_reply(_draft(_chunk_ids(db, note))))
    return _find(client, note.id).json()["card_ids"][0], note


def test_list_counts_blanks_and_evidence_by_status_and_note(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    card_id, note = _found_card(client, db_session, test_settings, "list")

    candidates = client.get("/api/cards", params={"status": "candidate"}).json()
    saved = client.get("/api/cards").json()  # 기본은 저장한 카드
    by_note = client.get("/api/cards", params={"status": "candidate", "note_id": note.id}).json()
    other_note = client.get("/api/cards", params={"status": "candidate", "note_id": note.id + 1}).json()

    assert candidates["total"] == 1
    summary = candidates["cards"][0]
    assert (summary["id"], summary["note_title"], summary["blank_count"], summary["evidence_count"]) == (
        card_id,
        note.title,
        2,
        2,
    )
    assert summary["blank_slots"] == ["task", "result"]
    assert saved == {"total": 0, "cards": [], "note_searched": None}
    assert by_note["total"] == 1 and by_note["note_searched"] is True
    assert other_note == {"total": 0, "cards": [], "note_searched": False}
    assert client.get("/api/cards", params={"status": "done"}).status_code == 422


def test_detail_save_and_delete(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    card_id, note = _found_card(client, db_session, test_settings, "detail")

    detail = client.get(f"/api/cards/{card_id}").json()
    assert [item["slot"] for item in detail["fields"]] == list(CARD_SLOTS)
    situation = detail["fields"][0]
    assert note.content[situation["quote_start"] : situation["quote_end"]] == situation["quote"] == SITUATION_QUOTE
    assert (detail["blank_count"], detail["evidence_count"], detail["status"]) == (2, 2, CARD_STATUS_CANDIDATE)

    saved = client.post(f"/api/cards/{card_id}/save", json={"title": "  상품 목록   캐시 도입 "})
    assert saved.status_code == 200
    assert (saved.json()["title"], saved.json()["status"]) == ("상품 목록 캐시 도입", CARD_STATUS_SAVED)
    assert client.post(f"/api/cards/{card_id}/save", json={"title": "  "}).status_code == 422
    assert client.get("/api/cards").json()["total"] == 1

    assert client.delete(f"/api/cards/{card_id}").status_code == 204
    assert client.get(f"/api/cards/{card_id}").status_code == 404
    assert _count(db_session, CardField) == 0


def test_answer_fills_a_blank_and_remove_quote_turns_a_field_into_a_blank(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    card_id, _ = _found_card(client, db_session, test_settings, "answer")

    answered = client.put(f"/api/cards/{card_id}/fields/task", json={"answer": "  목록 응답을 1초 안으로 줄이는 일  "})
    assert answered.status_code == 200
    assert answered.json()["fields"][1]["answer"] == "목록 응답을 1초 안으로 줄이는 일"
    assert answered.json()["blank_count"] == 1

    # 인용 칸에 내 답 덧붙이기 — 인용은 그대로
    added = client.put(f"/api/cards/{card_id}/fields/situation", json={"answer": "점심 시간대였다"}).json()
    assert added["fields"][0]["quote"] == SITUATION_QUOTE and added["fields"][0]["answer"] == "점심 시간대였다"

    removed = client.put(f"/api/cards/{card_id}/fields/action", json={"remove_quote": True}).json()
    action = removed["fields"][2]
    assert (action["quote"], action["chunk_id"], action["quote_start"]) == (None, None, None)
    assert action["question"] == CARD_DEFAULT_QUESTIONS["action"]
    assert (removed["blank_count"], removed["evidence_count"]) == (2, 1)

    cleared = client.put(f"/api/cards/{card_id}/fields/task", json={"answer": "   "}).json()
    assert cleared["fields"][1]["answer"] is None and cleared["blank_count"] == 3

    too_long = client.put(f"/api/cards/{card_id}/fields/task", json={"answer": "가" * (CARD_MAX_ANSWER_CHARS + 1)})
    assert too_long.status_code == 422
    assert client.put(f"/api/cards/{card_id}/fields/summary", json={"answer": "x"}).status_code == 422
    # 본문 자체가 터무니없이 크면 서비스까지 가지 않고 422(R2)
    huge = client.put(f"/api/cards/{card_id}/fields/task", json={"answer": "가" * (CARD_MAX_ANSWER_CHARS * 5 + 1)})
    assert huge.status_code == 422 and isinstance(huge.json()["detail"], list)
    assert client.post(f"/api/cards/{card_id}/save", json={"title": "가" * (CARD_TITLE_MAX_CHARS * 10 + 1)}).status_code == 422


def test_other_users_cards_are_404_everywhere(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    card_id, note = _found_card(client, db_session, test_settings, "owner")
    _login(client, db_session, test_settings, "intruder")

    assert client.get(f"/api/cards/{card_id}").status_code == 404
    assert client.post(f"/api/cards/{card_id}/save", json={"title": "가져감"}).status_code == 404
    assert client.put(f"/api/cards/{card_id}/fields/task", json={"answer": "x"}).status_code == 404
    assert client.delete(f"/api/cards/{card_id}").status_code == 404
    assert client.get("/api/cards", params={"status": "candidate"}).json()["total"] == 0
    by_note = client.get("/api/cards", params={"status": "candidate", "note_id": note.id}).json()
    assert by_note == {"total": 0, "cards": [], "note_searched": False}
    assert client.get(f"/api/cards/{2**31}").status_code == 404
    assert db_session.get(Card, card_id) is not None


def test_title_and_answer_with_control_characters_are_422(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """NUL 문자는 PostgreSQL이 받지 않아 저장 때 500이 된다 — 서버가 먼저 422로 막는다(F-006 1차 리뷰 R2)."""
    card_id, _ = _found_card(client, db_session, test_settings, "nul")

    assert client.post(f"/api/cards/{card_id}/save", json={"title": "제목\u0000"}).status_code == 422
    assert client.put(f"/api/cards/{card_id}/fields/task", json={"answer": "a\u0000b"}).status_code == 422
    # 줄바꿈 · 탭은 답에 쓸 수 있다
    ok = client.put(f"/api/cards/{card_id}/fields/task", json={"answer": "첫 줄\n\t둘째 줄"})
    assert ok.status_code == 200 and ok.json()["fields"][1]["answer"] == "첫 줄\n\t둘째 줄"


def test_slot_names_in_the_api_match_config(db_session: Session) -> None:
    assert typing.get_args(Slot) == CARD_SLOTS
    # 서비스만 불러도 틀린 칸 이름은 422 문구(InvalidCardInput)
    with pytest.raises(InvalidCardInput):
        update_field(db_session, user_id=1, card_id=1, slot="summary", answer="x")


def test_cards_need_login(client: TestClient) -> None:
    assert client.get("/api/cards").status_code == 401
    assert client.post("/api/notes/1/cards/candidates").status_code == 401


# --- 동시 클릭 · 정리 경로 (문제 만들기와 같은 시험) ---

ON_POSTGRES = bool(os.getenv("TEST_DATABASE_URL", "").strip())


def _claims(db: Session) -> list[int]:
    db.expire_all()
    return sorted(db.scalars(select(NoteCardClaim.note_id)).all())


def _second_note(db: Session, user_id: int, tag: str) -> Note:
    content = PROJECT_NOTE + f"\n{tag}"
    return create_note_for_user(db, user_id=user_id, title=tag, content=content, chunks=split_markdown(content))


@pytest.mark.skipif(not ON_POSTGRES, reason="사용자 줄 잠금(FOR NO KEY UPDATE)은 PostgreSQL에서만 시험한다")
@pytest.mark.parametrize("same_note", [True, False])
def test_two_requests_at_the_same_time_only_one_claims(db_session: Session, same_note: bool) -> None:
    """같은 노트(유니크) · 다른 노트(사용자당 1개)를 동시에 선점해도 하나만 통과한다."""
    user_id = _user(db_session, f"race-{same_note}")
    first = _note(db_session, user_id)
    note_ids = [first.id, first.id if same_note else _second_note(db_session, user_id, "둘째").id]
    make_session = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt(note_id: int) -> None:
        with make_session() as session:
            barrier.wait()
            try:
                prepare_search(session, user_id=user_id, note_id=note_id)
                results.append("claimed")
            except (SearchInProgress, OtherAIWorkInProgress):
                results.append("busy")

    threads = [threading.Thread(target=attempt, args=(note_id,)) for note_id in note_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == ["busy", "claimed"]
    assert len(_claims(db_session)) == 1


class _Cancelled(BaseException):
    """Exception이 아닌 BaseException(요청 취소 흉내) — `except Exception`에 안 잡히는 경로를 확인한다."""


def test_cancel_like_base_exception_also_cleans_up(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """AI를 기다리다 BaseException으로 끝나도 사용량 1회 · 선점 해제. 엔드포인트 함수를 직접 부른다."""
    from app.api import cards as cards_api
    from app.db.models import User

    user_id = _user(db_session, "cancel")
    note = _note(db_session, user_id)

    def cancelled(*args: object, **kwargs: object) -> None:
        raise _Cancelled

    monkeypatch.setattr(cards_api.anyio.from_thread, "run", cancelled)
    user = db_session.get(User, user_id)

    with pytest.raises(_Cancelled):
        cards_api.find_card_candidates(note.id, current_user=user, db=db_session, client=MockLLMClient())

    assert _claims(db_session) == []
    assert db_session.scalars(select(AIUsageLog.outcome)).one() == "error"


def test_quiz_in_progress_blocks_card_search_and_card_search_blocks_quiz(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """사용자당 진행 중인 AI 작업은 기능을 가리지 않고 1개(Q-023, 사용자 확인 2026-11-11)."""
    user_id = _login(client, db_session, test_settings, "one-ai-job")
    note = _note(db_session, user_id)
    other = _second_note(db_session, user_id, "퀴즈용")
    db_session.add(NoteQuizClaim(user_id=user_id, note_id=other.id, claimed_at=datetime.now(timezone.utc)))
    db_session.commit()
    mock = _use_mock()

    response = _find(client, note.id)

    assert (response.status_code, response.json()["detail"]) == (409, api_errors.OTHER_AI_WORK_DETAIL)
    assert mock.calls == [] and _claim(db_session, note.id) is None

    # 반대로 카드 후보 찾기가 진행 중이면 문제 만들기 선점도 막힌다
    db_session.execute(delete(NoteQuizClaim))
    db_session.add(NoteCardClaim(user_id=user_id, note_id=note.id, claimed_at=datetime.now(timezone.utc)))
    db_session.commit()
    with pytest.raises(quiz_generation.OtherAIWorkInProgress):
        note_claim.claim_note(
            db_session, quiz_generation._CLAIM_RULES, user_id=user_id, note_id=other.id, at=datetime.now(timezone.utc)
        )


def test_lost_claim_saves_nothing_and_leaves_the_new_owner_alone(db_session: Session) -> None:
    """AI가 늦어 내 선점을 다른 요청이 가져갔으면(5분 넘음) 후보를 저장하지 않고, 새 주인의 선점도 건드리지 않는다(R2)."""
    user_id = _user(db_session, "lost-claim")
    note = _note(db_session, user_id)
    plan = prepare_search(db_session, user_id=user_id, note_id=note.id)
    taken_at = plan.claimed_at + timedelta(seconds=CARD_CLAIM_STALE_SECONDS + 1)
    db_session.execute(update(NoteCardClaim).where(NoteCardClaim.note_id == note.id).values(claimed_at=taken_at))
    db_session.commit()
    reply = asyncio.run(
        request_card_drafts(MockLLMClient([_reply(_draft(_chunk_ids(db_session, note)))]), plan.messages)
    )

    with pytest.raises(ClaimLost):
        save_search(db_session, plan, reply)

    assert _count(db_session, Card) == 0
    claim = _claim(db_session, note.id)
    assert claim is not None and claim.finished_at is None  # 새 주인의 선점은 그대로
    assert _as_utc(claim.claimed_at) == taken_at
    assert db_session.scalars(select(AIUsageLog.outcome)).one() == "save_failed"


def test_lost_claim_answers_500_with_the_save_failed_message(
    client: TestClient, db_session: Session, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API로도: 선점을 잃으면 후보를 저장하지 않고 500 '저장하지 못했어요'(F-006 2차 리뷰 R3)."""
    user_id = _login(client, db_session, test_settings, "lost-api")
    note = _note(db_session, user_id)
    _use_mock(_reply(_draft(_chunk_ids(db_session, note))))

    def lost(*args: object, **kwargs: object) -> None:
        raise ClaimLost

    monkeypatch.setattr(note_claim, "ensure_still_owned", lost)

    response = _find(client, note.id)

    assert (response.status_code, response.json()["detail"]) == (500, cards_api.SAVE_FAILED_DETAIL)
    assert _count(db_session, Card) == 0


def test_save_failure_records_usage_and_releases_the_claim(
    client: TestClient, db_session: Session, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AI는 불렀는데 저장이 실패하면 500 + 사용량(save_failed) 기록 + 선점 해제(다시 누를 수 있게)."""
    user_id = _login(client, db_session, test_settings, "save-fail")
    note = _note(db_session, user_id)
    _use_mock(_reply(_draft(_chunk_ids(db_session, note))))

    def broken(*args: object, **kwargs: object) -> Card:
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr("app.services.card_generation._card_rows", broken)

    response = _find(client, note.id)

    assert response.status_code == 500
    assert _claims(db_session) == []
    assert _count(db_session, Card) == 0
    assert db_session.scalars(select(AIUsageLog.outcome)).one() == "save_failed"


def test_abandon_still_releases_the_claim_when_logging_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = _user(db_session, "abandon")
    note = _note(db_session, user_id)
    plan = prepare_search(db_session, user_id=user_id, note_id=note.id)

    def failing_save(*args: object, **kwargs: object) -> int:
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr("app.services.card_generation.save_failed_search", failing_save)

    abandon_search(db_session, plan)  # 예외가 올라오지 않는다

    assert _claims(db_session) == []
