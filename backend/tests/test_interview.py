"""면접 연습 (F-009) 테스트.

① 표 구조(버전 0009): 카드를 지우면 질문 · 선점이 같이 지워지고 로그는 남는다, 사용자를 지우면 모두 지워진다(D-004).
② 근거 검사(check_interview_questions): 보낸 칸 · 칸 글에 글자 그대로 있는 인용만 남기고 나머지는 버림(D-003, 완료 기준 1).
③ [면접 질문 만들기] API: 그 카드의 글 있는 칸만 보냄(원칙 6), 저장 카드만 · 카드당 한 번 · 빈칸만이면 409, 선점(D-020),
   하루 상한, AI 실패 시 로그 · 사용량 · 선점 해제, 남은 질문 0개면 저장 안 함(다시 누를 수 있음), 남의 카드 404.
④ 다시 검사: 카드 칸 글이 바뀌면 '근거가 바뀜'(AI 없음, 사용자 확인 2026-11-15). 카드 상세 응답에 질문.
⑤ 메모: 저장 · 비우기('답하지 않음'), 길이 · 제어 문자 422, 남의 질문 404.
⑥ [면접 연습] 탭: 매칭된 저장 카드별 질문(카드는 한 번, 역량은 태그), 질문 없는 카드도 보임, 답한 수.
⑦ 동시 클릭 · 실패 경로 · 같은 글 질문 합치기: 선점 뒤 다시 확인(409) · 트랜잭션을 닫고 AI로 · 형식 오류 502 · 저장 실패 500 ·
   선점을 잃은 저장 · AI 중 카드 삭제 404 · 예상 못 한 오류, 합칠 때 답한 질문 우선 · 합쳐진 카드는 '질문 없는 카드'가 아님.
"""

import asyncio
import json
import typing
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.api.interview import get_interview_llm_client
from app.api.schemas import RAW_INPUT_SLACK
from app.config import (
    CARD_SLOTS,
    CARD_STATUS_CANDIDATE,
    CARD_STATUS_SAVED,
    INTERVIEW_MAX_QUESTIONS,
    INTERVIEW_MEMO_MAX_CHARS,
    SESSION_COOKIE_NAME,
    Settings,
)
from app.db.models import (
    AIUsageLog,
    Application,
    Card,
    CardField,
    CardInterviewClaim,
    InterviewLog,
    InterviewQuestion,
    PostingRequirement,
    RequirementMatch,
    User,
)
from app.korea_time import now_utc
from app.llm import LLMRateLimited, LLMUsage, MockLLMClient
from app.main import app
from app.services import interview_service, note_claim
from app.services.application_service import QuestionInput, create_application
from app.services.auth_service import (
    GoogleProfile,
    create_session_token,
    get_or_create_google_user,
)
from app.services.card_service import CardNotFound
from app.services.interview_mock import mock_interview_responder
from app.services.interview_service import (
    InterviewPlan,
    abandon,
    prepare_interview,
    save_interview,
)
from app.services.interview_writing import (
    DROP_EMPTY_QUESTION,
    InterviewQuestionIn,
    build_interview_messages,
    check_interview_questions,
    request_interview_questions,
)
from app.services.note_claim import ClaimLost
from app.services.note_service import delete_user_account
from app.services.posting_checks import (
    DROP_QUOTE_NOT_FOUND,
    DROP_QUOTE_TOO_SHORT,
    DROP_TOO_MANY,
    DROP_UNKNOWN_SLOT,
)
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


def _card(db: Session, user_id: int, title: str = "Redis 재설계", *, status: str = CARD_STATUS_SAVED, blank: bool = False) -> Card:
    """행동 칸에 원문 인용, 결과 칸에 내 답, 나머지는 빈칸. blank=True면 모든 칸이 빈칸."""
    card = Card(user_id=user_id, note_id=None, title=title, status=status)
    for slot in CARD_SLOTS:
        if slot == "action" and not blank:
            card.fields.append(CardField(user_id=user_id, slot=slot, quote=ACTION_QUOTE, quote_start=0, quote_end=len(ACTION_QUOTE)))
        elif slot == "result" and not blank:
            card.fields.append(CardField(user_id=user_id, slot=slot, answer=RESULT_ANSWER))
        else:
            card.fields.append(CardField(user_id=user_id, slot=slot, question="?"))
    db.add(card)
    db.commit()
    return card


