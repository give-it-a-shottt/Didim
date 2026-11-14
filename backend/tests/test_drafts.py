"""근거 달린 자소서 초안 (F-008) 테스트.

① 표 구조(버전 0008): 문항 · 공고를 지우면 초안 · 문장이 같이 지워지고 로그는 남는다, 카드를 지우면 근거 카드만 비고
   문장은 남는다('카드 없음'), 사용자를 지우면 모두 지워진다(D-004).
② 근거 검사(check_ai_sentences): 보낸 카드 안 · 칸에 글자 그대로 있는 인용만 근거로, 못 넘은 문장은 근거 없이 남김(D-003).
③ [초안 쓰기] API: 매칭 카드만 보냄(원칙 6 · D-004), 매칭 카드 0장이면 409(D-003 예외 7), 초안 있으면 409 · 덮어쓰기,
   AI 실패 시 이전 초안 유지, 선점(D-020), 하루 상한, 남의 공고 · 문항 404.
④ 다시 검사: 카드 칸 글이 바뀌거나 카드가 지워지면 '근거 없음'(AI 없음).
⑤ 고치기: 문장 단위(고침 · 되돌림 · 새 문장 · 지우기 · [카드 연결] · 근거 떼기), version 충돌 409, 완료 표시.
⑥ 문항 목록 저장(추가 · 수정 · 삭제 · 순서), 공고 상세의 근거 없는 문장 수.
"""

import asyncio
import json
import re
import typing
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import config
from app.api.drafts import get_draft_llm_client
from app.config import CARD_SLOTS, CARD_STATUS_CANDIDATE, CARD_STATUS_SAVED, DEFAULT_DAILY_LIMIT, DRAFT_MAX_AI_SENTENCES, SESSION_COOKIE_NAME, Settings
from app.db.models import (
    AIUsageLog,
    Application,
    ApplicationClaim,
    ApplicationQuestion,
    Card,
    CardField,
    Draft,
    DraftLog,
    DraftSentence,
    PostingRequirement,
    RequirementMatch,
)
from app.korea_time import now_utc
from app.llm import LLMRateLimited, LLMUsage, Message, MockLLMClient
from app.main import app
from app.services import draft_service
from app.services.application_service import ApplicationNotFound, QuestionInput, create_application
from app.services.auth_service import GoogleProfile, create_session_token, get_or_create_google_user
from app.services.draft_mock import mock_draft_responder
from app.services.draft_view import edited_percent
from app.services.draft_writing import (
    DROP_CARD_NOT_SENT,
    DROP_EMPTY_SENTENCE,
    DROP_NO_EVIDENCE,
    DraftSentenceIn,
    check_ai_sentences,
    request_draft,
)
from app.services.note_service import delete_user_account
from app.services.posting_checks import DROP_QUOTE_NOT_FOUND, DROP_QUOTE_TOO_SHORT, DROP_TOO_MANY, DROP_UNKNOWN_SLOT
from app.services.posting_matching import CardText
from app.services.usage_service import record_usage

ACTION_QUOTE = "로그인한 사용자는 Redis 리스트로 옮기고, 비로그인은 그대로 두었다."
RESULT_ANSWER = "상품 상세 페이지 이탈률이 30% 줄었다."


def _user(db: Session, name: str) -> int:
    return get_or_create_google_user(db, GoogleProfile(sub=name, email=f"{name}@example.com", name=name)).id


def _login(client: TestClient, db: Session, settings: Settings, sub: str) -> int:
    user_id = _user(db, sub)
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id, settings.session_secret))
    return user_id


def _application(db: Session, user_id: int, *, questions: int = 2) -> int:
    return create_application(
        db,
        user_id=user_id,
        company="누리랩",
        role="풀스택 개발자",
        deadline=None,
        url=None,
        posting_text="- Redis 캐시 운영 경험\n- React 화면 개발 경험",
        questions=[QuestionInput(text=f"{index + 1}번 문항을 적어 주세요.", char_limit=700) for index in range(questions)],
    )


def _question_ids(db: Session, application_id: int) -> list[int]:
    return list(
        db.scalars(
            select(ApplicationQuestion.id)
            .where(ApplicationQuestion.application_id == application_id)
            .order_by(ApplicationQuestion.position)
        ).all()
    )


def _card(db: Session, user_id: int, title: str = "Redis 재설계", *, status: str = CARD_STATUS_SAVED) -> Card:
    """행동 칸에 원문 인용, 결과 칸에 내 답을 넣은 카드."""
    card = Card(user_id=user_id, note_id=None, title=title, status=status)
    for slot in CARD_SLOTS:
        if slot == "action":
            card.fields.append(CardField(user_id=user_id, slot=slot, quote=ACTION_QUOTE, quote_start=0, quote_end=len(ACTION_QUOTE)))
        elif slot == "result":
            card.fields.append(CardField(user_id=user_id, slot=slot, answer=RESULT_ANSWER))
        else:
            card.fields.append(CardField(user_id=user_id, slot=slot, question="?"))
    db.add(card)
    db.commit()
    return card


