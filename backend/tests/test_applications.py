"""공고 입력 · 요구 역량 뽑기 · 경험 매칭 (F-007) 테스트.

① 표 구조(버전 0007): 공고를 지우면 문항 · 역량 · 매칭 · 선점이 같이 지워지고 로그는 남는다, 카드를 지우면 매칭만 지워진다,
   사용자를 지우면 모두 지워진다(D-004).
② 공고 API: 만들기 · 입력 검사(링크는 http · https만) · D-day 순 목록 · 상태/마감일 바꾸기 · 삭제, 남의 공고는 404.
③ 역량 뽑기: 공고 원문 인용 검사(글자 그대로 없으면 버림, D-003), 공고당 한 번(409), 0개면 다시 누를 수 있음, AI 오류,
   선점(분석 중 · 다른 AI 작업 409, D-020), 하루 상한(D-018).
④ 매칭: 키워드 후보(내 저장 카드만, D-004), 후보 · 카드 칸 인용 검사, 후보가 없으면 AI를 부르지 않음, 다시 하면 바꿈,
   AI를 부르는 동안 지워진 카드는 뺌. AI는 MockLLMClient로 바꿔 끼운다.
"""

import asyncio
import json
import typing
from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.api.applications import ApplicationStatus, get_analysis_llm_client
from app.config import (
    APPLICATION_CLAIM_STALE_SECONDS,
    APPLICATION_STATUSES,
    CARD_SLOTS,
    CARD_STATUS_CANDIDATE,
    CARD_STATUS_SAVED,
    DEFAULT_DAILY_LIMIT,
    MATCH_CANDIDATES_PER_REQUIREMENT,
    MATCH_MAX_CARDS_SENT,
    MATCH_MAX_PER_REQUIREMENT,
    MAX_REQUIREMENTS,
    POSTING_TEXT_MAX_CHARS,
    SESSION_COOKIE_NAME,
    Settings,
)
from app.db.models import (
    AIUsageLog,
    Application,
    ApplicationClaim,
    ApplicationQuestion,
    Card,
    CardField,
    NoteCardClaim,
    PostingAnalysisLog,
    PostingRequirement,
    RequirementMatch,
)
from app.korea_time import korea_today
from app.llm import LLMRateLimited, LLMUsage, MockLLMClient
from app.main import app
from app.services import note_claim, posting_analysis
from app.services.application_service import QuestionInput, create_application
from app.services.auth_service import GoogleProfile, create_session_token, get_or_create_google_user
from app.services.note_service import delete_user_account
from app.services.posting_analysis import ClaimLost, prepare_extract, prepare_match, save_extract, save_match
from app.services.posting_checks import (
    DROP_CARD_GONE,
    DROP_DUPLICATE,
    DROP_EMPTY_NAME,
    DROP_NO_REASON,
    DROP_NOT_CANDIDATE,
    DROP_QUOTE_NOT_FOUND,
    DROP_QUOTE_TOO_SHORT,
    DROP_TOO_MANY,
    DROP_UNKNOWN_REQUIREMENT,
    DROP_UNKNOWN_SLOT,
    OUTCOME_NO_CANDIDATES,
)
from app.services.posting_extraction import RequirementDraftIn, check_requirements, request_requirements
from app.services.posting_matching import (
    CardText,
    MatchDraftIn,
    RequirementForMatch,
    check_matches,
    pick_candidates,
    rank_candidates,
    request_matches,
    requirement_terms,
)
from app.services.posting_mock import mock_analysis_responder
from app.services.usage_service import FEATURE_POSTING_EXTRACT, FEATURE_POSTING_MATCH, record_usage

POSTING = """[디딤컴퍼니] 백엔드 개발자 채용

자격 요건
- Python과 FastAPI로 API를 개발한 경험
- PostgreSQL 쿼리 튜닝 경험

우대 사항
- Redis 캐시를 운영해 본 분
"""


def _user(db: Session, name: str) -> int:
    return get_or_create_google_user(db, GoogleProfile(sub=name, email=f"{name}@example.com", name=name)).id


def _login(client: TestClient, db: Session, settings: Settings, sub: str) -> int:
    user_id = _user(db, sub)
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id, settings.session_secret))
    return user_id


def _application(db: Session, user_id: int, *, deadline: date | None = None, company: str = "디딤컴퍼니") -> int:
    return create_application(
        db,
        user_id=user_id,
        company=company,
        role="백엔드 개발자",
        deadline=deadline,
        url="https://example.com/jobs/1",
        posting_text=POSTING.strip(),
        questions=[QuestionInput(text="지원 동기를 적어 주세요.", char_limit=500)],
    )


def _card(
    db: Session,
    user_id: int,
    title: str,
    *,
    action_quote: str | None = None,
    result_answer: str | None = None,
    status: str = CARD_STATUS_SAVED,
) -> Card:
    """행동 칸에 원문 인용(노트 없이 — 매칭은 칸 글만 본다), 결과 칸에 내 답을 넣은 카드."""
    card = Card(user_id=user_id, note_id=None, title=title, status=status)
    for slot in CARD_SLOTS:
        if slot == "action" and action_quote:
            card.fields.append(CardField(user_id=user_id, slot=slot, quote=action_quote, quote_start=0, quote_end=len(action_quote)))
        elif slot == "result" and result_answer:
            card.fields.append(CardField(user_id=user_id, slot=slot, answer=result_answer))
        else:
            card.fields.append(CardField(user_id=user_id, slot=slot, question="?"))
    db.add(card)
    db.commit()
    return card


