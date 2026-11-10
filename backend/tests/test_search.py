"""기록 검색 테스트 (F-003, 2주차).

설계 의도의 완료 기준(feature.md)과 짝지어 확인한다.
1. 낱말 · 문장을 넣으면 내 조각 최대 5개, 결과마다 노트 제목 · 제목 경로 · 원문 위치
2. 다른 사용자의 조각은 나오지 않음(D-004)
3. (화면) 결과를 누르면 노트 상세에서 그 위치 강조 → 여기서는 노트 상세 API가 원문 · 조각 위치를 주는지
4. 검색마다 질문 · 결과 조각 · 점수를 로그로 남김(D-005)
6. 검색 방식은 갈아 끼울 수 있음(Depends(get_searcher))

키워드 검색은 PostgreSQL pg_trgm이 필요해서 실제 검색 테스트는 TEST_DATABASE_URL이 있을 때만 돈다(사용자 확인).
SQLite에서는 "검색을 못 쓴다는 응답(503)"과 DB가 필요 없는 부분(낱말 뽑기 · 발췌 · 노트 상세)만 확인한다.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.notes import MAX_NOTE_ID
from app.api.search import TIMEOUT_DETAIL
from app.config import MAX_SEARCH_QUERY_CHARS, MAX_SEARCH_RESULTS, MAX_SEARCH_TERMS, SESSION_COOKIE_NAME, Settings
from app.db.models import SearchLog
from app.main import app
from app.search import SearchHit, SearchQuery, SearchTimeoutError, extract_terms, get_searcher, make_excerpt
from app.search import keyword as keyword_module
from app.services.auth_service import GoogleProfile, create_session_token, get_or_create_google_user
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user, delete_user_account

ON_POSTGRES = bool(os.getenv("TEST_DATABASE_URL", "").strip())


def list_search_logs_for_user(db: Session, *, user_id: int) -> list[SearchLog]:
    """사용자의 검색 로그(오래된 순). 테스트에서만 쓰므로 운영 코드가 아니라 여기에 둔다(F-003 1차 리뷰 J)."""
    stmt = select(SearchLog).where(SearchLog.user_id == user_id).order_by(SearchLog.id.asc())
    return list(db.execute(stmt).scalars().all())
needs_postgres = pytest.mark.skipif(not ON_POSTGRES, reason="키워드 검색(pg_trgm)은 PostgreSQL에서만 시험한다")

REACT_NOTE = """# React 정리

## useEffect
useEffect는 컴포넌트가 그려진 뒤 부수 효과를 실행해요.
의존성 배열이 바뀔 때만 다시 실행돼요.

## useState
상태를 바꾸면 컴포넌트가 다시 그려져요.
"""

DB_NOTE = """# 데이터베이스

## 인덱스
인덱스는 조회를 빠르게 하지만 쓰기를 느리게 해요.