def _match(db: Session, user_id: int, application_id: int, card_id: int, *, position: int = 0) -> None:
    """공고 분석 없이 역량 하나 + 매칭 하나를 넣고 matched_at을 적는다."""
    requirement = PostingRequirement(
        user_id=user_id, application_id=application_id, position=position, name=f"역량{position}", kind="required",
        quote="Redis 캐시 운영 경험", quote_start=2, quote_end=14,
    )
    db.add(requirement)
    db.flush()
    db.add(
        RequirementMatch(
            user_id=user_id, requirement_id=requirement.id, card_id=card_id, slot="action", quote=ACTION_QUOTE[:10],
            quote_source="quote", quote_start=0, quote_end=10, reason="이유",
        )
    )
    db.execute(update(Application).where(Application.id == application_id).values(matched_at=now_utc()))
    db.commit()


def _reply(*sentences: dict[str, object]) -> str:
    return json.dumps({"sentences": list(sentences)}, ensure_ascii=False)


def _good_reply(card_id: int) -> str:
    return _reply(
        {"text": "Accio 쇼핑몰에서 최근 본 상품 기능을 맡았습니다.", "card_id": None, "slot": None, "quote": None},
        {"text": "로그인한 사용자는 Redis 리스트로 옮겼습니다.", "card_id": card_id, "slot": "action", "quote": "로그인한 사용자는 Redis 리스트로 옮기고"},
        {"text": "그 결과 이탈률이 30% 줄었습니다.", "card_id": card_id, "slot": "result", "quote": "이탈률이 30% 줄었다"},
        {"text": "이 과정에서 팀원 5명을 이끌었습니다.", "card_id": card_id, "slot": "action", "quote": "팀원 5명을 이끌었다"},
    )


def _count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture()
def use_mock(client: TestClient) -> Generator[typing.Callable[[MockLLMClient], MockLLMClient], None, None]:
    def _use(mock: MockLLMClient) -> MockLLMClient:
        app.dependency_overrides[get_draft_llm_client] = lambda: mock
        return mock

    yield _use
    app.dependency_overrides.pop(get_draft_llm_client, None)


@pytest.fixture()
def ready(
    client: TestClient, db_session: Session, test_settings: Settings
) -> dict[str, int]:
    """로그인한 사용자 · 문항 2개짜리 공고 · 매칭된 저장 카드 1장."""
    user_id = _login(client, db_session, test_settings, "writer")
    application_id = _application(db_session, user_id)
    card = _card(db_session, user_id)
    _match(db_session, user_id, application_id, card.id)
    question_id = _question_ids(db_session, application_id)[0]
    return {"user_id": user_id, "application_id": application_id, "card_id": card.id, "question_id": question_id}


def _write(client: TestClient, ready: dict[str, int], *, overwrite: bool = False, question_id: int | None = None):  # noqa: ANN202
    qid = question_id if question_id is not None else ready["question_id"]
    return client.post(
        f"/api/applications/{ready['application_id']}/questions/{qid}/draft", json={"overwrite": overwrite}
    )


def _drafts(client: TestClient, ready: dict[str, int]) -> dict[str, typing.Any]:
    response = client.get(f"/api/applications/{ready['application_id']}/drafts")
    assert response.status_code == 200
    return response.json()


def _first_draft(client: TestClient, ready: dict[str, int]) -> dict[str, typing.Any]:
    return _drafts(client, ready)["questions"][0]["draft"]


# --- ① 표 구조 ---


def _saved_draft(db: Session, user_id: int, application_id: int, question_id: int, card_id: int) -> Draft:
    draft = Draft(user_id=user_id, application_id=application_id, question_id=question_id, ai_text="문장.", version=1)
    db.add(draft)
    db.flush()
    db.add(
        DraftSentence(
            user_id=user_id, draft_id=draft.id, position=0, text="문장.", origin="ai", original_text="문장.",
            card_id=card_id, slot="action", quote=ACTION_QUOTE, quote_source="quote", quote_start=0,
            quote_end=len(ACTION_QUOTE), evidence_origin="ai",
        )
    )
    db.add(
        DraftLog(
            user_id=user_id, application_id=application_id, question_id=question_id, cards_sent=1, sentences=1,
            supported=1, drop_reasons={}, chars=3, char_limit=None, outcome="ok",
        )
    )
    db.commit()
    return draft


def test_deleting_a_question_removes_its_draft_but_keeps_logs(db_session: Session) -> None:
    user_id = _user(db_session, "cascade-question")
    application_id = _application(db_session, user_id)
    card = _card(db_session, user_id)
    question_id = _question_ids(db_session, application_id)[0]
    _saved_draft(db_session, user_id, application_id, question_id, card.id)

    db_session.execute(delete(ApplicationQuestion).where(ApplicationQuestion.id == question_id))
    db_session.commit()
    assert _count(db_session, Draft) == 0
    assert _count(db_session, DraftSentence) == 0
    assert _count(db_session, DraftLog) == 1


def test_deleting_a_card_keeps_the_sentence_and_its_quote(db_session: Session) -> None:
    user_id = _user(db_session, "cascade-card")
    application_id = _application(db_session, user_id)
    card = _card(db_session, user_id)
    _saved_draft(db_session, user_id, application_id, _question_ids(db_session, application_id)[0], card.id)

    db_session.execute(delete(Card).where(Card.id == card.id))
    db_session.commit()
    sentence = db_session.scalars(select(DraftSentence)).one()
    assert sentence.card_id is None
    assert sentence.quote == ACTION_QUOTE