def _reply(*questions: dict[str, str]) -> str:
    return json.dumps({"questions": list(questions)}, ensure_ascii=False)


GOOD_REPLY = _reply(
    {"slot": "result", "question": "이탈률은 어떻게 쟀나요?", "quote": "이탈률이 30% 줄었다"},
    {"slot": "action", "question": "왜 로그인 사용자만 옮겼나요?", "quote": "로그인한 사용자는 Redis 리스트로 옮기고"},
    {"slot": "situation", "question": "처음 상황은 어땠나요?", "quote": "상황 글"},  # 빈칸 → 버림
    {"slot": "action", "question": "팀원 5명과 어떻게 나눴나요?", "quote": "팀원 5명과 나눴다"},  # 지어낸 인용 → 버림
)


def _count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


UseMock = typing.Callable[[MockLLMClient], MockLLMClient]  # use_mock 픽스처 — 가짜 AI를 끼워 넣는 함수


@pytest.fixture()
def use_mock(client: TestClient) -> Generator[UseMock]:
    def _use(mock: MockLLMClient) -> MockLLMClient:
        app.dependency_overrides[get_interview_llm_client] = lambda: mock
        return mock

    yield _use
    app.dependency_overrides.pop(get_interview_llm_client, None)


@pytest.fixture()
def ready(client: TestClient, db_session: Session, test_settings: Settings) -> dict[str, int]:
    user_id = _login(client, db_session, test_settings, "interviewer")
    card = _card(db_session, user_id)
    return {"user_id": user_id, "card_id": card.id}


def _write(client: TestClient, card_id: int):  # noqa: ANN202
    return client.post(f"/api/cards/{card_id}/interview-questions")


def _saved_question(db: Session, user_id: int, card_id: int, *, position: int = 0, slot: str = "action", quote: str = ACTION_QUOTE[:10]) -> InterviewQuestion:
    row = InterviewQuestion(
        user_id=user_id, card_id=card_id, position=position, slot=slot, question=f"질문{position}?", quote=quote,
        quote_source="quote" if slot == "action" else "answer", quote_start=0, quote_end=len(quote),
    )
    db.add(row)
    db.commit()
    return row


# --- ① 표 구조 ---


def test_deleting_a_card_removes_its_questions_and_claim_but_keeps_logs(db_session: Session) -> None:
    user_id = _user(db_session, "cascade-card")
    card = _card(db_session, user_id)
    _saved_question(db_session, user_id, card.id)
    db_session.add(CardInterviewClaim(user_id=user_id, card_id=card.id, claimed_at=now_utc()))
    db_session.add(InterviewLog(user_id=user_id, card_id=card.id, fields_sent=2, questions=1, kept=1, drop_reasons={}, outcome="ok"))
    db_session.commit()

    db_session.execute(delete(Card).where(Card.id == card.id))
    db_session.commit()
    assert (_count(db_session, InterviewQuestion), _count(db_session, CardInterviewClaim), _count(db_session, InterviewLog)) == (0, 0, 1)


def test_deleting_the_user_removes_interview_rows(db_session: Session) -> None:
    user_id = _user(db_session, "cascade-user")
    card = _card(db_session, user_id)
    _saved_question(db_session, user_id, card.id)
    db_session.add(InterviewLog(user_id=user_id, card_id=card.id, fields_sent=2, questions=1, kept=1, drop_reasons={}, outcome="ok"))
    db_session.commit()
    delete_user_account(db_session, user_id=user_id)
    assert (_count(db_session, InterviewQuestion), _count(db_session, InterviewLog)) == (0, 0)


def test_interview_claims_count_as_ai_work() -> None:
    assert note_claim.INTERVIEW_CLAIMS in note_claim.ALL_TABLES


# --- ② 근거 검사 ---


def _card_text() -> CardText:
    return CardText(id=7, title="Redis", fields={
        "situation": (None, None), "task": (None, "   "), "action": (ACTION_QUOTE, None), "result": (None, RESULT_ANSWER),
    })


def test_messages_send_only_slots_with_text() -> None:
    messages, sent = build_interview_messages(_card_text())
    payload = json.loads(messages[1].content)
    assert sent.slots == ("action", "result")
    assert payload == {"card_title": "Redis", "fields": [{"slot": "action", "quote": ACTION_QUOTE}, {"slot": "result", "answer": RESULT_ANSWER}]}