## 트랜잭션
트랜잭션은 여러 작업을 하나로 묶어요.
"""


def _login(client: TestClient, db: Session, settings: Settings, sub: str) -> int:
    user = get_or_create_google_user(db, GoogleProfile(sub=sub, email=f"{sub}@example.com", name=sub))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user.id, settings.session_secret))
    return user.id


def _add_note(db: Session, user_id: int, content: str, title: str) -> int:
    note = create_note_for_user(db, user_id=user_id, title=title, content=content, chunks=split_markdown(content))
    return note.id


# --- 낱말 뽑기 · 발췌 (DB 없음) ----------------------------------------------


def test_terms_drop_short_and_duplicate_words_and_keep_korean() -> None:
    assert extract_terms("useEffect를 언제 a 쓰나요? UseEffect를") == ("useEffect를", "언제", "쓰나요")
    assert extract_terms("?! , .") == ()


def test_terms_are_capped() -> None:
    many = " ".join(f"낱말{index}" for index in range(MAX_SEARCH_TERMS + 5))
    assert len(extract_terms(many)) == MAX_SEARCH_TERMS


def test_excerpt_starts_near_the_first_term_and_reports_the_form_found_in_text() -> None:
    content = "앞" * 300 + "\n\nuseEffect는 부수 효과를 실행해요.\n" + "뒤" * 300
    excerpt, matched = make_excerpt(content, ["useEffect를"])  # 조사가 다른 낱말 → 끝 글자를 떼어 찾음
    assert matched == ["useEffect"]
    assert "useEffect는 부수 효과를 실행해요." in excerpt
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert "\n" not in excerpt


def test_excerpt_without_exact_match_shows_the_beginning() -> None:
    excerpt, matched = make_excerpt("짧은 조각", ["없는낱말"])
    assert (excerpt, matched) == ("짧은 조각", [])


# --- API: 로그인 · 입력 검사 ---------------------------------------------------


def test_search_requires_login(client: TestClient) -> None:
    assert client.get("/api/search", params={"q": "useEffect"}).status_code == 401


def test_search_rejects_blank_and_too_long_queries(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    _login(client, db_session, test_settings, "s-input")
    assert client.get("/api/search", params={"q": "   "}).status_code == 400
    assert client.get("/api/search", params={"q": "가" * (MAX_SEARCH_QUERY_CHARS + 1)}).status_code == 422
    assert client.get("/api/search", params={"q": "a", "limit": MAX_SEARCH_RESULTS + 1}).status_code == 422
    assert client.get("/api/search", params={"q": "a", "limit": 0}).status_code == 422


@pytest.mark.skipif(ON_POSTGRES, reason="SQLite에서만: pg_trgm이 없으면 503")
def test_search_on_sqlite_says_unavailable(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    _login(client, db_session, test_settings, "s-sqlite")
    response = client.get("/api/search", params={"q": "useEffect"})
    assert response.status_code == 503
    assert response.json()["detail"] == "지금은 기록 검색을 쓸 수 없어요."


# --- API: 노트 상세 (완료 기준 3의 서버 쪽) ----------------------------------------


def test_note_detail_returns_content_and_chunk_locations(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "s-detail")
    note_id = _add_note(db_session, user_id, REACT_NOTE, "React 정리")

    response = client.get(f"/api/notes/{note_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "React 정리"
    assert body["content"] == REACT_NOTE
    assert [chunk["heading_path"] for chunk in body["chunks"]] == ["# React 정리 > ## useEffect", "# React 정리 > ## useState"]
    for chunk in body["chunks"]:
        assert "## use" in body["content"][chunk["start_offset"] : chunk["end_offset"]]


def test_note_detail_hides_other_users_notes(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    owner = get_or_create_google_user(db_session, GoogleProfile(sub="s-owner", email="o@example.com", name="O"))
    note_id = _add_note(db_session, owner.id, REACT_NOTE, "React 정리")
    _login(client, db_session, test_settings, "s-other")

    assert client.get(f"/api/notes/{note_id}").status_code == 404
    assert client.get("/api/notes/999999").status_code == 404


@pytest.mark.parametrize("note_id", [0, -1, MAX_NOTE_ID + 1, 10**20])
def test_note_ids_outside_the_db_range_are_simply_not_found(
    client: TestClient, db_session: Session, test_settings: Settings, note_id: int
) -> None:
    """PostgreSQL integer 범위를 넘는 번호는 DB에 묻지 않고 404(전에는 DB 범위 초과로 500, 1차 리뷰 E)."""
    _login(client, db_session, test_settings, "s-range")
    response = client.get(f"/api/notes/{note_id}")
    assert (response.status_code, response.json()["detail"]) == (404, "노트를 찾을 수 없어요.")


def test_note_detail_requires_login(client: TestClient) -> None:
    assert client.get("/api/notes/1").status_code == 401


# --- 검색 방식 갈아 끼우기 (완료 기준 6) -------------------------------------------


class _FakeSearcher:
    """검색 방식을 바꿔 끼워도 API · 로그가 그대로 도는지 보는 가짜 방식(DB 종류와 상관없이 돈다)."""

    method = "fake"

    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.seen: list[tuple[int, SearchQuery, int]] = []

    def search(self, db: Session, *, user_id: int, query: SearchQuery, limit: int) -> list[SearchHit]:
        self.seen.append((user_id, query, limit))
        return self.hits[:limit]


def test_search_method_can_be_swapped_and_is_logged(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "s-fake")
    hit = SearchHit(
        chunk_id=7, note_id=3, note_title="노트", heading_path="# 제목", start_offset=0, end_offset=9,
        content="useEffect는 효과", score=0.5,
    )
    fake = _FakeSearcher([hit])
    app.dependency_overrides[get_searcher] = lambda: fake

    response = client.get("/api/search", params={"q": "  useEffect를 써요  ", "limit": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "fake"
    assert body["query"] == "useEffect를 써요"
    assert body["terms"] == ["useEffect를", "써요"]
    assert body["results"][0]["matched_terms"] == ["useEffect"]
    assert fake.seen[0][0] == user_id and fake.seen[0][2] == 3

    [log] = list_search_logs_for_user(db_session, user_id=user_id)
    assert (log.query, log.method, log.results) == ("useEffect를 써요", "fake", [{"chunk_id": 7, "score": 0.5}])


def test_results_are_still_returned_when_saving_the_log_fails(
    client: TestClient, db_session: Session, test_settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """로그 저장이 실패해도 롤백하고 결과는 그대로 돌려준다. 실패 로그에는 검색어를 쓰지 않는다(1차 리뷰 C)."""
    user_id = _login(client, db_session, test_settings, "s-logfail")
    hit = SearchHit(
        chunk_id=7, note_id=3, note_title="노트", heading_path="", start_offset=0, end_offset=5, content="비밀 메모", score=1.0
    )
    app.dependency_overrides[get_searcher] = lambda: _FakeSearcher([hit])
    rolled_back: list[bool] = []
    original_rollback = db_session.rollback

    def failing_commit() -> None:
        raise OperationalError("INSERT", {}, Exception("db down"))

    def tracking_rollback() -> None:
        rolled_back.append(True)
        original_rollback()

    monkeypatch.setattr(db_session, "commit", failing_commit)
    monkeypatch.setattr(db_session, "rollback", tracking_rollback)

    response = client.get("/api/search", params={"q": "비밀 메모"})

    assert response.status_code == 200
    assert [result["chunk_id"] for result in response.json()["results"]] == [7]
    assert rolled_back == [True]
    assert list_search_logs_for_user(db_session, user_id=user_id) == []
    assert "검색 로그 저장 실패" in caplog.text
    assert "비밀" not in caplog.text


class _TimeoutSearcher:
    method = "slow"

    def search(self, db: Session, *, user_id: int, query: SearchQuery, limit: int) -> list[SearchHit]:
        raise SearchTimeoutError("느림")


def test_search_over_the_time_limit_says_so_and_is_not_logged(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "s-slow")
    app.dependency_overrides[get_searcher] = lambda: _TimeoutSearcher()

    response = client.get("/api/search", params={"q": "useEffect"})

    assert (response.status_code, response.json()["detail"]) == (503, TIMEOUT_DETAIL)
    assert list_search_logs_for_user(db_session, user_id=user_id) == []


@needs_postgres
def test_slow_query_is_stopped_by_the_time_limit_and_settings_end_with_the_transaction(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검색 설정(시간 상한)은 그 트랜잭션에만 걸리고, 넘기면 SearchTimeoutError + 세션은 다시 쓸 수 있다(1차 리뷰 A)."""
    before = db_session.execute(text("SHOW statement_timeout")).scalar_one()
    db_session.commit()
    monkeypatch.setattr(keyword_module, "SEARCH_TIMEOUT_MS", 50)

    with pytest.raises(SearchTimeoutError):
        keyword_module.run_with_search_settings(db_session, select(func.pg_sleep(1)))

    assert db_session.execute(select(func.count()).select_from(SearchLog)).scalar_one() == 0  # 세션을 다시 쓸 수 있음
    assert db_session.execute(text("SHOW statement_timeout")).scalar_one() == before  # rollback으로 원래 값

    keyword_module.run_with_search_settings(db_session, select(func.pg_sleep(0)))
    assert db_session.execute(text("SHOW statement_timeout")).scalar_one() == "50ms"  # 같은 트랜잭션 안에서는 걸려 있음
    db_session.commit()
    assert db_session.execute(text("SHOW statement_timeout")).scalar_one() == before  # 트랜잭션이 끝나면 원래 값