def _extract_reply(*items: tuple[str, str, str]) -> str:
    return json.dumps(
        {"requirements": [{"name": name, "kind": kind, "quote": quote} for name, kind, quote in items]},
        ensure_ascii=False,
    )


GOOD_EXTRACT = _extract_reply(
    ("Python · FastAPI", "required", "Python과 FastAPI로 API를 개발한 경험"),
    ("SQL 튜닝", "required", "PostgreSQL 쿼리 튜닝 경험"),
    ("Redis", "preferred", "Redis 캐시를 운영해 본 분"),
)


def _count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture()
def use_mock(client: TestClient) -> Generator[typing.Callable[[MockLLMClient], MockLLMClient], None, None]:
    def _use(mock: MockLLMClient) -> MockLLMClient:
        app.dependency_overrides[get_analysis_llm_client] = lambda: mock
        return mock

    yield _use
    app.dependency_overrides.pop(get_analysis_llm_client, None)


def _extracted(db: Session, user_id: int, application_id: int) -> None:
    """역량 뽑기를 AI 없이 끝낸 상태로 만든다."""
    plan = prepare_extract(db, user_id=user_id, application_id=application_id)
    reply = asyncio.run(request_requirements(MockLLMClient([GOOD_EXTRACT]), plan.messages))
    save_extract(db, plan, reply)


def _requirement_ids(db: Session, application_id: int) -> list[int]:
    return list(
        db.scalars(
            select(PostingRequirement.id)
            .where(PostingRequirement.application_id == application_id)
            .order_by(PostingRequirement.position)
        ).all()
    )


# --- ① 표 구조 ---


def test_status_literal_matches_config() -> None:
    assert typing.get_args(ApplicationStatus) == APPLICATION_STATUSES


def test_deleting_a_card_removes_only_its_matches(db_session: Session) -> None:
    user_id = _user(db_session, "cascade-card")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    card = _card(db_session, user_id, "API 서버", action_quote="FastAPI로 주문 API를 만들었다")
    requirement_id = _requirement_ids(db_session, application_id)[0]
    db_session.add(
        RequirementMatch(
            user_id=user_id, requirement_id=requirement_id, card_id=card.id, slot="action",
            quote="FastAPI로 주문 API", quote_source="quote", quote_start=0, quote_end=14, reason="이유",
        )
    )
    db_session.commit()

    db_session.execute(delete(Card).where(Card.id == card.id))
    db_session.commit()
    assert _count(db_session, RequirementMatch) == 0
    assert _count(db_session, PostingRequirement) == 3  # 역량은 남고 '근거 없음'으로 돌아감


def test_deleting_an_application_removes_children_but_keeps_logs(db_session: Session) -> None:
    user_id = _user(db_session, "cascade-application")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    db_session.add(ApplicationClaim(user_id=user_id, application_id=application_id, claimed_at=datetime.now(timezone.utc)))
    db_session.commit()

    db_session.execute(delete(Application).where(Application.id == application_id))
    db_session.commit()
    for model in (ApplicationQuestion, PostingRequirement, ApplicationClaim):
        assert _count(db_session, model) == 0
    assert _count(db_session, PostingAnalysisLog) == 1


def test_deleting_the_user_removes_every_application_row(db_session: Session) -> None:
    user_id = _user(db_session, "cascade-user")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    delete_user_account(db_session, user_id=user_id)
    for model in (Application, ApplicationQuestion, PostingRequirement, PostingAnalysisLog):
        assert _count(db_session, model) == 0


# --- ② 공고 API ---


def _create_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "company": "  디딤컴퍼니 ",
        "role": "백엔드 개발자",
        "deadline": "2026-12-01",
        "url": "https://example.com/jobs/1",
        "posting_text": f"\n{POSTING}\n",
        "questions": [{"text": "지원 동기", "char_limit": 700}, {"text": "  ", "char_limit": None}],
    }
    body.update(overrides)
    return body


def test_create_application_saves_posting_and_questions(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    _login(client, db_session, test_settings, "create")
    response = client.post("/api/applications", json=_create_body())
    assert response.status_code == 201
    data = response.json()
    assert data["company"] == "디딤컴퍼니"  # 공백 정리
    assert data["status"] == "ready"
    assert data["posting_text"] == POSTING.strip()  # 앞뒤 공백만 걷음
    assert [(item["text"], item["char_limit"]) for item in data["questions"]] == [("지원 동기", 700)]  # 빈 문항은 건너뜀
    assert data["requirements"] == [] and data["extracted_at"] is None and data["matched_at"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"company": "   "},
        {"role": ""},
        {"posting_text": "   "},
        {"posting_text": "가" * (POSTING_TEXT_MAX_CHARS + 1)},
        {"url": "javascript:alert(1)"},
        {"url": "ftp://example.com/a"},
        {"url": "https://exa mple.com"},
        {"url": "http://[abc"},  # urlsplit이 ValueError를 내는 주소 — 500이 아니라 422(F-007 2차 R3)
        {"company": "회사\x00"},
        {"questions": [{"text": "문항", "char_limit": 0}]},
    ],
)
def test_create_application_rejects_bad_input(
    client: TestClient, db_session: Session, test_settings: Settings, overrides: dict[str, object]
) -> None:
    _login(client, db_session, test_settings, "create-bad")
    response = client.post("/api/applications", json=_create_body(**overrides))
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert _count(db_session, Application) == 0


