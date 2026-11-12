"""노션 연결 API (F-005).

GET    /api/notion/connect     — 노션 동의 화면으로 이동(위조 방지 state 쿠키, 연결을 시작한 사용자 번호를 담음)
GET    /api/notion/callback    — 코드를 토큰으로 바꿔 저장하고 설정 화면으로 돌아감(실패하면 이유를 쿼리로)
GET    /api/notion/status      — 연결 상태(none · connected · broken)와 워크스페이스 이름
DELETE /api/notion/connection  — 연결 끊기(노션에서도 토큰 회수를 시도, 우리 쪽 토큰 삭제, 가져온 노트는 남김)
GET    /api/notion/pages       — 가져올 수 있는 페이지 목록 + '이미 가져옴' + 잘렸는지
POST   /api/notion/import      — 고른 페이지 가져오기(사용자당 하나, 요청 한 번에 처리)

connect · callback은 브라우저가 주소를 직접 여는 이동이라, 비로그인이면 JSON 401 대신 /login으로 보낸다(1차 리뷰 R4).
노션 호출은 동기(httpx.Client)라 엔드포인트도 동기 함수 — FastAPI가 작업 스레드에서 돌려 이벤트 루프를 막지 않는다.
"""

import time
from collections.abc import Generator
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_settings
from app.config import (
    NOTION_API_BASE,
    NOTION_IMPORT_TIME_BUDGET_SECONDS,
    NOTION_MAX_IMPORT_PAGES,
    NOTION_MAX_PAGE_ID_INPUT_CHARS,
    NOTION_STATE_COOKIE_NAME,
    NOTION_STATE_MAX_AGE_SECONDS,
    SESSION_COOKIE_NAME,
    Settings,
)
from app.db.models import User
from app.db.session import get_db
from app.notion.client import NotionClient, NotionNotFoundError, NotionOAuthError, NotionUnavailableError
from app.services.auth_service import SessionConfigError, create_notion_state_token, verify_notion_state_token
from app.services.import_service import NoteKind
from app.services.notion_service import (
    ConnectionState,
    InvalidPageIdError,
    NotionImportInProgressError,
    NotionImportResult,
    NotionNotConfiguredError,
    NotionNotConnectedError,
    NotionReconnectRequiredError,
    NotionSession,
    claim_import,
    disconnect,
    get_connection_status,
    import_pages,
    list_pages,
    normalize_page_ids,
    release_import,
    save_connection,
)
from app.services.token_crypto import TokenKeyError

router = APIRouter(prefix="/notion", tags=["notion"])

STATE_COOKIE_PATH = "/api/notion"
NOT_CONFIGURED_DETAIL = "노션 연결 설정이 아직 안 됐어요."
NOT_CONNECTED_DETAIL = "노션이 연결되어 있지 않아요. 설정에서 연결해 주세요."
RECONNECT_DETAIL = "노션 연결이 끊겼어요. 설정에서 다시 연결해 주세요."
UNAVAILABLE_DETAIL = "노션이 잠시 응답하지 않아요. 잠시 후 다시 시도해 주세요."
NO_ACCESS_DETAIL = "노션이 페이지 목록을 주지 않았어요. 노션에서 디딤 연결의 '콘텐츠 읽기' 권한을 확인해 주세요."
IN_PROGRESS_DETAIL = "이미 노션 페이지를 가져오고 있어요. 끝난 뒤 다시 시도해 주세요."


def get_notion_client() -> Generator[NotionClient, None, None]:
    """요청마다 노션 클라이언트 하나(호출 간격은 요청 안에서 지킨다). 테스트는 가짜 서버를 넣은 것으로 바꿔 끼운다."""
    client = NotionClient()
    try:
        yield client
    finally:
        client.close()


# 노션 · 연결 오류 → HTTP 응답 표(목록 · 가져오기 · 세션 열기가 같이 씀). 잡는 예외 목록도 이 표에서 만든다 —
# 한쪽만 고쳐 500이 나는 일이 없게(3차 리뷰 R1). 위에서부터 처음 맞는 줄을 쓴다.
_ERROR_TABLE: tuple[tuple[tuple[type[Exception], ...], int, str], ...] = (
    ((NotionNotConfiguredError, TokenKeyError), status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED_DETAIL),
    ((NotionNotConnectedError,), status.HTTP_409_CONFLICT, NOT_CONNECTED_DETAIL),
    ((NotionReconnectRequiredError,), status.HTTP_409_CONFLICT, RECONNECT_DETAIL),
    ((NotionImportInProgressError,), status.HTTP_409_CONFLICT, IN_PROGRESS_DETAIL),
    ((NotionNotFoundError,), status.HTTP_502_BAD_GATEWAY, NO_ACCESS_DETAIL),
    ((NotionUnavailableError,), status.HTTP_502_BAD_GATEWAY, UNAVAILABLE_DETAIL),
)
NOTION_ERRORS: tuple[type[Exception], ...] = tuple(kind for kinds, _, _ in _ERROR_TABLE for kind in kinds)


