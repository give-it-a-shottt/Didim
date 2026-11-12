"""F-005 노션 연결 테스트.

실제 노션을 부르지 않는다. httpx.MockTransport로 만든 가짜 노션 서버(FakeNotion)가 토큰 교환 · 갱신(갱신 토큰 교체) ·
검색 · 페이지 · 블록(페이지 넘김)을 흉내 낸다.

① 블록 → 마크다운 변환(순수 함수)
② 클라이언트: Basic 인증 · invalid_grant · 429 Retry-After · 5xx 재시도 · 호출 간격
③ 연결: connect → callback(state 확인 · 다른 사용자 state 거부) → 암호화 저장 → 상태 · 끊기
④ 토큰: 401 뒤 갱신(교체 저장) · 만료 임박 미리 갱신 · 갱신 실패면 끊김 · 그새 바뀐 토큰 재사용
⑤ 페이지 목록 · 가져오기: 중첩 · 페이지 넘김 · 건너뛴 블록 · 중복 · 공유 안 됨 · 상한 · 시간 예산 · 도중 끊김
⑥ 사용자 분리(D-004)
⑦ 1차 리뷰 반영: 읽는 도중 예산 초과 한 번만 실패 · 호출 안 마감 · 토큰 요청 재시도 안 함 · 갱신 실패 종류별 응답 ·
   502(노션 다운 · 검색 권한 없음) · 도중 다른 창 끊기 · 사용자당 가져오기 하나 · 그새 재연결이면 끊김 처리 안 함 ·
   끊기 때 토큰 회수 · 비로그인 /login · 비ASCII state · 번호 길이 · 목록 잘림 · 블록 번호 검사
"""

import base64
import dataclasses
import json
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.deps import get_settings
from app.api.notion import get_notion_client
from app.config import (
    NOTION_IMPORT_CLAIM_STALE_SECONDS,
    NOTION_STATE_COOKIE_NAME,
    NOTION_STATE_MAX_AGE_SECONDS,
    NOTION_STATUS_BROKEN,
    NOTION_STATUS_CONNECTED,
    SESSION_COOKIE_NAME,
    Settings,
)
from app.db.models import Chunk, Note, NotionConnection
from app.importers.notion import page_title, render_notion_page
from app.main import app
from app.notion.client import (
    NotionAuthError,
    NotionClient,
    NotionDeadlineError,
    NotionOAuthError,
    NotionTokens,
    NotionUnavailableError,
)
from app.services.auth_service import (
    GoogleProfile,
    create_notion_state_token,
    create_session_token,
    get_or_create_google_user,
)
from app.services.note_service import create_note_for_user
from app.services.chunking import split_markdown
from app.services import notion_service
from app.services.notion_service import (
    TIME_BUDGET_REASON,
    NotionReconnectRequiredError,
    NotionSession,
    import_pages,
    normalize_page_id,
    save_connection,
)
from app.services.token_crypto import decrypt_token

CLIENT_ID = "test-notion-client"
TOGGLE_ID = "7099e1e0-0000-4000-8000-0000000000aa"
CLIENT_SECRET = "test-notion-secret"


def _rt(text: str, *, code: bool = False) -> list[dict[str, Any]]:
    return [{"type": "text", "plain_text": text, "annotations": {"code": code}}]


def _block(block_type: str, text: str = "", *, block_id: str | None = None, has_children: bool = False, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"rich_text": _rt(text)} if text or block_type not in ("divider", "image") else {}
    data.update(extra)
    return {
        "object": "block",
        "id": block_id or f"blk-{block_type}-{abs(hash(text)) % 100000}",
        "type": block_type,
        "has_children": has_children,
        block_type: data,
    }


def _uuid(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-{n:012x}"


def _page(page_id: str, title: str, *, in_trash: bool = False, edited: str = "2026-11-10T00:00:00.000Z") -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "in_trash": in_trash,
        "last_edited_time": edited,
        "properties": {"Name": {"id": "title", "type": "title", "title": _rt(title)}},
    }


# ---------------------------------------------------------------- 가짜 노션


class FakeNotion:
    """토큰 · 페이지 · 블록을 가진 가짜 노션. 갱신하면 접근 · 갱신 토큰이 모두 바뀐다(노션과 같음)."""

    def __init__(self) -> None:
        self.access_tokens: set[str] = set()
        self.refresh_tokens: dict[str, str] = {}  # refresh → 짝인 access
        self.pages: dict[str, dict[str, Any]] = {}
        self.children: dict[str, list[dict[str, Any]]] = {}
        self.page_size = 100
        self.calls: list[str] = []
        self.issued = 0
        self.expires_in: int | None = None
        self.fail_next: list[int] = []  # 다음 응답 상태(429 · 500 등)를 차례로 끼워 넣음
        self.code_ok = "good-code"
        self.search_has_more = False
        self.search_status = 200  # 403이면 통합에 '콘텐츠 읽기' 권한이 없는 경우 흉내
        self.revoked: list[str] = []

    def issue(self) -> tuple[str, str]:
        self.issued += 1
        access, refresh = f"access-{self.issued}", f"refresh-{self.issued}"
        self.access_tokens.add(access)
        self.refresh_tokens[refresh] = access
        return access, refresh

    def revoke_access(self, access: str) -> None:
        self.access_tokens.discard(access)

    def add_page(self, page_id: str, title: str, blocks: list[dict[str, Any]], **kwargs: Any) -> None:
        self.pages[page_id] = _page(page_id, title, **kwargs)
        self.children[page_id] = blocks

    def _token_body(self, access: str, refresh: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "bot_id": "bot-1",
            "workspace_id": "ws-1",
            "workspace_name": "내 워크스페이스",
            "owner": {"type": "user"},
        }
        if self.expires_in is not None:
            body["expires_in"] = self.expires_in
        return body

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1")
        self.calls.append(f"{request.method} {path}")
        if self.fail_next:
            status = self.fail_next.pop(0)
            headers = {"Retry-After": "2"} if status == 429 else {}
            return httpx.Response(status, headers=headers, json={"object": "error"})

        if path in ("/oauth/token", "/oauth/revoke") and request.headers.get("Authorization") != (
            "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        ):
            return httpx.Response(401, json={"error": "invalid_client"})
        if path == "/oauth/token":
            expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
            if request.headers.get("Authorization") != f"Basic {expected}":
                return httpx.Response(401, json={"error": "invalid_client"})
            body = json.loads(request.content)
            if body.get("grant_type") == "authorization_code":
                if body.get("code") != self.code_ok or body.get("redirect_uri") != "http://localhost:3000/api/notion/callback":
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json=self._token_body(*self.issue()))
            if body.get("grant_type") == "refresh_token":
                old_access = self.refresh_tokens.pop(body.get("refresh_token"), None)
                if old_access is None:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.revoke_access(old_access)
                return httpx.Response(200, json=self._token_body(*self.issue()))
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        if path == "/oauth/revoke":
            token = json.loads(request.content).get("token")
            self.revoked.append(token)
            self.revoke_access(token)
            return httpx.Response(200, json={"request_id": "r-1"})

        auth = request.headers.get("Authorization", "")
        if request.headers.get("Notion-Version") != "2026-03-11":
            return httpx.Response(400, json={"code": "missing_version"})
        if auth.removeprefix("Bearer ") not in self.access_tokens:
            return httpx.Response(401, json={"code": "unauthorized"})

        if path == "/search":
            if self.search_status != 200:
                return httpx.Response(self.search_status, json={"code": "restricted_resource"})
            return httpx.Response(200, json={"results": list(self.pages.values()), "has_more": self.search_has_more})
        if path.startswith("/pages/"):
            page = self.pages.get(path.removeprefix("/pages/"))
            return httpx.Response(200, json=page) if page else httpx.Response(404, json={"code": "object_not_found"})
        if path.startswith("/blocks/") and path.endswith("/children"):
            block_id = path.removeprefix("/blocks/").removesuffix("/children")
            if block_id not in self.children:
                return httpx.Response(404, json={"code": "object_not_found"})
            items = self.children[block_id]
            start = int(request.url.params.get("start_cursor") or 0)
            end = start + self.page_size
            has_more = end < len(items)
            return httpx.Response(
                200,
                json={"results": items[start:end], "has_more": has_more, "next_cursor": str(end) if has_more else None},
            )
        return httpx.Response(404, json={"code": "not_found"})