def test_deleting_the_application_or_user_removes_draft_rows(db_session: Session) -> None:
    user_id = _user(db_session, "cascade-user")
    application_id = _application(db_session, user_id)
    card = _card(db_session, user_id)
    _saved_draft(db_session, user_id, application_id, _question_ids(db_session, application_id)[0], card.id)

    db_session.execute(delete(Application).where(Application.id == application_id))
    db_session.commit()
    assert _count(db_session, Draft) == 0
    assert _count(db_session, DraftLog) == 1  # 공고를 지워도 평가 로그는 남는다

    delete_user_account(db_session, user_id=user_id)
    assert _count(db_session, DraftLog) == 0


# --- ② 근거 검사 ---


CARDS = {7: CardText(id=7, title="Redis", fields={"action": (ACTION_QUOTE, None), "result": (None, RESULT_ANSWER)})}


def test_check_keeps_evidence_only_when_the_quote_is_in_the_sent_card_field() -> None:
    result = check_ai_sentences(
        [
            DraftSentenceIn(text="근거 있음", card_id=7, slot="action", quote="Redis 리스트로 옮기고"),
            DraftSentenceIn(text="내 답 근거", card_id=7, slot="RESULT", quote="이탈률이 30% 줄었다"),
            DraftSentenceIn(text="지어냄", card_id=7, slot="action", quote="팀원 5명을 이끌었다"),
            DraftSentenceIn(text="남의 카드", card_id=99, slot="action", quote="Redis 리스트로 옮기고"),
            DraftSentenceIn(text="칸 틀림", card_id=7, slot="hobby", quote="Redis 리스트로 옮기고"),
            DraftSentenceIn(text="짧음", card_id=7, slot="action", quote="옮기고"),
            DraftSentenceIn(text="연결 문장"),
            DraftSentenceIn(text="   "),
        ],
        CARDS,
    )
    assert [item.text for item in result.sentences] == ["근거 있음", "내 답 근거", "지어냄", "남의 카드", "칸 틀림", "짧음", "연결 문장"]
    assert [item.supported for item in result.sentences] == [True, True, False, False, False, False, False]
    assert result.sentences[0].quote_source == "quote"
    assert result.sentences[1].quote_source == "answer"
    assert result.sentences[1].slot == "result"
    assert (result.sentences[0].quote_start, result.sentences[0].quote_end) == (ACTION_QUOTE.find("Redis 리스트로 옮기고"), ACTION_QUOTE.find("Redis 리스트로 옮기고") + len("Redis 리스트로 옮기고"))
    assert dict(result.drop_reasons) == {
        DROP_QUOTE_NOT_FOUND: 1,
        DROP_CARD_NOT_SENT: 1,
        DROP_UNKNOWN_SLOT: 1,
        DROP_QUOTE_TOO_SHORT: 1,
        DROP_NO_EVIDENCE: 1,
        DROP_EMPTY_SENTENCE: 1,
    }


def test_check_drops_sentences_over_the_limit() -> None:
    items = [DraftSentenceIn(text=f"문장 {index}") for index in range(DRAFT_MAX_AI_SENTENCES + 2)]
    result = check_ai_sentences(items, CARDS)
    assert len(result.sentences) == DRAFT_MAX_AI_SENTENCES
    assert result.drop_reasons[DROP_TOO_MANY] == 2


def test_edited_percent_compares_words() -> None:
    assert edited_percent("가 나 다 라", "가 나 다 라") == 0
    assert edited_percent("가 나 다 라", "마 바 사 아") == 100
    assert 0 < edited_percent("가 나 다 라", "가 나 다 마") < 100


# --- ③ [초안 쓰기] ---