def _http_error(exc: Exception) -> HTTPException:
    for kinds, code, detail in _ERROR_TABLE:
        if isinstance(exc, kinds):
            return HTTPException(status_code=code, detail=detail)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=UNAVAILABLE_DETAIL)


# ---- 연결 (브라우저가 주소를 직접 여는 이동) ----


def _user_or_none(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """로그인했으면 사용자, 아니면 None(주소 이동 경로가 /login으로 보내도록)."""
    try:
        return get_current_user(session_token, db, settings)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return None
        raise


def _login_redirect(settings: Settings) -> RedirectResponse:
    return RedirectResponse(url=f"{settings.frontend_url}/login", status_code=status.HTTP_302_FOUND)


def _settings_redirect(settings: Settings, **query: str) -> RedirectResponse:
    response = RedirectResponse(
        url=f"{settings.frontend_url}/settings?{urlencode(query)}", status_code=status.HTTP_302_FOUND
    )
    response.delete_cookie(key=NOTION_STATE_COOKIE_NAME, path=STATE_COOKIE_PATH)
    return response


@router.get("/connect")
def notion_connect(
    current_user: User | None = Depends(_user_or_none),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """노션 동의 화면(페이지 고르기)으로 보낸다."""
    if current_user is None:
        return _login_redirect(settings)
    if not settings.notion_configured:
        return _settings_redirect(settings, notion_error="not_configured")
    try:
        state = create_notion_state_token(
            current_user.id, settings.session_secret, max_age_seconds=NOTION_STATE_MAX_AGE_SECONDS
        )
    except SessionConfigError:
        return _settings_redirect(settings, notion_error="not_configured")
    query = urlencode(
        {
            "client_id": settings.notion_client_id,
            "redirect_uri": settings.notion_redirect_uri,
            "response_type": "code",
            "owner": "user",
            "state": state,
        }
    )
    response = RedirectResponse(url=f"{NOTION_API_BASE}/oauth/authorize?{query}", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=NOTION_STATE_COOKIE_NAME,
        value=state,
        max_age=NOTION_STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=STATE_COOKIE_PATH,
    )
    return response


@router.get("/callback")
def notion_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    cookie_state: str | None = Cookie(default=None, alias=NOTION_STATE_COOKIE_NAME),
    current_user: User | None = Depends(_user_or_none),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: NotionClient = Depends(get_notion_client),
) -> RedirectResponse:
    """노션이 돌려보낸 코드를 토큰으로 바꿔 지금 로그인한 사용자의 연결로 저장한다."""
    if current_user is None:
        return _login_redirect(settings)
    if error:
        return _settings_redirect(settings, notion_error="access_denied")
    if not settings.notion_configured:
        return _settings_redirect(settings, notion_error="not_configured")
    try:
        state_ok = bool(code and state and cookie_state) and verify_notion_state_token(
            state or "", cookie_state or "", settings.session_secret, user_id=current_user.id
        )
    except SessionConfigError:
        return _settings_redirect(settings, notion_error="not_configured")
    if not state_ok:
        return _settings_redirect(settings, notion_error="invalid_state")

    db.commit()  # 노션을 부르는 동안 트랜잭션을 열어 두지 않는다
    try:
        tokens = client.exchange_code(
            code or "",
            client_id=settings.notion_client_id,
            client_secret=settings.notion_client_secret,
            redirect_uri=settings.notion_redirect_uri,
        )
    except NotionOAuthError as exc:
        reason = "not_configured" if exc.reason == "invalid_client" else "exchange_failed"
        return _settings_redirect(settings, notion_error=reason)

    try:
        save_connection(db, settings, user_id=current_user.id, tokens=tokens)
    except TokenKeyError:
        db.rollback()
        return _settings_redirect(settings, notion_error="not_configured")
    except Exception:
        db.rollback()
        return _settings_redirect(settings, notion_error="save_failed")
    return _settings_redirect(settings, notion="connected")


# ---- 상태 · 끊기 ----


class NotionStatusOut(BaseModel):
    configured: bool
    status: ConnectionState
    workspace_name: str | None


@router.get("/status", response_model=NotionStatusOut)
def notion_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NotionStatusOut:
    result = get_connection_status(db, settings, user_id=current_user.id)
    return NotionStatusOut(configured=result.configured, status=result.status, workspace_name=result.workspace_name)


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
def notion_disconnect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: NotionClient = Depends(get_notion_client),
) -> Response:
    """연결을 끊는다. 연결이 없어도 204(이미 끊긴 상태가 목표 상태)."""
    disconnect(db, settings, client, user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- 페이지 목록 · 가져오기 ----


class NotionPageOut(BaseModel):
    id: str
    title: str
    last_edited_time: str | None
    imported_note_id: int | None


class NotionPagesOut(BaseModel):
    pages: list[NotionPageOut]
    truncated: bool  # 최근 수정한 100개보다 많아 오래된 페이지가 목록에서 빠짐


@router.get("/pages", response_model=NotionPagesOut)
def notion_pages(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: NotionClient = Depends(get_notion_client),
) -> NotionPagesOut:
    """이 연결에 공유된 페이지(최근 수정 순). 409: 연결 안 됨 · 끊김 / 502: 노션 응답 없음 · 권한 없음 / 503: 서버 설정 없음"""
    try:
        session = NotionSession(db, settings, client, user_id=current_user.id)
        found = list_pages(session, db, user_id=current_user.id)
    except NOTION_ERRORS as exc:
        raise _http_error(exc) from exc
    return NotionPagesOut(
        pages=[NotionPageOut(**vars(item)) for item in found.pages],
        truncated=found.truncated,
    )


PageIdIn = Annotated[str, StringConstraints(max_length=NOTION_MAX_PAGE_ID_INPUT_CHARS)]


class NotionImportIn(BaseModel):
    page_ids: list[PageIdIn] = Field(min_length=1, max_length=NOTION_MAX_IMPORT_PAGES)
    kind: NoteKind = "study"


class NotionImportSummary(BaseModel):
    notes: int
    chunks: int
    duplicates: int
    failed: int
    skipped_blocks: int


class NotionImportedOut(BaseModel):
    page_id: str
    note_id: int
    title: str
    chunk_count: int
    skipped_blocks: int


class NotionDuplicateOut(BaseModel):
    page_id: str
    title: str
    existing_note_id: int
    existing_title: str


class NotionFailedOut(BaseModel):
    page_id: str
    title: str | None
    reason: str


class NotionImportOut(BaseModel):
    summary: NotionImportSummary
    imported: list[NotionImportedOut]
    duplicates: list[NotionDuplicateOut]
    failed: list[NotionFailedOut]
    connection_broken: bool


def _import_out(result: NotionImportResult) -> NotionImportOut:
    return NotionImportOut(
        summary=NotionImportSummary(
            notes=len(result.imported),
            chunks=result.chunk_count,
            duplicates=len(result.duplicates),
            failed=len(result.failed),
            skipped_blocks=result.skipped_blocks,
        ),
        imported=[NotionImportedOut(**vars(page)) for page in result.imported],
        duplicates=[NotionDuplicateOut(**vars(page)) for page in result.duplicates],
        failed=[NotionFailedOut(**vars(page)) for page in result.failed],
        connection_broken=result.connection_broken,
    )


@router.post("/import", response_model=NotionImportOut)
def notion_import(
    body: NotionImportIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: NotionClient = Depends(get_notion_client),
) -> NotionImportOut:
    """고른 페이지를 노트로 가져온다. 일부가 실패해도 200으로 성공 · 중복 · 실패 목록을 함께 돌려준다.

    가져오는 중에 연결이 끊기면 그때까지 저장한 페이지는 남기고 connection_broken=true.
    409: 연결 안 됨 · 끊김(시작 전) · 이미 가져오는 중 / 422: 페이지 번호 형식 · 개수 · 길이 / 502 · 503: 위와 같음
    시간 예산은 이 함수에 들어온 시각부터 센다(세션 열기 · 갱신 · 선점 시간 포함 — 2차 리뷰 R2).
    """
    started = time.monotonic()
    try:
        page_ids = normalize_page_ids(body.page_ids)
    except InvalidPageIdError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    try:
        session = NotionSession(db, settings, client, user_id=current_user.id)
        claimed_at = claim_import(db, user_id=current_user.id)
    except NOTION_ERRORS as exc:
        raise _http_error(exc) from exc
    try:
        remaining = NOTION_IMPORT_TIME_BUDGET_SECONDS - (time.monotonic() - started)
        result = import_pages(
            session, db, user_id=current_user.id, kind=body.kind, page_ids=page_ids, time_budget=max(remaining, 0.0)
        )
    except NOTION_ERRORS as exc:
        raise _http_error(exc) from exc
    finally:
        release_import(db, user_id=current_user.id, claimed_at=claimed_at)
    return _import_out(result)