def test_check_keeps_only_questions_quoting_a_sent_slot() -> None:
    _, sent = build_interview_messages(_card_text())
    items = [
        InterviewQuestionIn(slot="RESULT", question="  결과를 어떻게 쟀나요?  ", quote="이탈률이 30% 줄었다"),
        InterviewQuestionIn(slot="action", question="왜 옮겼나요?", quote="Redis 리스트로 옮기고"),
        InterviewQuestionIn(slot="task", question="과제는?", quote="빈칸이라 보낸 적 없는 글"),
        InterviewQuestionIn(slot="action", question="몇 명과 했나요?", quote="팀원 5명과 했다"),
        InterviewQuestionIn(slot="action", question="짧은 인용?", quote="Re"),
        InterviewQuestionIn(slot="action", question="   ", quote="Redis 리스트로 옮기고"),
    ]
    result = check_interview_questions(items, sent)
    assert [(item.slot, item.question, item.quote_source) for item in result.questions] == [
        ("action", "왜 옮겼나요?", "quote"),  # 카드 칸 순서로(행동 → 결과)
        ("result", "결과를 어떻게 쟀나요?", "answer"),
    ]
    assert result.questions[0].quote_start == ACTION_QUOTE.index("Redis 리스트로 옮기고")
    assert result.received == 5
    assert dict(result.drop_reasons) == {
        DROP_UNKNOWN_SLOT: 1, DROP_QUOTE_NOT_FOUND: 1, DROP_QUOTE_TOO_SHORT: 1, DROP_EMPTY_QUESTION: 1,
    }


def test_check_keeps_at_most_the_limit() -> None:
    _, sent = build_interview_messages(_card_text())
    items = [InterviewQuestionIn(slot="action", question=f"질문{index}?", quote="Redis 리스트로 옮기고") for index in range(INTERVIEW_MAX_QUESTIONS + 2)]
    result = check_interview_questions(items, sent)
    assert len(result.questions) == INTERVIEW_MAX_QUESTIONS
    assert result.drop_reasons[DROP_TOO_MANY] == 2


# --- ③ [면접 질문 만들기] ---