def _client_for(fake: FakeNotion, sleeps: list[float] | None = None) -> NotionClient:
    return NotionClient(
        transport=httpx.MockTransport(fake.handle),
        min_interval=0,
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
    )


@pytest.fixture()
def fake() -> FakeNotion:
    return FakeNotion()


@pytest.fixture()
def notion_settings(test_settings: Settings) -> Settings:
    return dataclasses.replace(
        test_settings,
        notion_client_id=CLIENT_ID,
        notion_client_secret=CLIENT_SECRET,
        notion_token_key=Fernet.generate_key().decode(),
    )


@pytest.fixture()
def api(client: TestClient, notion_settings: Settings, fake: FakeNotion) -> Generator[TestClient, None, None]:
    """노션 설정이 들어간 서버 + 가짜 노션."""
    app.dependency_overrides[get_settings] = lambda: notion_settings

    def _override() -> Generator[NotionClient, None, None]:
        notion = _client_for(fake)
        try:
            yield notion
        finally:
            notion.close()

    app.dependency_overrides[get_notion_client] = _override
    yield client


def _user(db: Session, sub: str) -> int:
    return get_or_create_google_user(db, GoogleProfile(sub=sub, email=f"{sub}@example.com", name=sub)).id


def _login(client: TestClient, db: Session, settings: Settings, sub: str) -> int:
    user_id = _user(db, sub)
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id, settings.session_secret))
    return user_id


def _connect(db: Session, settings: Settings, fake: FakeNotion, user_id: int) -> tuple[str, str]:
    """콜백을 거치지 않고 연결을 저장한다(토큰 쌍을 돌려줌)."""
    access, refresh = fake.issue()
    tokens = NotionTokens(access, refresh, fake.expires_in, "ws-1", "내 워크스페이스", "bot-1")
    save_connection(db, settings, user_id=user_id, tokens=tokens)
    return access, refresh


def _connection(db: Session, user_id: int) -> NotionConnection | None:
    db.expire_all()
    return db.execute(select(NotionConnection).where(NotionConnection.user_id == user_id)).scalar_one_or_none()


# ---------------------------------------------------------------- ① 변환


def test_render_shifts_headings_and_keeps_lists_code_tables() -> None:
    blocks = [
        _block("heading_1", "개요"),
        _block("paragraph", "인덱스는 `B-Tree`로 만든다."),
        _block(
            "bulleted_list_item",
            "첫째",
            has_children=True,
        )
        | {"children": [_block("bulleted_list_item", "안쪽")]},
        _block("numbered_list_item", "하나"),
        _block("numbered_list_item", "둘"),
        _block("to_do", "할 일", checked=True),
        _block("heading_2", "코드"),
        {"type": "code", "id": "c1", "has_children": False, "code": {"rich_text": _rt("SELECT 1;"), "language": "sql"}},
        {"type": "divider", "id": "d1", "has_children": False, "divider": {}},
        _block("quote", "인용 한 줄"),
        {
            "type": "table",
            "id": "t1",
            "has_children": True,
            "table": {"has_column_header": True},
            "children": [
                {"type": "table_row", "table_row": {"cells": [_rt("이름"), _rt("값")]}},
                {"type": "table_row", "table_row": {"cells": [_rt("a|b"), _rt("1")]}},
            ],
        },
        {"type": "image", "id": "i1", "has_children": False, "image": {}},
        {"type": "child_page", "id": "cp1", "has_children": True, "child_page": {"title": "하위"}},
        {"type": "table_of_contents", "id": "toc", "has_children": False, "table_of_contents": {}},
    ]
    result = render_notion_page("인덱스 정리", blocks)
    content = result.document.content
    assert content.startswith("# 인덱스 정리\n\n## 개요\n\n인덱스는 `B-Tree`로 만든다.")
    assert "- 첫째\n  - 안쪽\n1. 하나\n2. 둘\n- [x] 할 일" in content
    assert "### 코드\n\n```sql\nSELECT 1;\n```\n\n---\n\n> 인용 한 줄" in content
    assert "| 이름 | 값 |\n| --- | --- |\n| a\\|b | 1 |" in content
    assert result.skipped_blocks == 2  # 이미지 · 하위 페이지 (목차는 세지 않음)
    assert result.document.source == "notion"
    assert result.document.title == "인덱스 정리"


def test_render_toggle_children_paragraph_hash_and_empty_title() -> None:
    blocks = [
        _block("toggle", "펼쳐 보기", has_children=True) | {"children": [_block("paragraph", "숨은 내용")]},
        _block("paragraph", "# 글자 샵"),
    ]
    result = render_notion_page("  ", blocks)
    assert result.document.title == "제목 없음"
    assert "펼쳐 보기\n\n숨은 내용\n\n\\# 글자 샵" in result.document.content
    # 마크다운 나누기가 그대로 먹는다(제목 경로 = 제목 없음)
    chunks = split_markdown(result.document.content)
    assert chunks and chunks[0].heading_path.startswith("# 제목 없음")