# --- 키워드 검색 (PostgreSQL) -------------------------------------------------


@needs_postgres
def test_word_query_finds_the_chunk_with_note_title_heading_and_location(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "s-word")
    note_id = _add_note(db_session, user_id, REACT_NOTE, "React 정리")
    _add_note(db_session, user_id, DB_NOTE, "데이터베이스")

    response = client.get("/api/search", params={"q": "useEffect를"})  # 원문은 "useEffect는"

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "keyword"
    top = body["results"][0]
    assert (top["note_id"], top["note_title"], top["heading_path"]) == (note_id, "React 정리", "# React 정리 > ## useEffect")
    assert REACT_NOTE[top["start_offset"] : top["end_offset"]].startswith("## useEffect")
    assert top["matched_terms"] == ["useEffect"]
    assert all(result["note_id"] == note_id for result in body["results"])  # 데이터베이스 노트는 안 걸림


@needs_postgres
def test_sentence_query_ranks_the_chunk_matching_more_words_first(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "s-sentence")
    _add_note(db_session, user_id, DB_NOTE, "데이터베이스")

    response = client.get("/api/search", params={"q": "인덱스가 조회를 빠르게 하나요"})

    results = response.json()["results"]
    assert results[0]["heading_path"] == "# 데이터베이스 > ## 인덱스"
    assert results[0]["score"] > (results[1]["score"] if len(results) > 1 else 0)