def test_write_sends_only_this_cards_text_and_saves_checked_questions(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    _card(db_session, ready["user_id"], title="다른 카드")  # 같은 사용자의 다른 카드 — 보내지 않아야 함
    mock = use_mock(MockLLMClient([GOOD_REPLY]))
    response = _write(client, ready["card_id"])
    assert response.status_code == 201
    body = response.json()
    assert (body["written"], body["questions"], body["received"], body["fields_sent"]) == (True, 2, 4, 2)
    assert body["drop_reasons"] == {DROP_UNKNOWN_SLOT: 1, DROP_QUOTE_NOT_FOUND: 1}
    sent = json.loads(mock.calls[0][1].content)
    assert sent["card_title"] == "Redis 재설계" and [item["slot"] for item in sent["fields"]] == ["action", "result"]
    assert "다른 카드" not in mock.calls[0][1].content and set(sent) == {"card_title", "fields"}  # 다른 카드 · 카드 번호 · 공고 없음

    rows = db_session.scalars(select(InterviewQuestion).order_by(InterviewQuestion.position)).all()
    assert [(row.position, row.slot, row.quote_source) for row in rows] == [(0, "action", "quote"), (1, "result", "answer")]
    log = db_session.scalars(select(InterviewLog)).one()
    assert (log.fields_sent, log.questions, log.kept, log.outcome) == (2, 4, 2, "ok")
    assert _count(db_session, CardInterviewClaim) == 0
    assert db_session.scalars(select(AIUsageLog.feature)).all() == ["interview_write"]

    again = _write(client, ready["card_id"])
    assert again.status_code == 409 and "이미" in again.json()["detail"]


def test_candidate_and_blank_cards_are_blocked_before_ai(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    mock = use_mock(MockLLMClient([GOOD_REPLY]))
    candidate = _card(db_session, ready["user_id"], status=CARD_STATUS_CANDIDATE)
    blank = _card(db_session, ready["user_id"], blank=True)
    response = _write(client, candidate.id)
    assert response.status_code == 409 and "저장" in response.json()["detail"]
    response = _write(client, blank.id)
    assert response.status_code == 409 and "빈칸" in response.json()["detail"]
    assert mock.calls == [] and _count(db_session, InterviewLog) == 0


def test_other_users_card_is_not_found(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    mock = use_mock(MockLLMClient([GOOD_REPLY]))
    stranger_card = _card(db_session, _user(db_session, "stranger"))
    assert _write(client, stranger_card.id).status_code == 404
    assert _write(client, 2**31).status_code == 404  # DB 범위 밖은 DB에 묻기 전에
    assert mock.calls == []


def test_write_is_blocked_while_claimed_or_other_ai_work_runs(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    mock = use_mock(MockLLMClient([GOOD_REPLY]))
    db_session.add(CardInterviewClaim(user_id=ready["user_id"], card_id=ready["card_id"], claimed_at=now_utc()))
    db_session.commit()
    response = _write(client, ready["card_id"])
    assert response.status_code == 409 and "만드는 중" in response.json()["detail"]

    db_session.execute(delete(CardInterviewClaim))
    other = _card(db_session, ready["user_id"], title="다른 카드")
    db_session.add(CardInterviewClaim(user_id=ready["user_id"], card_id=other.id, claimed_at=now_utc()))
    db_session.commit()
    response = _write(client, ready["card_id"])
    assert response.status_code == 409 and "다른 AI 작업" in response.json()["detail"]
    assert mock.calls == []


def test_write_respects_the_daily_limit(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    mock = use_mock(MockLLMClient([GOOD_REPLY]))
    db_session.execute(update(User).where(User.id == ready["user_id"]).values(daily_limit=1))
    db_session.commit()
    record_usage(db_session, user_id=ready["user_id"], feature="draft_write", usage=LLMUsage(calls=1), outcome="ok")
    assert _write(client, ready["card_id"]).status_code == 429
    assert mock.calls == []


def test_ai_failure_keeps_log_usage_and_releases_the_claim(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    use_mock(MockLLMClient([LLMRateLimited("한도", usage=LLMUsage(calls=1))]))
    assert _write(client, ready["card_id"]).status_code == 503
    log = db_session.scalars(select(InterviewLog)).one()
    assert (log.kept, log.outcome) == (0, "rate_limited")
    assert _count(db_session, CardInterviewClaim) == 0 and _count(db_session, InterviewQuestion) == 0
    assert db_session.scalar(select(func.sum(AIUsageLog.calls))) == 1


def test_no_kept_questions_saves_nothing_and_can_retry(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    use_mock(MockLLMClient([_reply({"slot": "action", "question": "지어낸 인용?", "quote": "카드에 없는 글이다"}), GOOD_REPLY]))
    first = _write(client, ready["card_id"])
    assert first.status_code == 201 and (first.json()["written"], first.json()["questions"]) == (False, 0)
    assert _count(db_session, InterviewQuestion) == 0
    assert db_session.scalars(select(InterviewLog.outcome)).all() == ["no_questions"]
    second = _write(client, ready["card_id"])
    assert second.status_code == 201 and second.json()["questions"] == 2


def test_card_deleted_while_ai_writes_is_404(client: TestClient, db_session: Session, ready: dict[str, int]) -> None:
    plan: InterviewPlan = prepare_interview(db_session, user_id=ready["user_id"], card_id=ready["card_id"])
    db_session.execute(delete(Card).where(Card.id == ready["card_id"]))
    db_session.commit()
    reply = asyncio.run(request_interview_questions(MockLLMClient([GOOD_REPLY]), plan.messages))
    with pytest.raises(CardNotFound):
        save_interview(db_session, plan, reply)
    assert _count(db_session, InterviewQuestion) == 0
    assert db_session.scalar(select(func.sum(AIUsageLog.calls))) == 1  # AI는 불렀으니 사용량은 남김


def test_abandon_counts_one_call_and_releases_the_claim(db_session: Session) -> None:
    user_id = _user(db_session, "abandon")
    card = _card(db_session, user_id)
    plan = prepare_interview(db_session, user_id=user_id, card_id=card.id)
    assert _count(db_session, CardInterviewClaim) == 1
    abandon(db_session, plan)
    assert _count(db_session, CardInterviewClaim) == 0
    assert db_session.scalar(select(func.sum(AIUsageLog.calls))) == 1


def test_mock_responder_quotes_each_slot_text() -> None:
    messages, sent = build_interview_messages(_card_text())
    reply = json.loads(mock_interview_responder(messages))
    result = check_interview_questions([InterviewQuestionIn(**item) for item in reply["questions"]], sent)
    assert [item.slot for item in result.questions] == ["action", "result"] and not result.drop_reasons


# --- ④ 카드 상세 · 다시 검사 ---


def test_card_detail_lists_questions_and_rechecks_evidence(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    use_mock(MockLLMClient([GOOD_REPLY]))
    assert _write(client, ready["card_id"]).status_code == 201
    detail = client.get(f"/api/cards/{ready['card_id']}").json()
    assert [(item["slot"], item["evidence_status"]) for item in detail["interview_questions"]] == [("action", "ok"), ("result", "ok")]

    # 결과 칸의 내 답을 고치면 그 질문만 '근거가 바뀜' — 고친 응답에 바로 보인다
    response = client.put(f"/api/cards/{ready['card_id']}/fields/result", json={"answer": "이탈률이 줄었다."})
    assert response.status_code == 200
    assert [item["evidence_status"] for item in response.json()["interview_questions"]] == ["ok", "changed"]


# --- ⑤ 메모 ---


def test_memo_saves_clears_and_validates(client: TestClient, db_session: Session, ready: dict[str, int]) -> None:
    question = _saved_question(db_session, ready["user_id"], ready["card_id"])
    response = client.patch(f"/api/interview-questions/{question.id}", json={"memo": "  로그인 사용자만 옮긴 이유는…\n두 번째 줄  "})
    assert response.status_code == 200
    body = response.json()
    assert body["memo"] == "로그인 사용자만 옮긴 이유는…\n두 번째 줄" and body["answered_at"] is not None

    cleared = client.patch(f"/api/interview-questions/{question.id}", json={"memo": "   "}).json()
    assert (cleared["memo"], cleared["answered_at"]) == (None, None)

    too_long = client.patch(f"/api/interview-questions/{question.id}", json={"memo": "가" * (INTERVIEW_MEMO_MAX_CHARS + 1)})
    assert too_long.status_code == 422
    control = client.patch(f"/api/interview-questions/{question.id}", json={"memo": "답\x00"})
    assert control.status_code == 422
    # 본문 상한(요청 모양 검사)을 넘으면 서비스까지 가지 않고 422 — detail은 문자열이 아니라 오류 목록(3차 리뷰 R3)
    oversized = client.patch(
        f"/api/interview-questions/{question.id}", json={"memo": "가" * (INTERVIEW_MEMO_MAX_CHARS * RAW_INPUT_SLACK + 1)}
    )
    assert oversized.status_code == 422 and isinstance(oversized.json()["detail"], list)

    stranger = _user(db_session, "memo-stranger")
    stranger_question = _saved_question(db_session, stranger, _card(db_session, stranger).id)
    assert client.patch(f"/api/interview-questions/{stranger_question.id}", json={"memo": "x"}).status_code == 404
    assert client.patch(f"/api/interview-questions/{2**31}", json={"memo": "x"}).status_code == 404


# --- ⑥ [면접 연습] 탭 ---


def _application(db: Session, user_id: int) -> int:
    return create_application(
        db, user_id=user_id, company="누리랩", role="백엔드", deadline=None, url=None,
        posting_text="- Redis 캐시 운영 경험\n- React 화면 개발 경험", questions=[QuestionInput(text="문항")],
    )


def _match(db: Session, user_id: int, application_id: int, card_id: int, *, position: int, name: str) -> None:
    requirement = db.scalar(
        select(PostingRequirement).where(PostingRequirement.application_id == application_id, PostingRequirement.position == position)
    )
    if requirement is None:
        requirement = PostingRequirement(
            user_id=user_id, application_id=application_id, position=position, name=name, kind="required",
            quote="Redis 캐시 운영 경험", quote_start=2, quote_end=14,
        )
        db.add(requirement)
        db.flush()
    db.add(RequirementMatch(
        user_id=user_id, requirement_id=requirement.id, card_id=card_id, slot="action", quote=ACTION_QUOTE[:10],
        quote_source="quote", quote_start=0, quote_end=10, reason="이유",
    ))
    db.execute(update(Application).where(Application.id == application_id).values(matched_at=now_utc()))
    db.commit()


def test_interview_tab_groups_questions_by_matched_card(client: TestClient, db_session: Session, ready: dict[str, int]) -> None:
    user_id = ready["user_id"]
    application_id = _application(db_session, user_id)
    before = client.get(f"/api/applications/{application_id}/interview").json()
    assert (before["analysis_done"], before["cards"]) == (False, [])

    no_questions = _card(db_session, user_id, title="질문 없는 카드")
    unmatched = _card(db_session, user_id, title="매칭 안 된 카드")
    _saved_question(db_session, user_id, unmatched.id)
    _match(db_session, user_id, application_id, ready["card_id"], position=0, name="Redis 운영")
    _match(db_session, user_id, application_id, ready["card_id"], position=1, name="React 화면")
    _match(db_session, user_id, application_id, no_questions.id, position=1, name="React 화면")
    answered = _saved_question(db_session, user_id, ready["card_id"], position=0)
    _saved_question(db_session, user_id, ready["card_id"], position=1, slot="result", quote="이탈률이 30% 줄었다")
    client.patch(f"/api/interview-questions/{answered.id}", json={"memo": "답"})

    body = client.get(f"/api/applications/{application_id}/interview").json()
    assert body["analysis_done"] is True
    assert [(card["card_title"], card["requirement_names"], len(card["questions"])) for card in body["cards"]] == [
        ("Redis 재설계", ["Redis 운영", "React 화면"], 2),  # 역량 두 개에 매칭돼도 카드는 한 번
        ("질문 없는 카드", ["React 화면"], 0),
    ]
    assert (body["question_count"], body["answered_count"]) == (2, 1)

    stranger_application = _application(db_session, _user(db_session, "tab-stranger"))
    assert client.get(f"/api/applications/{stranger_application}/interview").status_code == 404


def test_interview_routes_need_login(client: TestClient) -> None:
    assert client.post("/api/cards/1/interview-questions").status_code == 401
    assert client.patch("/api/interview-questions/1", json={"memo": "x"}).status_code == 401
    assert client.get("/api/applications/1/interview").status_code == 401


# --- ⑦ 동시 클릭 · 실패 경로 · 같은 글 질문 합치기 ---


def test_questions_saved_between_check_and_claim_stop_before_ai(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """'이미 질문 있음' 확인과 선점 사이에 다른 요청이 질문을 저장했으면 선점 뒤 다시 보고 409 — AI를 부르지 않는다(R2 · R3)."""
    user_id = _user(db_session, "race")
    card = _card(db_session, user_id)
    answers = iter([False, True])  # 처음 확인은 없음, 선점한 뒤에는 있음
    monkeypatch.setattr(interview_service, "_has_questions", lambda *_args, **_kwargs: next(answers))
    with pytest.raises(interview_service.QuestionsAlreadyExist):
        prepare_interview(db_session, user_id=user_id, card_id=card.id)
    assert _count(db_session, CardInterviewClaim) == 0


def test_error_after_claiming_releases_the_claim(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """선점한 뒤 다시 확인에서 DB 오류가 나도 선점을 풀고 올린다 — 안 풀면 5분 동안 모든 AI 작업이 409(3차 리뷰 R2 · R3)."""
    user_id = _user(db_session, "claim-then-error")
    card = _card(db_session, user_id)
    checks = iter([False])  # 처음 확인은 통과, 선점한 뒤 확인에서 오류

    def check_then_fail(*_args: object, **_kwargs: object) -> bool:
        for answer in checks:
            return answer
        raise RuntimeError("DB 연결 끊김")

    monkeypatch.setattr(interview_service, "_has_questions", check_then_fail)
    with pytest.raises(RuntimeError):
        prepare_interview(db_session, user_id=user_id, card_id=card.id)
    assert _count(db_session, CardInterviewClaim) == 0


def test_invalid_ai_output_is_502_and_releases_the_claim(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    use_mock(MockLLMClient(["형식이 틀린 답", "또 틀린 답"]))  # 형식 검사를 다시 해도 틀림 → LLMInvalidOutput
    response = _write(client, ready["card_id"])
    assert response.status_code == 502 and "형식" in response.json()["detail"]
    assert _count(db_session, CardInterviewClaim) == 0 and _count(db_session, InterviewQuestion) == 0


def test_save_failure_is_500_counts_usage_and_releases_the_claim(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_mock(MockLLMClient([GOOD_REPLY]))

    def broken_rows(*_args: object) -> list[InterviewQuestion]:
        raise RuntimeError("DB 오류")

    monkeypatch.setattr(interview_service, "_rows", broken_rows)
    response = _write(client, ready["card_id"])
    assert response.status_code == 500 and "저장하지 못했어요" in response.json()["detail"]
    assert _count(db_session, CardInterviewClaim) == 0 and _count(db_session, InterviewQuestion) == 0
    usage = db_session.scalars(select(AIUsageLog)).one()
    assert (usage.calls, usage.outcome) == (1, "save_failed")


def test_unexpected_error_during_ai_call_releases_the_claim(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    use_mock(MockLLMClient([RuntimeError("boom")]))
    with pytest.raises(RuntimeError):
        _write(client, ready["card_id"])
    assert _count(db_session, CardInterviewClaim) == 0
    usage = db_session.scalars(select(AIUsageLog)).one()
    assert (usage.calls, usage.outcome) == (1, "error")


def test_interview_tab_merges_same_questions_keeping_the_answered_one(client: TestClient, db_session: Session, ready: dict[str, int]) -> None:
    """같은 글의 질문은 서버가 하나로 — 답한 질문을 남기고, 질문 수 · 답한 수도 합친 뒤 센다(R1 · R4)."""
    user_id = ready["user_id"]
    application_id = _application(db_session, user_id)
    second = _card(db_session, user_id, title="두 번째 카드")
    _match(db_session, user_id, application_id, ready["card_id"], position=0, name="역량")
    _match(db_session, user_id, application_id, second.id, position=0, name="역량")
    first_question = _saved_question(db_session, user_id, ready["card_id"])
    first_question.question = "같은 질문인가요?"
    same = _saved_question(db_session, user_id, second.id)
    same.question = "같은  질문인가요?"  # 공백만 다름
    db_session.commit()
    client.patch(f"/api/interview-questions/{same.id}", json={"memo": "답했어요"})

    body = client.get(f"/api/applications/{application_id}/interview").json()
    assert [[q["id"] for q in card["questions"]] for card in body["cards"]] == [[], [same.id]]
    assert [card["has_questions"] for card in body["cards"]] == [True, True]  # 합쳐져 비었어도 '질문 없는 카드'가 아님
    assert (body["question_count"], body["answered_count"]) == (1, 1)


def test_prepare_closes_its_transaction_before_the_ai_call(db_session: Session) -> None:
    """AI 응답(최대 180초)을 기다리는 동안 DB 연결을 붙잡지 않는다 — 'idle in transaction' 방지(2차 리뷰 R2)."""
    user_id = _user(db_session, "no-open-transaction")
    card = _card(db_session, user_id)
    prepare_interview(db_session, user_id=user_id, card_id=card.id)
    assert not db_session.in_transaction()


def test_saving_after_losing_the_claim_saves_nothing(db_session: Session) -> None:
    """AI가 오래 걸려 다른 요청이 선점을 가져갔으면(선점 줄이 없음) 저장하지 않는다 — 사용량은 save_failed(2차 리뷰 R3)."""
    user_id = _user(db_session, "claim-lost")
    card = _card(db_session, user_id)
    plan = prepare_interview(db_session, user_id=user_id, card_id=card.id)
    db_session.execute(delete(CardInterviewClaim))
    db_session.commit()
    reply = asyncio.run(request_interview_questions(MockLLMClient([GOOD_REPLY]), plan.messages))
    with pytest.raises(ClaimLost):
        save_interview(db_session, plan, reply)
    assert (_count(db_session, InterviewQuestion), _count(db_session, InterviewLog)) == (0, 0)
    assert db_session.scalars(select(AIUsageLog.outcome)).all() == ["save_failed"]


def test_card_deleted_during_the_ai_call_is_404_over_http(
    client: TestClient, db_session: Session, ready: dict[str, int], use_mock: UseMock
) -> None:
    """AI가 답하는 사이 카드가 지워지면 API는 404(2차 리뷰 R3)."""

    def delete_then_reply(_messages: object) -> str:
        db_session.execute(delete(Card).where(Card.id == ready["card_id"]))
        db_session.commit()
        return GOOD_REPLY

    use_mock(MockLLMClient(responder=delete_then_reply))
    response = _write(client, ready["card_id"])
    assert response.status_code == 404 and "카드" in response.json()["detail"]
    assert _count(db_session, InterviewQuestion) == 0