def test_list_is_sorted_by_d_day(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    user_id = _login(client, db_session, test_settings, "list")
    today = korea_today()
    ids = {
        "none": _application(db_session, user_id, company="마감 없음"),
        "past": _application(db_session, user_id, deadline=today - timedelta(days=3), company="지남"),
        "far": _application(db_session, user_id, deadline=today + timedelta(days=10), company="멀다"),
        "today": _application(db_session, user_id, deadline=today, company="오늘"),
        "past_recent": _application(db_session, user_id, deadline=today - timedelta(days=1), company="어제"),
    }
    other = _user(db_session, "list-other")
    _application(db_session, other, company="남의 공고")

    data = client.get("/api/applications").json()
    assert data["total"] == 5
    assert [item["id"] for item in data["applications"]] == [
        ids["today"], ids["far"], ids["past_recent"], ids["past"], ids["none"]
    ]
    assert [item["days_left"] for item in data["applications"]] == [0, 10, -1, -3, None]


def test_update_status_and_deadline(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    user_id = _login(client, db_session, test_settings, "patch")
    application_id = _application(db_session, user_id, deadline=date(2026, 12, 1))

    response = client.patch(f"/api/applications/{application_id}", json={"status": "writing"})
    assert response.status_code == 200
    assert response.json()["status"] == "writing" and response.json()["deadline"] == "2026-12-01"  # 안 보낸 마감일은 그대로

    response = client.patch(f"/api/applications/{application_id}", json={"deadline": None})
    assert response.json()["deadline"] is None and response.json()["status"] == "writing"

    assert client.patch(f"/api/applications/{application_id}", json={"status": "done"}).status_code == 422


def test_other_users_application_is_not_found(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    owner = _user(db_session, "owner")
    application_id = _application(db_session, owner)
    _login(client, db_session, test_settings, "stranger")
    assert client.get(f"/api/applications/{application_id}").status_code == 404
    assert client.patch(f"/api/applications/{application_id}", json={"status": "writing"}).status_code == 404
    assert client.delete(f"/api/applications/{application_id}").status_code == 404
    assert client.post(f"/api/applications/{application_id}/requirements").status_code == 404
    assert client.post(f"/api/applications/{application_id}/matches").status_code == 404
    assert client.get("/api/applications/99999999999").status_code == 404
    assert _count(db_session, Application) == 1


def test_delete_application(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    user_id = _login(client, db_session, test_settings, "delete")
    application_id = _application(db_session, user_id)
    assert client.delete(f"/api/applications/{application_id}").status_code == 204
    assert client.get(f"/api/applications/{application_id}").status_code == 404


# --- ③ 요구 역량 뽑기 ---


def test_check_requirements_keeps_only_quotes_found_in_the_posting() -> None:
    posting = POSTING.strip()
    drafts = [
        RequirementDraftIn(name="Redis", kind="preferred", quote="Redis 캐시를 운영해 본 분"),
        RequirementDraftIn(name="Python", kind="required", quote="  Python과 FastAPI로 API를 개발한 경험 "),
        RequirementDraftIn(name="쿠버네티스", kind="required", quote="쿠버네티스 운영 경험"),  # 공고에 없음
        RequirementDraftIn(name="python", kind="required", quote="PostgreSQL 쿼리 튜닝 경험"),  # 이름 중복
        RequirementDraftIn(name="짧음", kind="required", quote="경험"),
        RequirementDraftIn(name="  ", kind="required", quote="PostgreSQL 쿼리 튜닝 경험"),
        RequirementDraftIn(name="SQL", kind="필수", quote="PostgreSQL 쿼리 튜닝 경험"),  # 이상한 kind → 필수
    ]
    result = check_requirements(drafts, posting)
    assert [item.name for item in result.kept] == ["Python", "SQL", "Redis"]  # 공고에 나온 순서
    assert [item.kind for item in result.kept] == ["required", "required", "preferred"]
    for item in result.kept:
        assert posting[item.quote_start : item.quote_end] == item.quote
    assert result.drop_reasons == {
        DROP_QUOTE_NOT_FOUND: 1, DROP_DUPLICATE: 1, DROP_QUOTE_TOO_SHORT: 1, DROP_EMPTY_NAME: 1
    }


def test_check_requirements_keeps_at_most_the_limit() -> None:
    posting = "\n".join(f"- 요구 사항 번호 {index:02d}" for index in range(MAX_REQUIREMENTS + 3))
    drafts = [
        RequirementDraftIn(name=f"역량{index}", kind="required", quote=f"요구 사항 번호 {index:02d}")
        for index in range(MAX_REQUIREMENTS + 3)
    ]
    result = check_requirements(drafts, posting)
    assert len(result.kept) == MAX_REQUIREMENTS
    assert result.drop_reasons[DROP_TOO_MANY] == 3


def test_extract_api_saves_requirements_once(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "extract")
    application_id = _application(db_session, user_id)
    mock = use_mock(MockLLMClient([GOOD_EXTRACT]))

    response = client.post(f"/api/applications/{application_id}/requirements")
    assert response.status_code == 201
    assert response.json()["requirement_count"] == 3
    assert response.json()["remaining_today"] == DEFAULT_DAILY_LIMIT - 1
    sent = json.loads(mock.calls[0][1].content)
    assert sent == {"company": "디딤컴퍼니", "role": "백엔드 개발자", "posting": POSTING.strip()}

    detail = client.get(f"/api/applications/{application_id}").json()
    assert detail["extracted_at"] is not None
    assert [(item["name"], item["kind"]) for item in detail["requirements"]] == [
        ("Python · FastAPI", "required"), ("SQL 튜닝", "required"), ("Redis", "preferred")
    ]
    for item in detail["requirements"]:
        assert detail["posting_text"][item["quote_start"] : item["quote_end"]] == item["quote"]
        assert item["matches"] == []
    log = db_session.scalars(select(PostingAnalysisLog)).one()
    assert (log.step, log.kept, log.outcome, log.items_sent) == ("extract", 3, "ok", len(POSTING.strip()))
    usage = db_session.scalars(select(AIUsageLog)).one()
    assert usage.feature == FEATURE_POSTING_EXTRACT
    assert _count(db_session, ApplicationClaim) == 0  # 끝나면 선점을 지움

    again = client.post(f"/api/applications/{application_id}/requirements")
    assert again.status_code == 409 and again.json()["detail"] == "이 공고는 이미 요구 역량을 뽑았어요."
    assert len(mock.calls) == 1


def test_extract_with_nothing_left_can_be_retried(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "extract-none")
    application_id = _application(db_session, user_id)
    use_mock(MockLLMClient([_extract_reply(("지어냄", "required", "공고에 없는 문장입니다")), GOOD_EXTRACT]))

    first = client.post(f"/api/applications/{application_id}/requirements")
    assert first.status_code == 201 and first.json()["requirement_count"] == 0
    assert first.json()["drop_reasons"] == {DROP_QUOTE_NOT_FOUND: 1}
    assert client.get(f"/api/applications/{application_id}").json()["extracted_at"] is None

    second = client.post(f"/api/applications/{application_id}/requirements")
    assert second.status_code == 201 and second.json()["requirement_count"] == 3


def test_extract_ai_error_releases_the_claim(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "extract-error")
    application_id = _application(db_session, user_id)
    use_mock(MockLLMClient([LLMRateLimited("429")]))

    response = client.post(f"/api/applications/{application_id}/requirements")
    assert response.status_code == 503
    assert _count(db_session, ApplicationClaim) == 0
    log = db_session.scalars(select(PostingAnalysisLog)).one()
    assert log.outcome == "rate_limited"
    assert db_session.scalars(select(AIUsageLog)).one().calls == 1


def test_extract_blocked_while_another_ai_job_runs(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    """같은 사용자의 다른 AI 작업(카드 후보 찾기)이 진행 중이면 409(D-020), 같은 공고를 분석 중이어도 409."""
    from app.services.note_service import create_note_for_user
    from app.services.chunking import split_markdown

    user_id = _login(client, db_session, test_settings, "extract-busy")
    application_id = _application(db_session, user_id)
    mock = use_mock(MockLLMClient([GOOD_EXTRACT]))
    note = create_note_for_user(db_session, user_id=user_id, title="노트", content="# 노트\n본문", chunks=split_markdown("# 노트\n본문"))
    db_session.add(NoteCardClaim(user_id=user_id, note_id=note.id, claimed_at=datetime.now(timezone.utc)))
    db_session.commit()
    response = client.post(f"/api/applications/{application_id}/requirements")
    assert response.status_code == 409 and "공고 분석" in response.json()["detail"]

    db_session.execute(delete(NoteCardClaim))
    db_session.add(ApplicationClaim(user_id=user_id, application_id=application_id, claimed_at=datetime.now(timezone.utc)))
    db_session.commit()
    response = client.post(f"/api/applications/{application_id}/requirements")
    assert response.status_code == 409 and response.json()["detail"] == "이 공고를 분석하는 중이에요. 잠시 뒤 다시 확인해 주세요."
    assert mock.calls == []


def test_extract_stops_at_the_daily_limit(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "extract-limit")
    application_id = _application(db_session, user_id)
    mock = use_mock(MockLLMClient([GOOD_EXTRACT]))
    record_usage(db_session, user_id=user_id, feature="quiz_generate", usage=LLMUsage(calls=DEFAULT_DAILY_LIMIT), outcome="ok")
    assert client.post(f"/api/applications/{application_id}/requirements").status_code == 429
    assert mock.calls == [] and _count(db_session, ApplicationClaim) == 0


def test_lost_claim_saves_no_requirements(db_session: Session) -> None:
    """AI가 늦어 내 선점을 다른 요청이 가져갔으면(5분 넘음) 역량을 저장하지 않는다."""
    user_id = _user(db_session, "extract-lost")
    application_id = _application(db_session, user_id)
    plan = prepare_extract(db_session, user_id=user_id, application_id=application_id)
    taken_at = plan.claimed_at + timedelta(seconds=APPLICATION_CLAIM_STALE_SECONDS + 1)
    db_session.execute(update(ApplicationClaim).values(claimed_at=taken_at))
    db_session.commit()
    reply = asyncio.run(request_requirements(MockLLMClient([GOOD_EXTRACT]), plan.messages))
    with pytest.raises(ClaimLost):
        save_extract(db_session, plan, reply)
    assert _count(db_session, PostingRequirement) == 0
    assert db_session.scalar(select(ApplicationClaim.claimed_at)) is not None  # 새 주인의 선점은 그대로


# --- ④ 매칭 ---


def test_requirement_terms_drop_common_posting_words() -> None:
    assert requirement_terms("Redis", "Redis 캐시를 운영해 본 분") == ["Redis", "캐시를", "운영해"]
    assert "경험" not in requirement_terms("SQL 튜닝", "PostgreSQL 쿼리 튜닝 경험")


def test_rank_candidates_scores_by_matched_terms() -> None:
    cards = [
        CardText(id=1, title="블로그 글쓰기", fields={"action": ("글을 매주 썼다", None)}),
        CardText(id=2, title="캐시 도입", fields={"action": ("Redis로 캐시를 붙였다", None)}),
        CardText(id=3, title="운영 자동화", fields={"result": (None, "Redis 운영 비용을 줄였어요")}),
    ]
    # 2: Redis · 캐시(를), 3: Redis · 운영(해) — 둘 다 2점이면 원래 순서(최근 고친 카드 먼저), 1은 0점이라 빠짐
    assert rank_candidates(["Redis", "캐시를", "운영해"], cards) == [2, 3]
    assert rank_candidates(["운영해"], cards) == [3]
    assert rank_candidates([], cards) == []


def test_pick_candidates_caps_cards_per_requirement_and_total() -> None:
    cards = [CardText(id=index, title=f"Redis 카드 {index}", fields={}) for index in range(1, 40)]
    requirements = [RequirementForMatch(id=100 + index, name="Redis", kind="required", quote="Redis 캐시") for index in range(6)]
    candidates = pick_candidates(requirements, cards)
    assert all(len(picked) <= MATCH_CANDIDATES_PER_REQUIREMENT for picked in candidates.values())
    assert len({card_id for picked in candidates.values() for card_id in picked}) <= MATCH_MAX_CARDS_SENT


def test_check_matches_keeps_only_candidate_cards_with_real_quotes() -> None:
    cards = {
        1: CardText(id=1, title="캐시", fields={"action": ("Redis로 캐시를 붙였다", None), "result": (None, "응답이 0.3초로 줄었어요")}),
        2: CardText(id=2, title="튜닝", fields={"action": ("느린 쿼리에 색인을 걸었다", None)}),
    }
    candidates = {10: [1], 11: [2]}

    def draft(requirement_id: int, card_id: int, slot: str, quote: str, reason: str = "맞아요") -> MatchDraftIn:
        return MatchDraftIn(requirement_id=requirement_id, card_id=card_id, slot=slot, quote=quote, reason=reason)

    result = check_matches(
        [
            draft(10, 1, "action", "Redis로 캐시를 붙였다"),
            draft(10, 1, "result", "응답이 0.3초로 줄었어요"),  # 같은 역량 · 같은 카드
            draft(11, 2, "result", "응답이 0.3초로 줄었어요", "이유"),  # 그 칸에 없음 → 슬롯 없음
            draft(11, 1, "action", "Redis로 캐시를 붙였다"),  # 이 역량의 후보가 아님
            draft(12, 2, "action", "느린 쿼리에 색인을 걸었다"),  # 보내지 않은 역량
            draft(11, 2, "action", "느린 쿼리를 모두 고쳤다"),  # 지어낸 인용
            draft(11, 2, "Action ", "느린 쿼리에 색인을 걸었다", "  "),  # 이유 없음
            draft(11, 2, "action", "색인"),  # 너무 짧음
            draft(11, 2, "how", "느린 쿼리에 색인을 걸었다"),
            draft(11, 2, "action", "느린 쿼리에 색인을 걸었다", "색인으로 튜닝했어요"),
        ],
        candidates,
        cards,
    )
    kept = [(item.requirement_id, item.card_id, item.slot, item.quote_source) for item in result.kept]
    assert kept == [(10, 1, "action", "quote"), (11, 2, "action", "quote")]
    assert result.drop_reasons == {
        DROP_DUPLICATE: 1, DROP_UNKNOWN_SLOT: 2, DROP_NOT_CANDIDATE: 1, DROP_UNKNOWN_REQUIREMENT: 1,
        DROP_QUOTE_NOT_FOUND: 1, DROP_NO_REASON: 1, DROP_QUOTE_TOO_SHORT: 1,
    }


def test_check_matches_finds_quotes_in_my_answer_and_caps_per_requirement() -> None:
    cards = {
        index: CardText(id=index, title=f"카드{index}", fields={"result": ("인용 문장입니다", f"내 답 문장 {index}번")})
        for index in range(1, 6)
    }
    candidates = {10: [1, 2, 3, 4, 5]}
    drafts = [
        MatchDraftIn(requirement_id=10, card_id=index, slot="result", quote=f"내 답 문장 {index}번", reason="맞아요")
        for index in range(1, 6)
    ]
    result = check_matches(drafts, candidates, cards)
    assert len(result.kept) == MATCH_MAX_PER_REQUIREMENT
    assert result.kept[0].quote_source == "answer" and result.kept[0].quote_start == 0
    assert result.drop_reasons == {DROP_TOO_MANY: 5 - MATCH_MAX_PER_REQUIREMENT}


def _match_reply(*items: tuple[int, int, str, str]) -> str:
    return json.dumps(
        {"matches": [{"requirement_id": r, "card_id": c, "slot": s, "quote": q, "reason": "역량을 보여 줘요"} for r, c, s, q in items]},
        ensure_ascii=False,
    )


def test_match_api_links_only_my_saved_cards(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "match")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    python_id, sql_id, redis_id = _requirement_ids(db_session, application_id)
    mine = _card(db_session, user_id, "주문 API", action_quote="FastAPI로 주문 API를 개발했다")
    _card(db_session, user_id, "후보 카드 FastAPI", action_quote="FastAPI 후보 카드 글", status=CARD_STATUS_CANDIDATE)
    other = _user(db_session, "match-other")
    theirs = _card(db_session, other, "남의 FastAPI Redis 카드", action_quote="FastAPI와 Redis를 썼다")

    mock = use_mock(MockLLMClient([_match_reply(
        (python_id, mine.id, "action", "FastAPI로 주문 API를 개발했다"),
        (redis_id, theirs.id, "action", "FastAPI와 Redis를 썼다"),  # 남의 카드 — 후보가 아님
    )]))
    response = client.post(f"/api/applications/{application_id}/matches")
    assert response.status_code == 201
    data = response.json()
    assert (data["matches"], data["matched_requirements"], data["requirements_sent"], data["cards_sent"]) == (1, 1, 1, 1)
    assert data["drop_reasons"] == {DROP_UNKNOWN_REQUIREMENT: 1}

    sent = json.loads(mock.calls[0][1].content)
    assert [card["card_id"] for card in sent["cards"]] == [mine.id]  # 후보 카드 · 남의 카드는 보내지 않음(D-004)
    assert [item["requirement_id"] for item in sent["requirements"]] == [python_id]

    detail = client.get(f"/api/applications/{application_id}").json()
    assert detail["matched_at"] is not None
    by_id = {item["id"]: item for item in detail["requirements"]}
    match = by_id[python_id]["matches"][0]
    assert (match["card_id"], match["card_title"], match["slot"], match["quote_source"]) == (mine.id, "주문 API", "action", "quote")
    assert by_id[sql_id]["matches"] == [] and by_id[redis_id]["matches"] == []
    assert db_session.scalars(select(AIUsageLog)).all()[-1].feature == FEATURE_POSTING_MATCH

    summary = client.get("/api/applications").json()["applications"][0]
    assert (summary["requirement_count"], summary["matched_requirement_count"], summary["matched"]) == (3, 1, True)


def test_match_without_candidate_cards_skips_ai(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "match-empty")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    usage_before = _count(db_session, AIUsageLog)
    mock = use_mock(MockLLMClient())

    response = client.post(f"/api/applications/{application_id}/matches")
    assert response.status_code == 201
    assert (response.json()["matches"], response.json()["requirements_sent"]) == (0, 0)
    assert mock.calls == [] and _count(db_session, AIUsageLog) == usage_before
    assert client.get(f"/api/applications/{application_id}").json()["matched_at"] is not None
    assert db_session.scalars(select(PostingAnalysisLog).where(PostingAnalysisLog.step == "match")).one().outcome == OUTCOME_NO_CANDIDATES


def test_match_before_extract_is_409(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    user_id = _login(client, db_session, test_settings, "match-early")
    application_id = _application(db_session, user_id)
    response = client.post(f"/api/applications/{application_id}/matches")
    assert response.status_code == 409 and response.json()["detail"] == "먼저 공고에서 요구 역량을 뽑아 주세요."


def test_match_again_replaces_previous_matches(db_session: Session) -> None:
    user_id = _user(db_session, "match-again")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    python_id = _requirement_ids(db_session, application_id)[0]
    first = _card(db_session, user_id, "FastAPI 1", action_quote="FastAPI로 첫 API를 만들었다")

    plan = prepare_match(db_session, user_id=user_id, application_id=application_id)
    reply = asyncio.run(request_matches(MockLLMClient([_match_reply((python_id, first.id, "action", "FastAPI로 첫 API를 만들었다"))]), plan.messages))
    save_match(db_session, plan, reply)
    assert _count(db_session, RequirementMatch) == 1

    plan = prepare_match(db_session, user_id=user_id, application_id=application_id)
    reply = asyncio.run(request_matches(MockLLMClient([_match_reply()]), plan.messages))
    outcome = save_match(db_session, plan, reply)
    assert outcome.matches == 0 and _count(db_session, RequirementMatch) == 0


def test_card_deleted_while_matching_is_left_out(db_session: Session) -> None:
    user_id = _user(db_session, "match-gone")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    python_id = _requirement_ids(db_session, application_id)[0]
    card = _card(db_session, user_id, "FastAPI", action_quote="FastAPI로 API를 만들었다")
    plan = prepare_match(db_session, user_id=user_id, application_id=application_id)
    reply = asyncio.run(request_matches(MockLLMClient([_match_reply((python_id, card.id, "action", "FastAPI로 API를 만들었다"))]), plan.messages))
    db_session.execute(delete(Card).where(Card.id == card.id))
    db_session.commit()
    outcome = save_match(db_session, plan, reply)
    assert outcome.matches == 0 and outcome.drop_reasons == {DROP_CARD_GONE: 1}
    assert _count(db_session, ApplicationClaim) == 0


def test_mock_responder_runs_the_whole_flow(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    """키 없이(LLM_PROVIDER=mock) 화면 흐름이 끝까지 돈다 — 가짜 답도 검사를 통과하는 인용을 쓴다."""
    user_id = _login(client, db_session, test_settings, "mock-flow")
    application_id = _application(db_session, user_id)
    _card(db_session, user_id, "Redis 캐시", action_quote="Redis 캐시를 붙여 응답을 줄였다")
    use_mock(MockLLMClient(responder=mock_analysis_responder))

    extract = client.post(f"/api/applications/{application_id}/requirements").json()
    assert extract["requirement_count"] == 3
    match = client.post(f"/api/applications/{application_id}/matches").json()
    assert match["matches"] >= 1 and match["drop_reasons"] == {}


def test_mock_requirement_names_do_not_pull_in_mock_cards(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    """가짜 카드 제목의 '(mock)'과 가짜 역량 이름이 키워드로 겹쳐 엉뚱한 카드가 매칭되지 않는다(F-007 4차 R3 — 2026-11-13 화면 확인)."""
    user_id = _login(client, db_session, test_settings, "mock-names")
    application_id = _application(db_session, user_id)
    _card(db_session, user_id, "(mock) 디자인 시안 정리", action_quote="피그마로 화면 시안을 정리했다")  # 공고와 겹치는 낱말 없음
    use_mock(MockLLMClient(responder=mock_analysis_responder))

    client.post(f"/api/applications/{application_id}/requirements")
    names = [row.name for row in db_session.scalars(select(PostingRequirement)).all()]
    assert names and not any("mock" in name.casefold() for name in names)
    match = client.post(f"/api/applications/{application_id}/matches").json()
    assert match["cards_sent"] == 0 and match["matches"] == 0  # 후보 없음 → AI 안 부르고 모두 '근거 없음'


def test_claim_rules_cover_application_claims() -> None:
    assert note_claim.APPLICATION_CLAIMS in note_claim.ALL_TABLES
    assert posting_analysis._CLAIM_RULES.table is note_claim.APPLICATION_CLAIMS


# --- 실패 경로 (1차 리뷰 R3) ---


def _saved_card_for_python(db: Session, user_id: int) -> Card:
    return _card(db, user_id, "FastAPI 서버", action_quote="FastAPI로 주문 API를 만들었다")


def test_match_ai_error_keeps_previous_matches_and_releases_the_claim(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "match-ai-error")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    card = _saved_card_for_python(db_session, user_id)
    python_id = _requirement_ids(db_session, application_id)[0]
    use_mock(MockLLMClient([_match_reply((python_id, card.id, "action", "FastAPI로 주문 API를 만들었다")), LLMRateLimited("429")]))
    assert client.post(f"/api/applications/{application_id}/matches").status_code == 201

    response = client.post(f"/api/applications/{application_id}/matches")  # [매칭 다시] — AI 실패
    assert response.status_code == 503
    assert _count(db_session, RequirementMatch) == 1  # 이전 매칭은 그대로(저장까지 가지 않음)
    assert _count(db_session, ApplicationClaim) == 0
    log = db_session.scalars(select(PostingAnalysisLog).order_by(PostingAnalysisLog.id.desc())).first()
    assert (log.step, log.outcome) == ("match", "rate_limited")
    usage = db_session.scalars(select(AIUsageLog).order_by(AIUsageLog.id.desc())).first()
    assert (usage.feature, usage.outcome) == (FEATURE_POSTING_MATCH, "rate_limited")


def test_match_stops_at_the_daily_limit_and_while_analysis_runs(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "match-limits")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    _saved_card_for_python(db_session, user_id)
    mock = use_mock(MockLLMClient())

    db_session.add(ApplicationClaim(user_id=user_id, application_id=application_id, claimed_at=datetime.now(timezone.utc)))
    db_session.commit()
    response = client.post(f"/api/applications/{application_id}/matches")
    assert response.status_code == 409 and response.json()["detail"] == "이 공고를 분석하는 중이에요. 잠시 뒤 다시 확인해 주세요."
    db_session.execute(delete(ApplicationClaim))
    db_session.commit()

    record_usage(db_session, user_id=user_id, feature="quiz_generate", usage=LLMUsage(calls=DEFAULT_DAILY_LIMIT), outcome="ok")
    assert client.post(f"/api/applications/{application_id}/matches").status_code == 429  # 후보가 있으면 상한 확인
    assert mock.calls == [] and _count(db_session, ApplicationClaim) == 0


def test_lost_claim_saves_no_matches(db_session: Session) -> None:
    user_id = _user(db_session, "match-lost")
    application_id = _application(db_session, user_id)
    _extracted(db_session, user_id, application_id)
    card = _saved_card_for_python(db_session, user_id)
    python_id = _requirement_ids(db_session, application_id)[0]
    plan = prepare_match(db_session, user_id=user_id, application_id=application_id)
    db_session.execute(update(ApplicationClaim).values(claimed_at=plan.claimed_at + timedelta(seconds=APPLICATION_CLAIM_STALE_SECONDS + 1)))
    db_session.commit()
    reply = asyncio.run(request_matches(MockLLMClient([_match_reply((python_id, card.id, "action", "FastAPI로 주문 API를 만들었다"))]), plan.messages))
    with pytest.raises(ClaimLost):
        save_match(db_session, plan, reply)
    assert _count(db_session, RequirementMatch) == 0
    assert db_session.scalar(select(Application.matched_at)) is None


@pytest.mark.parametrize("step", ["requirements", "matches"])
def test_save_failure_is_500_and_cleans_up(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
    use_mock: typing.Callable[[MockLLMClient], MockLLMClient],
    monkeypatch: pytest.MonkeyPatch,
    step: str,
) -> None:
    user_id = _login(client, db_session, test_settings, f"save-fail-{step}")
    application_id = _application(db_session, user_id)
    if step == "matches":
        _extracted(db_session, user_id, application_id)
        _saved_card_for_python(db_session, user_id)
    use_mock(MockLLMClient([GOOD_EXTRACT], responder=mock_analysis_responder))

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("저장 중 오류")

    monkeypatch.setattr(posting_analysis, "check_requirements" if step == "requirements" else "check_matches", broken)
    response = client.post(f"/api/applications/{application_id}/{step}")
    assert response.status_code == 500 and "저장하지 못했어요" in response.json()["detail"]
    assert _count(db_session, ApplicationClaim) == 0
    usage = db_session.scalars(select(AIUsageLog).order_by(AIUsageLog.id.desc())).first()
    assert usage.outcome == "save_failed"
    detail = client.get(f"/api/applications/{application_id}").json()
    assert detail["matched_at"] is None
    if step == "requirements":
        assert detail["extracted_at"] is None and detail["requirements"] == []


def test_invalid_ai_output_is_502(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    user_id = _login(client, db_session, test_settings, "extract-502")
    application_id = _application(db_session, user_id)
    use_mock(MockLLMClient(["형식이 틀린 답", "또 틀린 답"]))
    response = client.post(f"/api/applications/{application_id}/requirements")
    assert response.status_code == 502 and "형식" in response.json()["detail"]
    assert _count(db_session, ApplicationClaim) == 0


def test_application_deleted_while_ai_runs_is_404(
    client: TestClient, db_session: Session, test_settings: Settings, use_mock: typing.Callable[[MockLLMClient], MockLLMClient]
) -> None:
    """AI를 부르는 동안 공고를 지우면 '저장 실패'(500)가 아니라 '없는 공고'(404) — 사용량은 남긴다(1차 리뷰 R3)."""
    user_id = _login(client, db_session, test_settings, "deleted-mid-ai")
    application_id = _application(db_session, user_id)

    def delete_then_answer(_messages: object) -> str:
        db_session.execute(delete(Application).where(Application.id == application_id))
        db_session.commit()
        return GOOD_EXTRACT

    use_mock(MockLLMClient(responder=delete_then_answer))
    response = client.post(f"/api/applications/{application_id}/requirements")
    assert response.status_code == 404
    assert _count(db_session, PostingRequirement) == 0
    assert db_session.scalars(select(AIUsageLog)).one().outcome == "save_failed"


def test_abandon_counts_one_call_and_releases_the_claim(db_session: Session) -> None:
    """AI 호출이 LLMError가 아닌 이유(요청 취소 등)로 끝나도 로그 · 사용량 1회 · 선점 해제(D-018)."""
    user_id = _user(db_session, "abandon")
    application_id = _application(db_session, user_id)
    plan = prepare_extract(db_session, user_id=user_id, application_id=application_id)
    posting_analysis.abandon(db_session, plan)
    assert _count(db_session, ApplicationClaim) == 0
    assert db_session.scalars(select(AIUsageLog)).one().calls == 1
    assert db_session.scalars(select(PostingAnalysisLog)).one().outcome == "error"