@needs_postgres
def test_other_users_chunks_never_appear(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    owner = get_or_create_google_user(db_session, GoogleProfile(sub="s-a", email="a@example.com", name="A"))
    _add_note(db_session, owner.id, REACT_NOTE, "A의 React")
    user_id = _login(client, db_session, test_settings, "s-b")
    my_note_id = _add_note(db_session, user_id, REACT_NOTE + "\n내 메모\n", "B의 React")

    results = client.get("/api/search", params={"q": "useEffect"}).json()["results"]

    assert results
    assert {result["note_id"] for result in results} == {my_note_id}


@needs_postgres
def test_results_are_capped_at_five(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    user_id = _login(client, db_session, test_settings, "s-cap")
    sections = "\n".join(f"## 절 {index}\nuseEffect 정리 {index}\n" for index in range(MAX_SEARCH_RESULTS + 3))
    _add_note(db_session, user_id, f"# 많은 절\n{sections}", "많은 절")

    results = client.get("/api/search", params={"q": "useEffect"}).json()["results"]

    assert len(results) == MAX_SEARCH_RESULTS


@needs_postgres
def test_no_match_returns_empty_results_and_is_still_logged(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "s-none")
    _add_note(db_session, user_id, REACT_NOTE, "React 정리")

    for query in ["쿠버네티스", "a ?"]:  # 맞는 조각 없음 / 쓸 낱말 없음
        response = client.get("/api/search", params={"q": query})
        assert response.status_code == 200
        assert response.json()["results"] == []

    assert [(log.query, log.results) for log in list_search_logs_for_user(db_session, user_id=user_id)] == [
        ("쿠버네티스", []),
        ("a ?", []),
    ]


@needs_postgres
def test_search_log_keeps_ranked_chunk_ids_and_scores_and_goes_with_the_user(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "s-log")
    _add_note(db_session, user_id, REACT_NOTE, "React 정리")

    results = client.get("/api/search", params={"q": "컴포넌트 상태"}).json()["results"]

    [log] = list_search_logs_for_user(db_session, user_id=user_id)
    assert log.method == "keyword"
    assert [entry["chunk_id"] for entry in log.results] == [result["chunk_id"] for result in results]
    assert all(0 < entry["score"] for entry in log.results)

    delete_user_account(db_session, user_id=user_id)
    assert db_session.execute(select(SearchLog)).scalars().all() == []