def test_page_title_reads_title_property_and_normalize_page_id() -> None:
    assert page_title(_page(_uuid(1), "제목\n둘째 줄")) == "제목 둘째 줄"
    assert page_title({"properties": {}}) == "제목 없음"
    compact = "0123456789ABCDEF0123456789abcdef"
    assert normalize_page_id(compact) == "01234567-89ab-cdef-0123-456789abcdef"
    assert normalize_page_id("01234567-89ab-cdef-0123-456789abcdef") == "01234567-89ab-cdef-0123-456789abcdef"
    assert normalize_page_id("../etc/passwd") is None
    assert normalize_page_id("") is None


# ---------------------------------------------------------------- ② 클라이언트


def test_client_exchange_uses_basic_auth_and_maps_invalid_grant(fake: FakeNotion) -> None:
    notion = _client_for(fake)
    tokens = notion.exchange_code(
        "good-code", client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        redirect_uri="http://localhost:3000/api/notion/callback",
    )
    assert tokens.access_token == "access-1" and tokens.workspace_name == "내 워크스페이스"
    with pytest.raises(NotionOAuthError) as bad_code:
        notion.exchange_code("bad", client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
                             redirect_uri="http://localhost:3000/api/notion/callback")
    assert bad_code.value.reason == "invalid_grant"
    with pytest.raises(NotionOAuthError) as bad_client:
        notion.exchange_code("good-code", client_id=CLIENT_ID, client_secret="wrong",
                             redirect_uri="http://localhost:3000/api/notion/callback")
    assert bad_client.value.reason == "invalid_client"


def test_client_retries_429_with_retry_after_then_gives_up(fake: FakeNotion) -> None:
    sleeps: list[float] = []
    notion = _client_for(fake, sleeps)
    access, _ = fake.issue()
    fake.add_page(_uuid(1), "a", [])
    fake.fail_next = [429, 500]
    assert notion.search_pages(access, limit=10)
    assert sleeps == [2.0, 1.0]
    fake.fail_next = [500, 500, 500]
    with pytest.raises(NotionUnavailableError):
        notion.search_pages(access, limit=10)


def test_client_keeps_minimum_interval_between_requests(fake: FakeNotion) -> None:
    sleeps: list[float] = []
    now = [100.0]
    notion = NotionClient(
        transport=httpx.MockTransport(fake.handle), min_interval=0.34, sleep=sleeps.append, clock=lambda: now[0]
    )
    access, _ = fake.issue()
    notion.search_pages(access, limit=1)
    notion.search_pages(access, limit=1)  # 시계가 그대로 → 0.34초 기다림
    assert sleeps == [pytest.approx(0.34)]


# ---------------------------------------------------------------- ③ 연결