def test_write_sends_only_matched_cards_and_saves_checked_sentences(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    _card(db_session, ready["user_id"], "매칭 안 된 카드")
    other = _user(db_session, "other-writer")
    _card(db_session, other, "남의 카드")
    mock = use_mock(MockLLMClient([_good_reply(ready["card_id"])]))

    response = _write(client, ready)
    assert response.status_code == 201
    body = response.json()
    assert body["written"] is True
    assert (body["sentences"], body["supported"], body["cards_sent"]) == (4, 2, 1)
    assert body["drop_reasons"] == {DROP_NO_EVIDENCE: 1, DROP_QUOTE_NOT_FOUND: 1}

    payload = json.loads(mock.calls[0][-1].content)
    assert [card["title"] for card in payload["cards"]] == ["Redis 재설계"]  # 매칭 안 된 카드 · 남의 카드는 안 보냄
    assert payload["question"] == "1번 문항을 적어 주세요."
    assert payload["target_chars"] == 700

    draft = _first_draft(client, ready)
    assert [item["evidence_status"] for item in draft["sentences"]] == ["none", "ok", "ok", "none"]
    assert draft["unsupported_count"] == 2
    assert draft["edited_percent"] == 0
    assert draft["sentences"][1]["evidence"]["card_title"] == "Redis 재설계"
    assert draft["sentences"][2]["evidence"]["quote_source"] == "answer"
    assert draft["chars"] == len(" ".join(item["text"] for item in draft["sentences"]))
    log = db_session.scalars(select(DraftLog)).one()
    assert (log.cards_sent, log.sentences, log.supported, log.outcome) == (1, 4, 2, "ok")
    assert _count(db_session, ApplicationClaim) == 0
    assert db_session.scalars(select(AIUsageLog.feature)).all() == ["draft_write"]


def test_write_without_matched_cards_is_blocked(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "no-cards")
    application_id = _application(db_session, user_id)
    question_id = _question_ids(db_session, application_id)[0]
    _card(db_session, user_id)  # 저장 카드는 있지만 이 공고에 매칭되지 않음
    mock = use_mock(MockLLMClient([]))
    url = f"/api/applications/{application_id}/questions/{question_id}/draft"

    response = client.post(url, json={})
    assert response.status_code == 409
    assert "공고 분석" in response.json()["detail"]  # 아직 매칭 안 함
    db_session.execute(update(Application).where(Application.id == application_id).values(matched_at=now_utc()))
    db_session.commit()
    response = client.post(url, json={})
    assert response.status_code == 409
    assert "매칭된 경험 카드가 없어요" in response.json()["detail"]
    assert mock.calls == []
    view = client.get(f"/api/applications/{application_id}/drafts").json()
    assert view["matched_card_ids"] == []
    assert view["analysis_done"] is True


def test_candidate_cards_are_not_sent(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "candidate")
    application_id = _application(db_session, user_id)
    card = _card(db_session, user_id, status=CARD_STATUS_CANDIDATE)
    _match(db_session, user_id, application_id, card.id)
    use_mock(MockLLMClient([]))
    response = client.post(f"/api/applications/{application_id}/questions/{_question_ids(db_session, application_id)[0]}/draft")
    assert response.status_code == 409


def test_existing_draft_needs_overwrite_and_ai_failure_keeps_it(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"]), LLMRateLimited("429"), _reply({"text": "새 초안 문장입니다."})]))
    assert _write(client, ready).status_code == 201
    before = _first_draft(client, ready)

    response = _write(client, ready)
    assert response.status_code == 409
    assert "이미 초안" in response.json()["detail"]

    assert _write(client, ready, overwrite=True).status_code == 503  # AI 실패 → 이전 초안 그대로
    assert _first_draft(client, ready)["sentences"] == before["sentences"]
    assert _count(db_session, ApplicationClaim) == 0

    assert _write(client, ready, overwrite=True).status_code == 201
    after = _first_draft(client, ready)
    assert [item["text"] for item in after["sentences"]] == ["새 초안 문장입니다."]
    assert after["version"] == before["version"] + 1  # 열려 있던 탭의 저장이 409가 되게
    assert _count(db_session, Draft) == 1


def test_empty_ai_reply_keeps_the_previous_draft(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"]), _reply({"text": "  "})]))
    _write(client, ready)
    response = _write(client, ready, overwrite=True)
    assert response.status_code == 201
    assert response.json()["written"] is False
    assert len(_first_draft(client, ready)["sentences"]) == 4
    assert db_session.scalars(select(DraftLog.outcome).order_by(DraftLog.id)).all() == ["ok", "no_sentences"]


def test_write_is_blocked_while_the_application_is_claimed(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    db_session.add(ApplicationClaim(user_id=ready["user_id"], application_id=ready["application_id"], claimed_at=now_utc()))
    db_session.commit()
    mock = use_mock(MockLLMClient([]))
    response = _write(client, ready)
    assert response.status_code == 409
    assert "진행 중" in response.json()["detail"]
    assert mock.calls == []


def test_write_respects_the_daily_limit(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    record_usage(db_session, user_id=ready["user_id"], feature="quiz_generate", usage=LLMUsage(calls=DEFAULT_DAILY_LIMIT), outcome="ok")
    mock = use_mock(MockLLMClient([]))
    assert _write(client, ready).status_code == 429
    assert mock.calls == []
    assert _count(db_session, ApplicationClaim) == 0


def test_other_users_application_and_question_are_not_found(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([]))
    other = _user(db_session, "other-owner")
    other_application = _application(db_session, other)
    other_question = _question_ids(db_session, other_application)[0]
    assert client.get(f"/api/applications/{other_application}/drafts").status_code == 404
    assert client.post(f"/api/applications/{other_application}/questions/{other_question}/draft").status_code == 404
    # 내 공고 + 남의 문항 번호
    assert _write(client, ready, question_id=other_question).status_code == 404
    assert client.put(f"/api/applications/{other_application}/questions", json={"questions": []}).status_code == 404


def test_mock_responder_writes_one_supported_and_one_unsupported_sentence(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient(responder=mock_draft_responder))
    assert _write(client, ready).status_code == 201
    statuses = [item["evidence_status"] for item in _first_draft(client, ready)["sentences"]]
    assert statuses == ["ok", "none"]


# --- ④ 다시 검사 ---


def test_recheck_marks_changed_and_deleted_cards(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)

    db_session.execute(
        update(CardField).where(CardField.card_id == ready["card_id"], CardField.slot == "result").values(answer="다른 답")
    )
    db_session.commit()
    assert [item["evidence_status"] for item in _first_draft(client, ready)["sentences"]] == ["none", "ok", "changed", "none"]

    db_session.execute(delete(Card).where(Card.id == ready["card_id"]))
    db_session.commit()
    draft = _first_draft(client, ready)
    assert [item["evidence_status"] for item in draft["sentences"]] == ["none", "card_gone", "card_gone", "none"]
    assert draft["sentences"][1]["evidence"]["card_id"] is None
    assert draft["unsupported_count"] == 4
    detail = client.get(f"/api/applications/{ready['application_id']}").json()
    assert detail["unsupported_sentence_count"] == 4


# --- ⑤ 고치기 · 완료 ---


def _put(client: TestClient, draft: dict[str, typing.Any], sentences: list[dict[str, object]]):  # noqa: ANN202
    return client.put(f"/api/drafts/{draft['id']}", json={"version": draft["version"], "sentences": sentences})


def test_sentence_edits_keep_evidence_and_track_origin(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    draft = _first_draft(client, ready)
    first, second, third, _fourth = draft["sentences"]
    client.patch(f"/api/drafts/{draft['id']}", json={"completed": True})

    response = _put(
        client,
        draft,
        [
            {"id": second["id"], "text": "  로그인 사용자는   Redis로 옮겼습니다. "},  # 고침 → 근거 유지 · '내가 고침'
            {"text": "사이에 넣은 내 문장입니다."},  # 새 문장 → 근거 없음
            {"id": third["id"], "text": third["text"]},  # 그대로
            {"id": first["id"], "text": first["text"]},  # 순서만 바뀜 · 넷째 문장은 지움
        ],
    )
    assert response.status_code == 200
    saved = response.json()
    assert [item["text"] for item in saved["sentences"]] == [
        "로그인 사용자는 Redis로 옮겼습니다.", "사이에 넣은 내 문장입니다.", third["text"], first["text"],
    ]
    assert [item["origin"] for item in saved["sentences"]] == ["edited", "user", "ai", "ai"]
    assert [item["evidence_status"] for item in saved["sentences"]] == ["ok", "none", "ok", "none"]
    assert saved["sentences"][0]["original_text"] == second["text"]
    assert saved["version"] == draft["version"] + 1
    assert saved["completed_at"] is None  # 고치면 다시 '작성 중'
    assert saved["edited_percent"] > 0

    # 원래 문장으로 되돌리면 다시 ai
    back = _put(client, saved, [{"id": saved["sentences"][0]["id"], "text": second["text"]}]).json()
    assert back["sentences"][0]["origin"] == "ai"


def test_version_conflict_and_bad_input_are_rejected(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    draft = _first_draft(client, ready)
    sentence_id = draft["sentences"][0]["id"]
    assert _put(client, draft, [{"id": sentence_id, "text": "첫 탭"}]).status_code == 200
    stale = _put(client, draft, [{"id": sentence_id, "text": "둘째 탭"}])  # 옛 version
    assert stale.status_code == 409

    fresh = _first_draft(client, ready)
    assert _put(client, fresh, [{"id": fresh["sentences"][0]["id"], "text": "   "}]).status_code == 422
    assert _put(client, fresh, []).status_code == 422
    assert _put(client, fresh, [{"id": 999_999, "text": "없는 문장"}]).status_code == 422
    same = fresh["sentences"][0]["id"]
    assert _put(client, fresh, [{"id": same, "text": "a"}, {"id": same, "text": "b"}]).status_code == 422
    assert _put(client, fresh, [{"text": "x" * 501}]).status_code == 422
    assert _first_draft(client, ready)["version"] == fresh["version"]  # 거절된 저장은 아무것도 바꾸지 않음


def test_card_link_attaches_a_whole_field_from_my_saved_cards(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    draft = _first_draft(client, ready)
    unmatched = _card(db_session, ready["user_id"], "매칭 안 된 내 카드")
    other_card = _card(db_session, _user(db_session, "other-linker"), "남의 카드")
    candidate = _card(db_session, ready["user_id"], "후보 카드", status=CARD_STATUS_CANDIDATE)
    first = draft["sentences"][0]

    def link(card_id: int, slot: str = "result", source: str = "answer"):  # noqa: ANN202
        current = _first_draft(client, ready)
        return _put(client, current, [{"id": current["sentences"][0]["id"], "text": first["text"], "link": {"card_id": card_id, "slot": slot, "quote_source": source}}])

    assert link(other_card.id).status_code == 422  # 남의 카드(D-004)
    assert link(candidate.id).status_code == 422  # 저장 전 후보
    assert link(unmatched.id, "situation", "quote").status_code == 422  # 빈 칸
    assert link(unmatched.id, "hobby").status_code == 422

    response = link(unmatched.id)  # 매칭 안 된 카드도 내 저장 카드면 연결할 수 있다
    assert response.status_code == 200
    linked = response.json()["sentences"][0]
    assert linked["evidence_status"] == "ok"
    assert linked["evidence"] == {
        "card_id": unmatched.id, "card_title": "매칭 안 된 내 카드", "note_title": None, "slot": "result",
        "quote": RESULT_ANSWER, "quote_source": "answer", "added_by": "user",
    }
    assert linked["origin"] == "ai"  # 문장 글은 그대로

    current = _first_draft(client, ready)
    unlinked = _put(client, current, [{"id": current["sentences"][0]["id"], "text": first["text"], "unlink": True}]).json()
    assert unlinked["sentences"][0]["evidence"] is None
    assert unlinked["sentences"][0]["evidence_status"] == "none"
    row = db_session.scalars(select(DraftSentence)).one()
    assert (row.card_id, row.quote, row.evidence_origin) == (None, None, None)


def test_complete_marks_and_clears(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    draft = _first_draft(client, ready)
    done = client.patch(f"/api/drafts/{draft['id']}", json={"completed": True}).json()
    assert done["completed_at"] is not None
    assert done["version"] == draft["version"]  # 내용이 바뀌지 않으면 version은 그대로
    assert client.patch(f"/api/drafts/{draft['id']}", json={"completed": False}).json()["completed_at"] is None


def test_other_users_draft_is_not_found(
    client: TestClient, db_session: Session, test_settings: Settings, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    draft = _first_draft(client, ready)
    _login(client, db_session, test_settings, "intruder")
    assert _put(client, draft, [{"id": draft["sentences"][0]["id"], "text": "남이 고침"}]).status_code == 404
    assert client.patch(f"/api/drafts/{draft['id']}", json={"completed": True}).status_code == 404
    assert client.put("/api/drafts/0", json={"version": 1, "sentences": []}).status_code == 404


# --- ⑥ 문항 목록 · 공고 상세 ---


def test_replace_questions_adds_edits_reorders_and_deletes_with_drafts(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    first_id, second_id = _question_ids(db_session, ready["application_id"])
    url = f"/api/applications/{ready['application_id']}/questions"

    response = client.put(
        url,
        json={"questions": [
            {"id": second_id, "text": " 2번 문항(고침) ", "char_limit": 500},
            {"text": "새 문항", "char_limit": None},
            {"id": first_id, "text": "1번 문항을 적어 주세요.", "char_limit": 700},
        ]},
    )
    assert response.status_code == 200
    questions = response.json()["questions"]
    assert [(item["id"] == second_id, item["text"], item["char_limit"]) for item in questions[:1]] == [(True, "2번 문항(고침)", 500)]
    assert [item["text"] for item in questions] == ["2번 문항(고침)", "새 문항", "1번 문항을 적어 주세요."]
    assert questions[2]["draft"] is not None  # 순서만 바뀐 문항의 초안은 그대로

    assert client.put(url, json={"questions": [{"id": first_id, "text": "  "}]}).status_code == 422
    assert client.put(url, json={"questions": [{"id": 999_999, "text": "없는 문항"}]}).status_code == 409
    assert _count(db_session, Draft) == 1  # 거절된 저장은 아무것도 지우지 않음

    new_id = questions[1]["id"]
    body = {"questions": [{"id": second_id, "text": "2번 문항(고침)", "char_limit": 500}], "removed_ids": [first_id, new_id]}
    response = client.put(url, json=body)
    assert response.status_code == 200
    assert _count(db_session, Draft) == 0  # 1번 문항을 지우면 초안도 같이
    assert _count(db_session, DraftSentence) == 0


def test_application_detail_counts_unsupported_sentences(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    assert client.get(f"/api/applications/{ready['application_id']}").json()["unsupported_sentence_count"] == 0
    use_mock(MockLLMClient([_good_reply(ready["card_id"]), _good_reply(ready["card_id"])]))
    _write(client, ready)
    _write(client, ready, question_id=_question_ids(db_session, ready["application_id"])[1])
    assert client.get(f"/api/applications/{ready['application_id']}").json()["unsupported_sentence_count"] == 4


# --- ⑦ 실패 경로 · 동시 저장 · 번호 범위 (1차 리뷰 R2 · R3) ---


def test_ai_failures_keep_logs_usage_and_release_the_claim(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([LLMRateLimited("429")], default_reply="형식이 아닌 답"))
    assert _write(client, ready).status_code == 503
    response = _write(client, ready)  # 다음 답은 JSON이 아님 → 다시 요청해도 형식 오류
    assert response.status_code == 502
    assert "형식" in response.json()["detail"]
    assert db_session.scalars(select(DraftLog.outcome).order_by(DraftLog.id)).all() == ["rate_limited", "invalid_output"]
    assert db_session.scalars(select(AIUsageLog.outcome).order_by(AIUsageLog.id)).all() == ["rate_limited", "invalid_output"]
    assert _count(db_session, ApplicationClaim) == 0
    assert _count(db_session, Draft) == 0


def test_save_failure_is_500_counts_usage_and_keeps_the_previous_draft(
    client: TestClient,
    db_session: Session,
    ready: dict[str, int],
    use_mock: typing.Callable[[MockLLMClient], MockLLMClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"]), _reply({"text": "새 문장입니다."})]))
    _write(client, ready)
    before = _first_draft(client, ready)

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(draft_service, "_replace_draft", broken)
    response = _write(client, ready, overwrite=True)
    assert response.status_code == 500
    assert "이전 초안은 그대로" in response.json()["detail"]
    assert _first_draft(client, ready)["sentences"] == before["sentences"]
    assert db_session.scalars(select(AIUsageLog.outcome).order_by(AIUsageLog.id)).all() == ["ok", "save_failed"]
    assert _count(db_session, ApplicationClaim) == 0


def test_abandon_counts_one_call_and_releases_the_claim(db_session: Session) -> None:
    user_id = _user(db_session, "abandon")
    application_id = _application(db_session, user_id)
    card = _card(db_session, user_id)
    _match(db_session, user_id, application_id, card.id)
    plan = draft_service.prepare_draft(
        db_session, user_id=user_id, application_id=application_id,
        question_id=_question_ids(db_session, application_id)[0], overwrite=False,
    )
    assert _count(db_session, ApplicationClaim) == 1
    draft_service.abandon(db_session, plan)
    assert _count(db_session, ApplicationClaim) == 0
    usage = db_session.scalars(select(AIUsageLog)).one()
    assert (usage.calls, usage.outcome) == (1, "error")


def test_other_ai_work_blocks_writing(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    other_application = _application(db_session, ready["user_id"])
    db_session.add(ApplicationClaim(user_id=ready["user_id"], application_id=other_application, claimed_at=now_utc()))
    db_session.commit()
    mock = use_mock(MockLLMClient([]))
    response = _write(client, ready)
    assert response.status_code == 409
    assert "다른 AI 작업" in response.json()["detail"]
    assert mock.calls == []


def test_concurrent_save_with_the_same_version_is_409_not_500(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    """두 탭이 같은 version을 읽고 동시에 저장: 앞 요청이 version을 올린 뒤 뒤 요청이 오면 조건부 갱신이 0줄 → 409."""
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    draft = _first_draft(client, ready)
    # 이 세션은 version 1인 초안을 읽어 둔 상태(앞 요청이 아직 비교를 통과하기 전과 같음)
    stale = db_session.scalars(select(Draft)).one()
    assert stale.version == draft["version"]
    with Session(bind=db_session.get_bind()) as other:  # 다른 탭이 먼저 저장
        other.execute(update(Draft).where(Draft.id == stale.id).values(version=stale.version + 1))
        other.commit()
    with pytest.raises(draft_service.DraftConflict):
        draft_service.update_draft(
            db_session, user_id=ready["user_id"], draft_id=stale.id, version=draft["version"],
            sentences=[draft_service.SentenceEdit(id=draft["sentences"][0]["id"], text="뒤에 온 저장")],
        )
    db_session.expire_all()
    assert db_session.scalars(select(DraftSentence.text).order_by(DraftSentence.position)).first() == draft["sentences"][0]["text"]


def test_ids_beyond_the_db_range_are_rejected_before_the_db(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    draft = _first_draft(client, ready)
    huge = 2**31
    first = draft["sentences"][0]
    link = {"id": first["id"], "text": first["text"], "link": {"card_id": huge, "slot": "action", "quote_source": "quote"}}
    assert _put(client, draft, [link]).status_code == 422
    assert _put(client, draft, [{"id": huge, "text": "큰 번호"}]).status_code == 422
    assert client.put(f"/api/drafts/{draft['id']}", json={"version": huge, "sentences": [{"text": "a"}]}).status_code == 422
    url = f"/api/applications/{ready['application_id']}/questions"
    assert client.put(url, json={"questions": [{"id": huge, "text": "큰 번호"}]}).status_code == 422


def test_edited_percent_uses_a_fast_estimate_for_very_long_text() -> None:
    long_ai = " ".join(f"낱말{index}" for index in range(600))
    long_now = " ".join(f"낱말{index}" for index in range(300)) + " " + " ".join(f"새말{index}" for index in range(300))
    assert 0 < edited_percent(long_ai, long_now) <= 100


# --- ⑧ 2차 리뷰 R2 · R3: 문항 '먼저 바뀜' · AI 중 삭제 · 엔드포인트 abandon · 입력 422 · 401 ---


def test_stale_question_list_is_409_and_deletes_nothing(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    """옛 목록을 가진 탭: 다른 탭이 넣은 문항을 모르고 저장하면 409 — 그 문항 · 초안을 지우지 않는다."""
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    first_id, second_id = _question_ids(db_session, ready["application_id"])
    url = f"/api/applications/{ready['application_id']}/questions"
    stale = [{"id": first_id, "text": "1번", "char_limit": 700}, {"id": second_id, "text": "2번", "char_limit": 700}]
    # 다른 탭이 문항을 하나 더 넣고 그 문항에 초안을 씀
    added = client.put(url, json={"questions": [*stale, {"text": "다른 탭 문항"}]}).json()["questions"][2]["id"]
    _write(client, ready, question_id=added)
    response = client.put(url, json={"questions": stale})  # 옛 목록 그대로 저장
    assert response.status_code == 409
    assert "먼저 바뀌었어요" in response.json()["detail"]
    assert added in _question_ids(db_session, ready["application_id"])
    assert _count(db_session, Draft) == 1
    # 지울 문항으로 같이 보낸 번호가 이미 없으면(다른 탭이 지움) 역시 409
    assert client.put(url, json={"questions": stale, "removed_ids": [added, 999_999]}).status_code == 409
    # 같은 번호를 남기면서 지우면 422
    assert client.put(url, json={"questions": stale, "removed_ids": [first_id, added]}).status_code == 422


def test_question_inputs_out_of_range_are_422(client: TestClient, db_session: Session, ready: dict[str, int]) -> None:
    url = f"/api/applications/{ready['application_id']}/questions"
    first_id, second_id = _question_ids(db_session, ready["application_id"])
    keep = [{"id": first_id, "text": "1번"}, {"id": second_id, "text": "2번"}]
    assert client.put(url, json={"questions": [*keep, {"text": "글자 수 0", "char_limit": 0}]}).status_code == 422
    assert client.put(url, json={"questions": [*keep, {"text": "제어\x00문자"}]}).status_code == 422
    many = [*keep, *({"text": f"문항 {index}"} for index in range(9))]
    assert client.put(url, json={"questions": many}).status_code == 422  # 11개
    assert len(_question_ids(db_session, ready["application_id"])) == 2


def test_sentence_with_control_characters_is_422(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    draft = _first_draft(client, ready)
    assert _put(client, draft, [{"id": draft["sentences"][0]["id"], "text": "제어\x00문자"}]).status_code == 422


def test_question_or_application_deleted_while_ai_writes(db_session: Session) -> None:
    """AI를 부르는 동안 문항 · 공고가 지워지면 저장하지 않고 404 예외 — 선점은 풀리고 사용량은 save_failed로 남는다."""
    user_id = _user(db_session, "deleted-midway")
    application_id = _application(db_session, user_id)
    card = _card(db_session, user_id)
    _match(db_session, user_id, application_id, card.id)
    question_id = _question_ids(db_session, application_id)[0]
    reply = asyncio.run(request_draft(MockLLMClient([_good_reply(card.id)]), [Message("user", "{}")]))

    plan = draft_service.prepare_draft(db_session, user_id=user_id, application_id=application_id, question_id=question_id, overwrite=False)
    db_session.execute(delete(ApplicationQuestion).where(ApplicationQuestion.id == question_id))
    db_session.commit()
    with pytest.raises(draft_service.QuestionNotFound):
        draft_service.save_draft(db_session, plan, reply)
    assert _count(db_session, ApplicationClaim) == 0

    other_question = _question_ids(db_session, application_id)[0]
    plan = draft_service.prepare_draft(db_session, user_id=user_id, application_id=application_id, question_id=other_question, overwrite=False)
    db_session.execute(delete(Application).where(Application.id == application_id))
    db_session.commit()
    with pytest.raises(ApplicationNotFound):
        draft_service.save_draft(db_session, plan, reply)
    assert _count(db_session, Draft) == 0
    assert db_session.scalars(select(AIUsageLog.outcome)).all() == ["save_failed", "save_failed"]


def test_unexpected_error_during_ai_call_releases_the_claim(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    """엔드포인트에서 AI 호출이 LLMError가 아닌 예외로 끝나면 abandon — 선점을 풀고 사용량 1회를 남긴다."""
    use_mock(MockLLMClient([RuntimeError("boom")]))
    with pytest.raises(RuntimeError):
        _write(client, ready)
    assert _count(db_session, ApplicationClaim) == 0
    usage = db_session.scalars(select(AIUsageLog)).one()
    assert (usage.calls, usage.outcome) == (1, "error")


def test_draft_routes_need_login(client: TestClient, db_session: Session, ready: dict[str, int]) -> None:
    client.cookies.clear()
    app_id, question_id = ready["application_id"], ready["question_id"]
    assert client.get(f"/api/applications/{app_id}/drafts").status_code == 401
    assert client.post(f"/api/applications/{app_id}/questions/{question_id}/draft").status_code == 401
    assert client.put(f"/api/applications/{app_id}/questions", json={"questions": []}).status_code == 401
    assert client.put("/api/drafts/1", json={"version": 1, "sentences": [{"text": "a"}]}).status_code == 401
    assert client.patch("/api/drafts/1", json={"completed": True}).status_code == 401


def test_frontend_draft_constants_match_the_server() -> None:
    """화면 안내 문구가 쓰는 상한(frontend/src/lib/drafts.ts)이 서버 값(config.py)과 같은지 — 한쪽만 바뀌지 않게(3차 리뷰 R1)."""
    source = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "drafts.ts"
    if not source.exists():
        pytest.skip("프론트 폴더가 없는 환경")
    text = source.read_text(encoding="utf-8")
    for name, value in {
        "DRAFT_MAX_CARDS_SENT": config.DRAFT_MAX_CARDS_SENT,
        "DRAFT_SENTENCE_MAX_CHARS": config.DRAFT_SENTENCE_MAX_CHARS,
        "DRAFT_DEFAULT_TARGET_CHARS": config.DRAFT_DEFAULT_TARGET_CHARS,
    }.items():
        match = re.search(rf"export const {name} = ([\d_]+);", text)
        assert match is not None, name
        assert int(match.group(1).replace("_", "")) == value, name


def test_complete_after_the_draft_was_replaced_is_not_found(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    """[이 문항 완료]를 누르는 사이 다른 탭의 [다시 쓰기]가 초안을 지웠으면 500(StaleDataError)이 아니라 없는 초안(3차 리뷰 R2)."""
    use_mock(MockLLMClient([_good_reply(ready["card_id"])]))
    _write(client, ready)
    stale = db_session.scalars(select(Draft)).one()  # 이 세션은 지워지기 전 초안을 읽어 둠
    with Session(bind=db_session.get_bind()) as other:
        other.execute(delete(Draft).where(Draft.id == stale.id))
        other.commit()
    with pytest.raises(draft_service.DraftNotFound):
        draft_service.set_draft_completed(db_session, user_id=ready["user_id"], draft_id=stale.id, completed=True)