def test_connect_redirects_to_notion_with_state_cookie(api: TestClient, db_session: Session, notion_settings: Settings) -> None:
    _login(api, db_session, notion_settings, "u-connect")
    response = api.get("/api/notion/connect", follow_redirects=False)
    assert response.status_code == 302
    location = urlparse(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://api.notion.com/v1/oauth/authorize"
    query = parse_qs(location.query)
    assert query["owner"] == ["user"] and query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["http://localhost:3000/api/notion/callback"]
    assert query["state"][0] == response.cookies[NOTION_STATE_COOKIE_NAME]
    assert "Path=/api/notion" in response.headers["set-cookie"]


def test_connect_without_server_config_goes_back_to_settings(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    _login(client, db_session, test_settings, "u-noconf")
    response = client.get("/api/notion/connect", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/settings?notion_error=not_configured"
    assert client.get("/api/notion/status").json() == {"configured": False, "status": "none", "workspace_name": None}


def test_callback_saves_encrypted_tokens_and_status(api: TestClient, db_session: Session, notion_settings: Settings) -> None:
    user_id = _login(api, db_session, notion_settings, "u-callback")
    state = api.get("/api/notion/connect", follow_redirects=False).cookies[NOTION_STATE_COOKIE_NAME]
    api.cookies.set(NOTION_STATE_COOKIE_NAME, state, path="/api/notion")
    response = api.get(f"/api/notion/callback?code=good-code&state={state}", follow_redirects=False)
    assert response.headers["location"] == "http://localhost:3000/settings?notion=connected"

    row = _connection(db_session, user_id)
    assert row is not None and row.status == NOTION_STATUS_CONNECTED
    assert row.access_token_enc and "access-1" not in row.access_token_enc  # 평문으로 저장하지 않음
    assert decrypt_token(row.access_token_enc, notion_settings.notion_token_key) == "access-1"
    assert api.get("/api/notion/status").json() == {
        "configured": True, "status": "connected", "workspace_name": "내 워크스페이스",
    }


@pytest.mark.parametrize("case", ["no_cookie", "mismatch", "other_user", "denied"])
def test_callback_rejects_bad_state(api: TestClient, db_session: Session, notion_settings: Settings, case: str) -> None:
    user_id = _login(api, db_session, notion_settings, "u-badstate")
    other_id = _user(db_session, "u-other")
    secret = notion_settings.session_secret
    if case == "other_user":
        # 다른 사용자가 시작한 연결의 state를 내 브라우저에서 끝내려는 경우
        state = create_notion_state_token(other_id, secret, max_age_seconds=NOTION_STATE_MAX_AGE_SECONDS)
        api.cookies.set(NOTION_STATE_COOKIE_NAME, state, path="/api/notion")
        url = f"/api/notion/callback?code=good-code&state={state}"
    elif case == "mismatch":
        api.cookies.set(NOTION_STATE_COOKIE_NAME, create_notion_state_token(user_id, secret, max_age_seconds=60), path="/api/notion")
        url = f"/api/notion/callback?code=good-code&state={create_notion_state_token(user_id, secret, max_age_seconds=60)}"
    elif case == "denied":
        url = "/api/notion/callback?error=access_denied"
    else:
        url = f"/api/notion/callback?code=good-code&state={create_notion_state_token(user_id, secret, max_age_seconds=60)}"
    response = api.get(url, follow_redirects=False)
    expected = "access_denied" if case == "denied" else "invalid_state"
    assert response.headers["location"] == f"http://localhost:3000/settings?notion_error={expected}"
    assert _connection(db_session, user_id) is None


def test_callback_exchange_failure_goes_back_with_reason(api: TestClient, db_session: Session, notion_settings: Settings) -> None:
    user_id = _login(api, db_session, notion_settings, "u-exfail")
    state = create_notion_state_token(user_id, notion_settings.session_secret, max_age_seconds=60)
    api.cookies.set(NOTION_STATE_COOKIE_NAME, state, path="/api/notion")
    response = api.get(f"/api/notion/callback?code=wrong&state={state}", follow_redirects=False)
    assert response.headers["location"] == "http://localhost:3000/settings?notion_error=exchange_failed"
    assert _connection(db_session, user_id) is None


def test_disconnect_keeps_imported_notes(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-disc")
    _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "노트", [_block("paragraph", "남아 있어야 하는 본문")])
    assert api.post("/api/notion/import", json={"page_ids": [_uuid(1)]}).json()["summary"]["notes"] == 1

    assert api.delete("/api/notion/connection").status_code == 204
    assert api.delete("/api/notion/connection").status_code == 204  # 이미 끊김도 204
    assert api.get("/api/notion/status").json()["status"] == "none"
    assert db_session.scalars(select(Note).where(Note.user_id == user_id)).all()
    assert api.get("/api/notion/pages").status_code == 409


# ---------------------------------------------------------------- ④ 토큰


def test_401_refreshes_once_and_saves_rotated_pair(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-refresh")
    access, refresh = _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "a", [])
    fake.revoke_access(access)  # 만료 흉내 — 만료 시각은 모름(expires_in 없음)

    response = api.get("/api/notion/pages")
    assert response.status_code == 200 and len(response.json()["pages"]) == 1
    row = _connection(db_session, user_id)
    assert row is not None
    key = notion_settings.notion_token_key
    assert decrypt_token(row.access_token_enc or "", key) == "access-2"
    assert decrypt_token(row.refresh_token_enc or "", key) == "refresh-2"  # 새 갱신 토큰도 저장
    assert refresh not in fake.refresh_tokens


def test_refresh_invalid_grant_marks_broken_then_reconnect(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-broken")
    access, refresh = _connect(db_session, notion_settings, fake, user_id)
    fake.revoke_access(access)
    fake.refresh_tokens.pop(refresh)  # 갱신 토큰도 회수됨

    response = api.get("/api/notion/pages")
    assert response.status_code == 409 and "다시 연결" in response.json()["detail"]
    row = _connection(db_session, user_id)
    assert row is not None and row.status == NOTION_STATUS_BROKEN and row.access_token_enc is None
    assert api.get("/api/notion/status").json()["status"] == "broken"

    # 다시 연결하면 같은 줄이 connected로
    state = create_notion_state_token(user_id, notion_settings.session_secret, max_age_seconds=60)
    api.cookies.set(NOTION_STATE_COOKIE_NAME, state, path="/api/notion")
    api.get(f"/api/notion/callback?code=good-code&state={state}", follow_redirects=False)
    assert api.get("/api/notion/status").json()["status"] == "connected"
    assert db_session.scalars(select(NotionConnection)).all().__len__() == 1


def test_refreshes_ahead_of_known_expiry(db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _user(db_session, "u-expiry")
    fake.expires_in = 30  # 미리 갱신 여유(60초)보다 짧음
    _connect(db_session, notion_settings, fake, user_id)
    session = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    assert session.call(lambda token: token) == "access-2"
    assert fake.calls.count("POST /oauth/token") == 1


def test_refresh_reuses_token_rotated_by_another_request(db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    """두 요청이 같은 옛 토큰으로 401을 받으면, 늦은 쪽은 갱신하지 않고 먼저 갱신된 토큰을 쓴다."""
    user_id = _user(db_session, "u-race")
    old_access, _ = _connect(db_session, notion_settings, fake, user_id)
    first = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    second = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    fake.revoke_access(old_access)
    assert first.call(lambda token: _client_for(fake).search_pages(token, limit=1)).pages == []
    token_calls = fake.calls.count("POST /oauth/token")
    assert second.call(lambda token: _client_for(fake).search_pages(token, limit=1)).pages == []
    assert fake.calls.count("POST /oauth/token") == token_calls  # 두 번째는 갱신하지 않음
    row = _connection(db_session, user_id)
    assert row is not None and row.status == NOTION_STATUS_CONNECTED


def test_undecryptable_token_is_treated_as_broken(db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _user(db_session, "u-key")
    _connect(db_session, notion_settings, fake, user_id)
    rotated = dataclasses.replace(notion_settings, notion_token_key=Fernet.generate_key().decode())  # 키가 바뀜
    with pytest.raises(NotionReconnectRequiredError):
        NotionSession(db_session, rotated, _client_for(fake), user_id=user_id)
    row = _connection(db_session, user_id)
    assert row is not None and row.status == NOTION_STATUS_BROKEN


# ---------------------------------------------------------------- ⑤ 목록 · 가져오기


def test_pages_list_excludes_trash_and_marks_imported(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-list")
    _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "살아 있는 페이지", [_block("paragraph", "본문 하나 둘 셋")])
    fake.add_page(_uuid(2), "휴지통", [], in_trash=True)

    pages = api.get("/api/notion/pages").json()["pages"]
    assert [p["title"] for p in pages] == ["살아 있는 페이지"]
    assert pages[0]["imported_note_id"] is None

    note_id = api.post("/api/notion/import", json={"page_ids": [_uuid(1)]}).json()["imported"][0]["note_id"]
    assert api.get("/api/notion/pages").json()["pages"][0]["imported_note_id"] == note_id


def test_import_reads_nested_paginated_blocks_and_saves_note(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-import")
    _connect(db_session, notion_settings, fake, user_id)
    fake.page_size = 2  # 블록 목록이 여러 번에 나뉘어 옴
    page_id = _uuid(7)
    fake.add_page(
        page_id,
        "트랜잭션 공부",
        [
            _block("heading_1", "격리 수준"),
            _block("paragraph", "READ COMMITTED는 커밋된 값만 읽는다."),
            _block("toggle", "더 보기", block_id=TOGGLE_ID, has_children=True),
            {"type": "image", "id": "img", "has_children": False, "image": {}},
            _block("paragraph", "마지막 문단입니다."),
        ],
    )
    fake.children[TOGGLE_ID] = [_block("paragraph", "토글 안의 내용은 함께 가져온다.")]

    response = api.post("/api/notion/import", json={"page_ids": [page_id.replace("-", "").upper()], "kind": "project"})
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"notes": 1, "chunks": body["summary"]["chunks"], "duplicates": 0, "failed": 0, "skipped_blocks": 1}
    assert body["imported"][0]["page_id"] == page_id and body["connection_broken"] is False

    note = db_session.get(Note, body["imported"][0]["note_id"])
    assert note is not None and note.user_id == user_id
    assert (note.source, note.kind, note.notion_page_id, note.title) == ("notion", "project", page_id, "트랜잭션 공부")
    assert "## 격리 수준" in note.content and "토글 안의 내용은 함께 가져온다." in note.content
    assert "마지막 문단입니다." in note.content
    chunks = db_session.scalars(select(Chunk).where(Chunk.note_id == note.id)).all()
    assert chunks and all(note.content[c.start_offset:c.end_offset] == c.content for c in chunks)


def test_import_reports_duplicates_not_shared_and_trash(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-dup")
    _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "한 번만", [_block("paragraph", "중복 확인용 본문입니다.")])
    fake.add_page(_uuid(3), "버린 페이지", [], in_trash=True)
    # 같은 내용의 마크다운 노트가 이미 있는 페이지
    same = render_notion_page("같은 내용", [_block("paragraph", "이미 올린 본문입니다.")]).document.content
    create_note_for_user(db_session, user_id=user_id, title="같은 내용", content=same, chunks=split_markdown(same))
    fake.add_page(_uuid(4), "같은 내용", [_block("paragraph", "이미 올린 본문입니다.")])

    assert api.post("/api/notion/import", json={"page_ids": [_uuid(1)]}).json()["summary"]["notes"] == 1
    body = api.post("/api/notion/import", json={"page_ids": [_uuid(1), _uuid(2), _uuid(3), _uuid(4), _uuid(1)]}).json()
    assert [d["page_id"] for d in body["duplicates"]] == [_uuid(1), _uuid(4)]  # 같은 번호 두 번은 한 번만
    reasons = {f["page_id"]: f["reason"] for f in body["failed"]}
    assert "공유했는지" in reasons[_uuid(2)] and "휴지통" in reasons[_uuid(3)]
    assert body["summary"]["notes"] == 0


def test_import_validates_ids_and_count(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-valid")
    _connect(db_session, notion_settings, fake, user_id)
    assert api.post("/api/notion/import", json={"page_ids": ["../../oauth/token"]}).status_code == 422
    assert api.post("/api/notion/import", json={"page_ids": []}).status_code == 422
    assert api.post("/api/notion/import", json={"page_ids": [_uuid(i) for i in range(21)]}).status_code == 422
    assert api.post("/api/notion/import", json={"page_ids": [_uuid(1)], "kind": "auto"}).status_code == 422


def test_import_without_connection_or_config(client: TestClient, api: TestClient, db_session: Session, notion_settings: Settings, test_settings: Settings) -> None:
    _login(api, db_session, notion_settings, "u-none")
    response = api.post("/api/notion/import", json={"page_ids": [_uuid(1)]})
    assert response.status_code == 409 and "설정에서 연결" in response.json()["detail"]
    app.dependency_overrides[get_settings] = lambda: test_settings  # 서버 설정 없음
    assert api.get("/api/notion/pages").status_code == 503


def test_import_fails_page_with_too_many_blocks(db_session: Session, notion_settings: Settings, fake: FakeNotion, monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = _user(db_session, "u-many")
    _connect(db_session, notion_settings, fake, user_id)
    monkeypatch.setattr(notion_service, "NOTION_MAX_BLOCKS_PER_PAGE", 3)
    fake.add_page(_uuid(1), "큰 페이지", [_block("paragraph", f"문단 {i} 입니다") for i in range(5)])
    fake.add_page(_uuid(2), "작은 페이지", [_block("paragraph", "작은 페이지 본문입니다.")])
    session = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    result = import_pages(session, db_session, user_id=user_id, kind="study", page_ids=[_uuid(1), _uuid(2)])
    assert [f.title for f in result.failed] == ["큰 페이지"] and "블록이 너무 많아요" in result.failed[0].reason
    assert [p.title for p in result.imported] == ["작은 페이지"]


def test_import_stops_starting_pages_after_time_budget(db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _user(db_session, "u-budget")
    _connect(db_session, notion_settings, fake, user_id)
    for i in (1, 2, 3):
        fake.add_page(_uuid(i), f"페이지 {i}", [_block("paragraph", f"페이지 {i}의 본문입니다.")])
    now = [0.0]
    original = fake.handle

    def slow_first_page(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/blocks/{_uuid(1)}/children":
            now[0] = 999.0  # 첫 페이지를 읽는 동안 예산을 다 씀 — 그 페이지는 끝까지 저장
        return original(request)

    fake.handle = slow_first_page  # type: ignore[method-assign]
    session = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    result = import_pages(
        session, db_session, user_id=user_id, kind="study",
        page_ids=[_uuid(1), _uuid(2), _uuid(3)], clock=lambda: now[0], time_budget=10.0,
    )
    assert [p.page_id for p in result.imported] == [_uuid(1)]
    assert {f.page_id for f in result.failed} == {_uuid(2), _uuid(3)}
    assert all(f.reason == TIME_BUDGET_REASON for f in result.failed)


def test_connection_breaking_mid_import_keeps_saved_pages(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-mid")
    access, refresh = _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "먼저", [_block("paragraph", "먼저 가져오는 페이지 본문.")])
    fake.add_page(_uuid(2), "나중", [_block("paragraph", "나중 페이지 본문입니다.")])

    original = fake.handle

    def revoke_after_first_page(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/pages/{_uuid(2)}":
            fake.revoke_access(access)
            fake.refresh_tokens.pop(refresh, None)
        return original(request)

    fake.handle = revoke_after_first_page  # type: ignore[method-assign]
    body = api.post("/api/notion/import", json={"page_ids": [_uuid(1), _uuid(2)]}).json()
    assert body["connection_broken"] is True
    assert [p["page_id"] for p in body["imported"]] == [_uuid(1)]
    assert body["failed"][0]["page_id"] == _uuid(2) and "다시 연결" in body["failed"][0]["reason"]
    assert api.get("/api/notion/status").json()["status"] == "broken"


# ---------------------------------------------------------------- ⑥ 사용자 분리


def test_users_never_see_each_others_connection_or_notes(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    a = _login(api, db_session, notion_settings, "u-a")
    _connect(db_session, notion_settings, fake, a)
    fake.add_page(_uuid(1), "A의 페이지", [_block("paragraph", "A만 가져온 본문입니다.")])
    api.post("/api/notion/import", json={"page_ids": [_uuid(1)]})

    b = _login(api, db_session, notion_settings, "u-b")
    assert api.get("/api/notion/status").json()["status"] == "none"
    assert api.get("/api/notion/pages").status_code == 409  # A의 연결을 쓰지 않음
    assert api.post("/api/notion/import", json={"page_ids": [_uuid(1)]}).status_code == 409

    _connect(db_session, notion_settings, fake, b)
    pages = api.get("/api/notion/pages").json()["pages"]
    assert pages[0]["imported_note_id"] is None  # A가 가져온 노트는 B에게 '이미 가져옴'이 아님
    body = api.post("/api/notion/import", json={"page_ids": [_uuid(1)]}).json()
    assert body["summary"]["notes"] == 1  # 같은 페이지라도 B의 노트로 따로 저장
    assert api.delete("/api/notion/connection").status_code == 204
    assert _connection(db_session, a) is not None  # B가 끊어도 A의 연결은 그대로
    owners = db_session.scalars(select(Note.user_id).where(Note.notion_page_id == _uuid(1))).all()
    assert sorted(owners) == sorted([a, b])


# ---------------------------------------------------------------- ⑦ 1차 리뷰 반영 (2026-11-12)


def test_time_budget_hit_while_reading_a_page_fails_it_once_with_title(db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    """페이지를 읽는 도중 예산을 넘으면 그 페이지는 제목과 함께 한 번만 실패, 남은 페이지는 제목 없이 실패(리뷰 A)."""
    user_id = _user(db_session, "u-midbudget")
    _connect(db_session, notion_settings, fake, user_id)
    fake.page_size = 1
    fake.add_page(_uuid(1), "긴 페이지", [_block("paragraph", "첫 문단입니다."), _block("paragraph", "둘째 문단입니다.")])
    fake.add_page(_uuid(2), "다음 페이지", [_block("paragraph", "다음 페이지 본문.")])
    now = [0.0]
    original = fake.handle

    def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/blocks/{_uuid(1)}/children":
            now[0] = 999.0  # 블록 첫 묶음을 받는 동안 예산을 다 씀 → 다음 묶음 전에 멈춤
        return original(request)

    fake.handle = slow  # type: ignore[method-assign]
    session = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    result = import_pages(
        session, db_session, user_id=user_id, kind="study",
        page_ids=[_uuid(1), _uuid(2)], clock=lambda: now[0], time_budget=10.0,
    )
    assert [(f.page_id, f.title) for f in result.failed] == [(_uuid(1), "긴 페이지"), (_uuid(2), None)]
    assert result.imported == []


def test_client_deadline_stops_retry_waits_inside_one_call(fake: FakeNotion) -> None:
    """마감이 가까우면 호출 하나 안의 재시도 대기도 하지 않고 멈춘다(리뷰 C)."""
    now = [0.0]
    notion = NotionClient(
        transport=httpx.MockTransport(fake.handle), min_interval=0, sleep=lambda _s: None, clock=lambda: now[0]
    )
    access, _ = fake.issue()
    notion.set_time_budget(5.0)
    fake.fail_next = [429]  # Retry-After 2초 — 남은 5초 안이라 기다린 뒤 다시
    assert notion.search_pages(access, limit=1).pages == []
    now[0] = 4.5  # 남은 0.5초 — 새 요청을 보내지 않음
    with pytest.raises(NotionDeadlineError):
        notion.search_pages(access, limit=1)
    notion.set_time_budget(1.8)  # 요청은 보내지만(남은 1.8초), 500 뒤 1초를 기다리면 마감 1초 안쪽 → 기다리지 않고 멈춤
    fake.fail_next = [500]
    with pytest.raises(NotionDeadlineError):
        notion.search_pages(access, limit=1)
    notion.set_time_budget(None)
    assert notion.search_pages(access, limit=1).pages == []


def test_token_requests_are_not_retried(fake: FakeNotion) -> None:
    """토큰 요청은 다시 보내지 않는다 — 응답만 잃었는데 다시 보내면 바뀐 갱신 토큰이라 끊김이 될 수 있다(리뷰 R2)."""
    notion = _client_for(fake)
    _, refresh = fake.issue()
    previous = NotionTokens("a", refresh, None, "ws-1", "w", "bot-1")
    fake.fail_next = [500]
    with pytest.raises(NotionOAuthError) as failed:
        notion.refresh(refresh, client_id=CLIENT_ID, client_secret=CLIENT_SECRET, previous=previous)
    assert failed.value.reason == "failed"
    assert fake.calls.count("POST /oauth/token") == 1
    assert refresh in fake.refresh_tokens  # 노션 쪽 갱신 토큰은 그대로


def test_refresh_failure_kinds_map_to_502_and_503(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-refresh-kinds")
    access, _ = _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "a", [])
    fake.revoke_access(access)
    fake.fail_next = [401, 500]  # 첫 검색 401 → 갱신이 500(일시 오류)
    assert api.get("/api/notion/pages").status_code == 502
    row = _connection(db_session, user_id)
    assert row is not None and row.status == NOTION_STATUS_CONNECTED

    app.dependency_overrides[get_settings] = lambda: dataclasses.replace(notion_settings, notion_client_secret="wrong")
    assert api.get("/api/notion/pages").status_code == 503  # 갱신이 invalid_client — 서버 설정 문제
    row = _connection(db_session, user_id)
    assert row is not None and row.status == NOTION_STATUS_CONNECTED


def test_pages_502_when_notion_down_or_search_forbidden(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-502")
    _connect(db_session, notion_settings, fake, user_id)
    fake.fail_next = [500, 500, 500]
    assert api.get("/api/notion/pages").status_code == 502
    fake.search_status = 403  # 통합에 '콘텐츠 읽기' 권한이 없음 — 500이 아니라 이유와 함께 502 (리뷰 B)
    response = api.get("/api/notion/pages")
    assert response.status_code == 502 and "콘텐츠 읽기" in response.json()["detail"]


def test_disconnect_in_another_tab_mid_import_is_reported_not_500(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    """가져오는 도중 다른 창에서 연결을 끊으면 저장한 페이지는 남기고 connection_broken (리뷰 B)."""
    user_id = _login(api, db_session, notion_settings, "u-tab")
    access, _ = _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "먼저", [_block("paragraph", "먼저 가져오는 페이지 본문.")])
    fake.add_page(_uuid(2), "나중", [_block("paragraph", "나중 페이지 본문입니다.")])
    original = fake.handle

    def disconnect_elsewhere(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/pages/{_uuid(2)}":
            db_session.execute(NotionConnection.__table__.delete().where(NotionConnection.user_id == user_id))
            db_session.commit()
            fake.revoke_access(access)
        return original(request)

    fake.handle = disconnect_elsewhere  # type: ignore[method-assign]
    response = api.post("/api/notion/import", json={"page_ids": [_uuid(1), _uuid(2)]})
    assert response.status_code == 200
    body = response.json()
    assert body["connection_broken"] is True and [p["page_id"] for p in body["imported"]] == [_uuid(1)]


def test_one_import_per_user(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    """사용자당 가져오기 하나(리뷰 D). 오래된 표시는 새 요청이 가져가고, 끝나면 표시를 푼다."""
    user_id = _login(api, db_session, notion_settings, "u-claim")
    _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "페이지", [_block("paragraph", "가져올 본문입니다.")])
    row = _connection(db_session, user_id)
    assert row is not None
    row.importing_since = datetime.now(timezone.utc)
    db_session.commit()
    response = api.post("/api/notion/import", json={"page_ids": [_uuid(1)]})
    assert response.status_code == 409 and "이미 노션 페이지를 가져오고" in response.json()["detail"]

    row = _connection(db_session, user_id)
    assert row is not None
    row.importing_since = datetime.now(timezone.utc) - timedelta(seconds=NOTION_IMPORT_CLAIM_STALE_SECONDS + 1)
    db_session.commit()
    assert api.post("/api/notion/import", json={"page_ids": [_uuid(1)]}).json()["summary"]["notes"] == 1
    row = _connection(db_session, user_id)
    assert row is not None and row.importing_since is None


def test_second_401_does_not_wipe_a_connection_renewed_meanwhile(db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    """갱신한 토큰도 401일 때, 그새 다시 연결해 토큰이 바뀌었으면 끊김으로 바꾸지 않는다(리뷰 R2)."""
    user_id = _user(db_session, "u-renewed")
    _connect(db_session, notion_settings, fake, user_id)
    session = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    calls = [0]

    def always_401(_token: str) -> None:
        calls[0] += 1
        if calls[0] == 2:
            _connect(db_session, notion_settings, fake, user_id)  # 다른 창에서 다시 연결
        raise NotionAuthError("401")

    with pytest.raises(NotionUnavailableError):
        session.call(always_401)
    row = _connection(db_session, user_id)
    assert row is not None and row.status == NOTION_STATUS_CONNECTED

    def plain_401(_token: str) -> None:
        raise NotionAuthError("401")

    session = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    with pytest.raises(NotionReconnectRequiredError):
        session.call(plain_401)
    row = _connection(db_session, user_id)
    assert row is not None and row.status == NOTION_STATUS_BROKEN


def test_disconnect_also_revokes_token_at_notion(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-revoke")
    access, _ = _connect(db_session, notion_settings, fake, user_id)
    assert api.delete("/api/notion/connection").status_code == 204
    assert fake.revoked == [access] and _connection(db_session, user_id) is None

    # 회수가 실패해도 우리 쪽 토큰은 지운다
    _connect(db_session, notion_settings, fake, user_id)
    fake.fail_next = [500]
    assert api.delete("/api/notion/connection").status_code == 204
    assert _connection(db_session, user_id) is None


def test_connect_and_callback_send_logged_out_users_to_login(api: TestClient) -> None:
    for path in ("/api/notion/connect", "/api/notion/callback?code=x&state=y"):
        response = api.get(path, follow_redirects=False)
        assert response.status_code == 302 and response.headers["location"] == "http://localhost:3000/login"


def test_non_ascii_state_is_rejected_not_500(api: TestClient, db_session: Session, notion_settings: Settings) -> None:
    user_id = _login(api, db_session, notion_settings, "u-ascii")
    state = create_notion_state_token(user_id, notion_settings.session_secret, max_age_seconds=60)
    api.cookies.set(NOTION_STATE_COOKIE_NAME, state, path="/api/notion")
    response = api.get("/api/notion/callback?code=good-code&state=상태", follow_redirects=False)
    assert response.headers["location"] == "http://localhost:3000/settings?notion_error=invalid_state"


def test_page_id_length_limit_and_truncated_list(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _login(api, db_session, notion_settings, "u-len")
    _connect(db_session, notion_settings, fake, user_id)
    assert api.post("/api/notion/import", json={"page_ids": ["a" * 65]}).status_code == 422
    fake.add_page(_uuid(1), "a", [])
    assert api.get("/api/notion/pages").json()["truncated"] is False
    fake.search_has_more = True  # 100개보다 많음 — 화면이 '최근 100개만' 안내 (리뷰 F)
    assert api.get("/api/notion/pages").json()["truncated"] is True


def test_disconnect_works_even_when_token_key_is_malformed(api: TestClient, db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    """키 형식이 틀려도 [연결 끊기]는 500이 아니라 204 — 회수만 건너뛰고 우리 쪽 토큰은 지운다(2차 리뷰 R1 · R2 · R3)."""
    user_id = _login(api, db_session, notion_settings, "u-badkey")
    _connect(db_session, notion_settings, fake, user_id)
    app.dependency_overrides[get_settings] = lambda: dataclasses.replace(notion_settings, notion_token_key="not-a-fernet-key")
    assert api.delete("/api/notion/connection").status_code == 204
    assert _connection(db_session, user_id) is None and fake.revoked == []


def test_server_config_problem_mid_import_still_returns_saved_pages(db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    """가져오는 도중 갱신이 invalid_client(서버 설정 문제)여도 저장한 페이지 결과를 돌려준다(2차 리뷰 R3 · R4)."""
    user_id = _user(db_session, "u-midconf")
    access, _ = _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "먼저", [_block("paragraph", "먼저 가져오는 페이지 본문.")])
    fake.add_page(_uuid(2), "나중", [_block("paragraph", "나중 페이지 본문입니다.")])
    original = fake.handle

    def expire_after_first(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/pages/{_uuid(2)}":
            fake.revoke_access(access)
        return original(request)

    fake.handle = expire_after_first  # type: ignore[method-assign]
    wrong_secret = dataclasses.replace(notion_settings, notion_client_secret="wrong")  # 갱신이 invalid_client
    session = NotionSession(db_session, wrong_secret, _client_for(fake), user_id=user_id)
    result = import_pages(session, db_session, user_id=user_id, kind="study", page_ids=[_uuid(1), _uuid(2)])
    assert [p.page_id for p in result.imported] == [_uuid(1)]
    assert [f.page_id for f in result.failed] == [_uuid(2)] and "설정" in result.failed[0].reason
    assert result.connection_broken is False
    row = _connection(db_session, user_id)
    assert row is not None and row.status == NOTION_STATUS_CONNECTED  # 서버 설정 문제로 사용자 연결을 끊지 않음


def test_callback_maps_invalid_client_and_save_failure(api: TestClient, db_session: Session, notion_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = _login(api, db_session, notion_settings, "u-cbfail")
    state = create_notion_state_token(user_id, notion_settings.session_secret, max_age_seconds=60)
    api.cookies.set(NOTION_STATE_COOKIE_NAME, state, path="/api/notion")
    app.dependency_overrides[get_settings] = lambda: dataclasses.replace(notion_settings, notion_client_secret="wrong")
    response = api.get(f"/api/notion/callback?code=good-code&state={state}", follow_redirects=False)
    assert response.headers["location"] == "http://localhost:3000/settings?notion_error=not_configured"

    app.dependency_overrides[get_settings] = lambda: notion_settings
    api.cookies.set(NOTION_STATE_COOKIE_NAME, state, path="/api/notion")

    def broken_save(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr("app.api.notion.save_connection", broken_save)
    response = api.get(f"/api/notion/callback?code=good-code&state={state}", follow_redirects=False)
    assert response.headers["location"] == "http://localhost:3000/settings?notion_error=save_failed"
    assert _connection(db_session, user_id) is None


def test_tokens_are_hidden_from_repr() -> None:
    tokens = NotionTokens("secret-access", "secret-refresh", None, "ws-1", "w", "bot-1")
    assert "secret-access" not in repr(tokens) and "secret-refresh" not in repr(tokens)


def test_token_request_is_not_sent_without_enough_time(fake: FakeNotion) -> None:
    """남은 예산이 토큰 요청 시간 상한보다 짧으면 갱신 요청을 아예 보내지 않는다 — 노션만 바뀌고 응답을 잃는 일을 막음(2차 리뷰 R2)."""
    now = [0.0]
    notion = NotionClient(
        transport=httpx.MockTransport(fake.handle), min_interval=0, sleep=lambda _s: None, clock=lambda: now[0]
    )
    _, refresh = fake.issue()
    notion.set_time_budget(5.0)
    with pytest.raises(NotionDeadlineError):
        notion.refresh(refresh, client_id=CLIENT_ID, client_secret=CLIENT_SECRET, previous=NotionTokens("a", refresh, None, "w", "w", "b"))
    assert "POST /oauth/token" not in fake.calls and refresh in fake.refresh_tokens


def test_failure_paths_body_chunks_save_and_db_errors(db_session: Session, notion_settings: Settings, fake: FakeNotion, monkeypatch: pytest.MonkeyPatch) -> None:
    """빈 본문 · 조각 상한 · 저장 실패 · 저장 직전 경합 · 도중 DB 읽기 오류의 이유(3차 리뷰 R3)."""
    from app.services.note_service import DuplicateNoteError

    user_id = _user(db_session, "u-paths")
    _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "빈 페이지", [])
    fake.add_page(_uuid(2), "큰 페이지", [_block("heading_1", "가"), _block("paragraph", "가 본문입니다."), _block("heading_1", "나"), _block("paragraph", "나 본문입니다.")])

    def run(*ids: int) -> list[str]:
        session = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
        result = import_pages(session, db_session, user_id=user_id, kind="study", page_ids=[_uuid(i) for i in ids])
        return [f.reason for f in result.failed]

    monkeypatch.setattr(notion_service, "MAX_CHUNKS_PER_NOTE", 1)
    reasons = run(1, 2)
    assert "본문이 없어요" in reasons[0] and "조각이 너무 많아요" in reasons[1]
    monkeypatch.undo()

    fake.add_page(_uuid(3), "저장 실패", [_block("paragraph", "저장이 실패하는 본문입니다.")])

    def save_fails(*_a: object, **_k: object) -> None:
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr(notion_service, "create_note_for_user", save_fails)
    assert "저장하지 못했어요" in run(3)[0]

    def raced(*_a: object, **_k: object) -> None:
        raise DuplicateNoteError("raced")  # 경합인데 다시 찾아도 없음 → 저장 실패로

    monkeypatch.setattr(notion_service, "create_note_for_user", raced)
    assert "저장하지 못했어요" in run(3)[0]
    monkeypatch.undo()

    fake.add_page(_uuid(4), "넷", [_block("paragraph", "넷째 페이지 본문입니다.")])
    fake.add_page(_uuid(5), "다섯", [_block("paragraph", "다섯째 페이지 본문입니다.")])
    original = notion_service.find_note_by_content_hash_for_user
    calls = [0]

    def read_fails_second_time(*args: object, **kwargs: object) -> object:
        calls[0] += 1
        if calls[0] == 2:
            raise OperationalError("SELECT", {}, Exception("db down"))
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(notion_service, "find_note_by_content_hash_for_user", read_fails_second_time)
    session = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    result = import_pages(session, db_session, user_id=user_id, kind="study", page_ids=[_uuid(4), _uuid(5)])
    assert [p.page_id for p in result.imported] == [_uuid(4)]  # 저장한 페이지 결과는 남음
    assert [(f.page_id, "저장하지 못했어요" in f.reason) for f in result.failed] == [(_uuid(5), True)]


def test_client_retries_connection_errors(fake: FakeNotion) -> None:
    calls = [0]

    def flaky(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        if calls[0] == 1:
            raise httpx.ConnectError("down", request=request)
        return fake.handle(request)

    access, _ = fake.issue()
    notion = NotionClient(transport=httpx.MockTransport(flaky), min_interval=0, sleep=lambda _s: None)
    assert notion.search_pages(access, limit=1).pages == [] and calls[0] == 2


def test_block_ids_are_checked_before_going_into_the_url(db_session: Session, notion_settings: Settings, fake: FakeNotion) -> None:
    user_id = _user(db_session, "u-blockid")
    _connect(db_session, notion_settings, fake, user_id)
    fake.add_page(_uuid(1), "페이지", [_block("toggle", "토글 글자입니다", block_id="../../oauth/token", has_children=True)])
    session = NotionSession(db_session, notion_settings, _client_for(fake), user_id=user_id)
    result = import_pages(session, db_session, user_id=user_id, kind="study", page_ids=[_uuid(1)])
    assert len(result.imported) == 1
    assert not any("oauth" in call for call in fake.calls if call.startswith("GET"))
