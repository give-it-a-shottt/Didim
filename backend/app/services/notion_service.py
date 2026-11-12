"""노션 연결 · 페이지 목록 · 가져오기 (F-005).

- 연결: OAuth로 받은 토큰 쌍을 암호화해 사용자당 1줄로 저장한다(notion_connections).
- 토큰 쓰기: 만료 시각을 알면 미리 갱신하고, 모르면 401을 받았을 때 한 번 갱신한 뒤 다시 부른다.
  갱신이 invalid_grant로 실패하면 '끊김'(토큰 지움) → 설정에서 다시 연결.
  노션은 갱신할 때 갱신 토큰도 바꾼다(rotation). 두 요청이 같은 옛 토큰으로 동시에 갱신하면 늦은 쪽이 실패해
  멀쩡한 연결이 '끊김'이 될 수 있다 → 연결 줄을 잠근(FOR UPDATE) 뒤 "그새 다른 요청이 바꿨는지"를 보고 갱신한다.
  끊김으로 바꿀 때도 같은 방법으로 확인한다(그새 다시 연결한 새 토큰을 지우지 않게, 1차 리뷰 R2).
  잠금은 갱신 요청(노션 호출 한 번, 다시 보내지 않음) 동안만 쥔다 — 같은 사용자의 다른 요청은 그동안 기다렸다가 새 토큰을 쓴다.
- 가져오기: 사용자당 하나(연결 줄의 importing_since 선점, 1차 리뷰 D). 페이지마다 따로 처리 · 따로 저장한다
  (일부가 실패해도 성공한 페이지는 남음 — F-002 완료 기준 4와 같음). 노션을 부르는 동안에는 DB 트랜잭션을
  열어 두지 않는다(연결 풀을 오래 붙잡지 않게). 한 페이지의 순서: 이미 가져온 페이지인지 → 페이지 읽기 →
  블록 나무 읽기(상한) → 마크다운으로(어댑터) → 같은 내용인지 → 나누기 → 저장(D-001, F-002와 같은 함수).
- 시간 예산은 노션 클라이언트에 마감 시각으로도 넘겨, 호출 하나 안에서도 넘기지 않는다(1차 리뷰 C).
- 모든 조회에 user_id 조건(D-004). 토큰 · 제목 · 본문은 로그에 남기지 않는다.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, TypeVar

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import (
    MAX_CHUNKS_PER_NOTE,
    NOTION_IMPORT_CLAIM_STALE_SECONDS,
    NOTION_IMPORT_TIME_BUDGET_SECONDS,
    NOTION_MAX_BLOCK_DEPTH,
    NOTION_MAX_BLOCKS_PER_PAGE,
    NOTION_MAX_PAGE_LIST,
    NOTION_STATUS_BROKEN,
    NOTION_STATUS_CONNECTED,
    NOTION_TOKEN_REFRESH_MARGIN_SECONDS,
    NOTION_WORKSPACE_ID_MAX_CHARS,
    NOTION_WORKSPACE_NAME_MAX_CHARS,
    Settings,
)
from app.db.models import Note, NotionConnection
from app.importers.notion import page_title, render_notion_page
from app.notion.client import (
    NotionAuthError,
    NotionClient,
    NotionDeadlineError,
    NotionError,
    NotionNotFoundError,
    NotionOAuthError,
    NotionTokens,
    NotionUnavailableError,
)
from app.services.chunking import TooManyChunksError, split_markdown
from app.services.import_service import NO_BODY_REASON, SAVE_FAILED_REASON, TOO_MANY_CHUNKS_REASON, NoteKind
from app.services.note_service import (
    ChunkLocationError,
    DuplicateNoteError,
    compute_content_hash,
    create_note_for_user,
    find_note_by_content_hash_for_user,
)
from app.services.token_crypto import TokenDecryptError, TokenKeyError, decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 화면 · API가 보는 연결 상태. "none"은 줄이 없음(저장하지 않는 값), 나머지는 notion_connections.status
ConnectionState = Literal["none", "connected", "broken"]

NOT_SHARED_REASON = "페이지를 찾지 못했어요. 노션에서 이 페이지를 디딤 연결에 공유했는지 확인해 주세요."
IN_TRASH_REASON = "노션 휴지통에 있는 페이지예요."
TOO_MANY_BLOCKS_REASON = f"블록이 너무 많아요({NOTION_MAX_BLOCKS_PER_PAGE:,}개 초과). 페이지를 나눠서 가져와 주세요."
TIME_BUDGET_REASON = "한 번에 가져오기엔 시간이 부족했어요. 이 페이지는 다시 골라 가져와 주세요."
UNAVAILABLE_REASON = "노션이 잠시 응답하지 않아요. 잠시 후 다시 가져와 주세요."
CONNECTION_BROKEN_REASON = "노션 연결이 끊겨서 가져오지 못했어요. 설정에서 다시 연결해 주세요."
NOT_CONFIGURED_REASON = "서버의 노션 연결 설정이 맞지 않아 가져오지 못했어요. 잠시 후 다시 시도해 주세요."

_PAGE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class NotionNotConfiguredError(RuntimeError):
    """서버에 노션 client ID · secret · 토큰 암호화 키가 없다(설정 문제)."""


class NotionNotConnectedError(RuntimeError):
    """이 사용자는 노션을 연결한 적이 없다(또는 연결을 끊었다)."""


class NotionReconnectRequiredError(RuntimeError):
    """연결이 끊겼다(갱신 실패 · 토큰을 풀 수 없음) — 설정에서 다시 연결해야 한다."""


class NotionImportInProgressError(RuntimeError):
    """같은 사용자의 다른 가져오기가 아직 돌고 있다."""


class InvalidPageIdError(ValueError):
    """페이지 번호 형식이 틀렸다."""


class _TimeBudgetExceeded(RuntimeError):
    def __init__(self, title: str | None) -> None:
        super().__init__("time budget")
        self.title = title


class _TooManyBlocks(RuntimeError):
    pass


def normalize_page_id(raw: str) -> str | None:
    """노션 페이지 · 블록 번호(하이픈 있든 없든)를 하이픈 있는 소문자 UUID로. 형식이 틀리면 None."""
    compact = raw.strip().lower().replace("-", "")
    if not _PAGE_ID_RE.match(compact):
        return None
    return f"{compact[:8]}-{compact[8:12]}-{compact[12:16]}-{compact[16:20]}-{compact[20:]}"


def normalize_page_ids(raw_ids: list[str]) -> list[str]:
    """요청의 페이지 번호들을 정리한다(같은 번호는 한 번만, 순서 유지). 하나라도 틀리면 InvalidPageIdError."""
    page_ids: list[str] = []
    for raw in raw_ids:
        page_id = normalize_page_id(raw)
        if page_id is None:
            raise InvalidPageIdError("페이지 번호 형식이 맞지 않아요.")
        if page_id not in page_ids:
            page_ids.append(page_id)
    return page_ids


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    # SQLite는 시간대를 빼고 돌려준다 — 저장할 때는 항상 UTC라 시간대를 붙여 비교한다.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# ---- 연결 상태 ----


@dataclass(frozen=True)
class ConnectionStatus:
    configured: bool
    status: ConnectionState
    workspace_name: str | None


def _get_connection(db: Session, user_id: int, *, for_update: bool = False) -> NotionConnection | None:
    stmt = select(NotionConnection).where(NotionConnection.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def get_connection_status(db: Session, settings: Settings, *, user_id: int) -> ConnectionStatus:
    connection = _get_connection(db, user_id)
    if connection is None:
        return ConnectionStatus(configured=settings.notion_configured, status="none", workspace_name=None)
    status: ConnectionState = "connected" if connection.status == NOTION_STATUS_CONNECTED else "broken"
    return ConnectionStatus(
        configured=settings.notion_configured, status=status, workspace_name=connection.workspace_name
    )


def _apply_tokens(connection: NotionConnection, tokens: NotionTokens, key: str) -> None:
    connection.workspace_id = tokens.workspace_id[:NOTION_WORKSPACE_ID_MAX_CHARS]
    connection.workspace_name = tokens.workspace_name[:NOTION_WORKSPACE_NAME_MAX_CHARS]
    connection.bot_id = tokens.bot_id[:NOTION_WORKSPACE_ID_MAX_CHARS]
    connection.access_token_enc = encrypt_token(tokens.access_token, key)
    connection.refresh_token_enc = encrypt_token(tokens.refresh_token, key)
    connection.expires_at = _utc_now() + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    connection.status = NOTION_STATUS_CONNECTED
    connection.updated_at = _utc_now()


def save_connection(db: Session, settings: Settings, *, user_id: int, tokens: NotionTokens) -> None:
    """연결(또는 재연결)을 저장한다. 사용자당 1줄이라 있으면 덮어쓴다."""
    connection = _get_connection(db, user_id, for_update=True)
    if connection is None:
        connection = NotionConnection(user_id=user_id)
        db.add(connection)
    _apply_tokens(connection, tokens, settings.notion_token_key)
    try:
        db.commit()
    except IntegrityError:
        # 같은 사용자가 두 창에서 동시에 연결을 끝낸 경우 — 먼저 저장된 줄에 덮어쓴다.
        db.rollback()
        connection = _get_connection(db, user_id, for_update=True)
        if connection is None:
            raise
        _apply_tokens(connection, tokens, settings.notion_token_key)
        db.commit()


def disconnect(db: Session, settings: Settings, client: NotionClient, *, user_id: int) -> None:
    """연결을 끊는다: 노션에서도 접근 토큰을 회수해 보고(실패해도 넘어감) 우리 쪽 토큰을 지운다. 가져온 노트는 남는다."""
    connection = _get_connection(db, user_id)
    if connection is None:
        return
    if settings.notion_configured and connection.access_token_enc:
        try:
            access_token = decrypt_token(connection.access_token_enc, settings.notion_token_key)
            db.commit()  # 노션을 부르는 동안 트랜잭션을 열어 두지 않는다
            client.revoke(access_token, client_id=settings.notion_client_id, client_secret=settings.notion_client_secret)
        except (TokenDecryptError, TokenKeyError, NotionError):
            # 키 형식이 틀려도(서버 설정 문제) 끊기는 된다 — 회수만 건너뛰고 우리 쪽 토큰은 지운다(2차 리뷰 R1 · R2 · R3)
            db.rollback()
            logger.warning("노션 토큰 회수 실패 (user_id=%s) — 우리 쪽 토큰만 지움", user_id)
    db.execute(NotionConnection.__table__.delete().where(NotionConnection.user_id == user_id))
    db.commit()


def _mark_broken(db: Session, connection: NotionConnection) -> None:
    connection.status = NOTION_STATUS_BROKEN
    connection.access_token_enc = None
    connection.refresh_token_enc = None
    connection.expires_at = None
    connection.updated_at = _utc_now()
    db.commit()


# ---- 가져오기 선점 (사용자당 하나) ----


def claim_import(db: Session, *, user_id: int, now: datetime | None = None) -> datetime:
    """'가져오는 중' 표시를 건다. 이미 돌고 있으면(오래된 표시는 빼고) NotionImportInProgressError.

    UPDATE 한 번(조건부)이라 두 요청이 동시에 와도 하나만 가져간다. 연결 줄이 없으면 NotionNotConnectedError.
    """
    claimed_at = now or _utc_now()
    stale_before = claimed_at - timedelta(seconds=NOTION_IMPORT_CLAIM_STALE_SECONDS)
    result = db.execute(
        update(NotionConnection)
        .where(
            NotionConnection.user_id == user_id,
            or_(NotionConnection.importing_since.is_(None), NotionConnection.importing_since < stale_before),
        )
        .values(importing_since=claimed_at)
    )
    db.commit()
    if result.rowcount == 1:  # type: ignore[attr-defined]
        return claimed_at
    if _get_connection(db, user_id) is None:
        db.commit()
        raise NotionNotConnectedError("노션이 연결되어 있지 않아요.")
    db.commit()
    raise NotionImportInProgressError("이미 노션 페이지를 가져오고 있어요.")


def release_import(db: Session, *, user_id: int, claimed_at: datetime) -> None:
    """내가 건 표시일 때만 푼다(오래돼서 남이 가져간 표시는 건드리지 않음). 실패해도 예외를 올리지 않는다(오래되면 풀림)."""
    try:
        db.rollback()
        db.execute(
            update(NotionConnection)
            .where(NotionConnection.user_id == user_id, NotionConnection.importing_since == claimed_at)
            .values(importing_since=None)
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.error("노션 가져오기 표시 해제 실패 (user_id=%s)", user_id)


# ---- 토큰을 쓰는 호출 ----


class NotionSession:
    """한 요청 동안 한 사용자의 노션 호출을 맡는다. 토큰 꺼내기 · 미리 갱신 · 401 뒤 한 번 갱신."""

    def __init__(self, db: Session, settings: Settings, client: NotionClient, *, user_id: int) -> None:
        if not settings.notion_configured:
            raise NotionNotConfiguredError("노션 연결 설정이 아직 안 됐어요.")
        self._db = db
        self._settings = settings
        self._client = client
        self._user_id = user_id
        self._token = self._load_token()

    @property
    def client(self) -> NotionClient:
        return self._client

    def _decrypt(self, connection: NotionConnection, value: str | None) -> str:
        if not value:
            raise NotionReconnectRequiredError("노션 연결이 끊겼어요.")
        try:
            return decrypt_token(value, self._settings.notion_token_key)
        except TokenDecryptError as exc:
            # 키가 바뀌었거나 값이 깨짐 — 이 연결은 더 쓸 수 없다
            _mark_broken(self._db, connection)
            raise NotionReconnectRequiredError("노션 연결이 끊겼어요.") from exc

    def _load_token(self) -> str:
        connection = _get_connection(self._db, self._user_id)
        if connection is None:
            raise NotionNotConnectedError("노션이 연결되어 있지 않아요.")
        if connection.status != NOTION_STATUS_CONNECTED:
            raise NotionReconnectRequiredError("노션 연결이 끊겼어요.")
        token = self._decrypt(connection, connection.access_token_enc)
        expires_at = connection.expires_at
        self._db.commit()  # 읽기 트랜잭션을 닫는다(노션을 부르는 동안 DB 연결을 붙잡지 않게)
        if expires_at is not None and _as_utc(expires_at) - _utc_now() <= timedelta(
            seconds=NOTION_TOKEN_REFRESH_MARGIN_SECONDS
        ):
            return self._refresh(stale_access_token=token)
        return token

    def _locked_connection(self) -> NotionConnection:
        connection = _get_connection(self._db, self._user_id, for_update=True)
        if connection is None:
            self._db.rollback()
            raise NotionNotConnectedError("노션이 연결되어 있지 않아요.")
        if connection.status != NOTION_STATUS_CONNECTED:
            self._db.rollback()
            raise NotionReconnectRequiredError("노션 연결이 끊겼어요.")
        return connection

    def _refresh(self, *, stale_access_token: str) -> str:
        connection = self._locked_connection()
        current = self._decrypt(connection, connection.access_token_enc)
        if current != stale_access_token:
            # 잠그기 전에 다른 요청이 이미 갱신했다(또는 다시 연결했다) — 그 토큰을 쓴다
            self._db.commit()
            return current
        refresh_token = self._decrypt(connection, connection.refresh_token_enc)
        previous = NotionTokens(
            access_token=current,
            refresh_token=refresh_token,
            expires_in=None,
            workspace_id=connection.workspace_id,
            workspace_name=connection.workspace_name,
            bot_id=connection.bot_id,
        )
        try:
            tokens = self._client.refresh(
                refresh_token,
                client_id=self._settings.notion_client_id,
                client_secret=self._settings.notion_client_secret,
                previous=previous,
            )
        except NotionOAuthError as exc:
            if exc.reason == "invalid_grant":
                _mark_broken(self._db, connection)
                raise NotionReconnectRequiredError("노션 연결이 끊겼어요.") from exc
            self._db.rollback()
            if exc.reason == "invalid_client":
                raise NotionNotConfiguredError("노션 연결 설정이 맞지 않아요.") from exc
            raise NotionUnavailableError("노션 토큰을 갱신하지 못했어요.") from exc
        _apply_tokens(connection, tokens, self._settings.notion_token_key)
        self._db.commit()
        return tokens.access_token

    def _mark_broken_if_current(self, token: str) -> None:
        """갱신한 토큰도 401이면 끊김으로 — 단, 그새 다시 연결해 토큰이 바뀌었으면 건드리지 않는다."""
        connection = self._locked_connection()
        if self._decrypt(connection, connection.access_token_enc) != token:
            self._db.commit()
            raise NotionUnavailableError("노션 연결이 방금 바뀌었어요. 다시 시도해 주세요.")
        _mark_broken(self._db, connection)

    def call(self, fn: Callable[[str], T]) -> T:
        """fn(접근 토큰)을 부른다. 401이면 한 번 갱신하고 다시. 또 401이면 연결을 끊김으로."""
        try:
            return fn(self._token)
        except NotionAuthError:
            self._token = self._refresh(stale_access_token=self._token)
        try:
            return fn(self._token)
        except NotionAuthError as exc:
            self._mark_broken_if_current(self._token)
            raise NotionReconnectRequiredError("노션 연결이 끊겼어요.") from exc


# ---- 페이지 목록 ----


@dataclass(frozen=True)
class NotionPageItem:
    id: str
    title: str
    last_edited_time: str | None
    imported_note_id: int | None


@dataclass(frozen=True)
class NotionPageList:
    pages: list[NotionPageItem]
    truncated: bool  # 최근 수정한 NOTION_MAX_PAGE_LIST개보다 많아 오래된 페이지가 빠졌는지


def _is_live_page(item: dict[str, Any]) -> bool:
    return item.get("object") == "page" and item.get("in_trash") is not True and item.get("archived") is not True


def list_pages(session: NotionSession, db: Session, *, user_id: int) -> NotionPageList:
    """이 연결에 공유된 페이지(최근 수정 순, 최대 NOTION_MAX_PAGE_LIST개)와 '이미 가져옴' 표시."""
    found = session.call(lambda token: session.client.search_pages(token, limit=NOTION_MAX_PAGE_LIST))
    pages: list[tuple[str, dict[str, Any]]] = []
    for item in found.pages:
        if not _is_live_page(item):
            continue
        page_id = normalize_page_id(str(item.get("id") or ""))
        if page_id is not None:
            pages.append((page_id, item))
    imported: dict[str, int] = {}
    if pages:
        rows = db.execute(
            select(Note.notion_page_id, Note.id).where(
                Note.user_id == user_id,
                Note.notion_page_id.in_([page_id for page_id, _ in pages]),
            )
        ).all()
        db.commit()
        imported = {page_id: note_id for page_id, note_id in rows if page_id is not None}
    items = [
        NotionPageItem(
            id=page_id,
            title=page_title(item),
            last_edited_time=edited if isinstance(edited := item.get("last_edited_time"), str) else None,
            imported_note_id=imported.get(page_id),
        )
        for page_id, item in pages
    ]
    return NotionPageList(pages=items, truncated=found.has_more)


# ---- 가져오기 ----


@dataclass(frozen=True)
class NotionImportedPage:
    page_id: str
    note_id: int
    title: str
    chunk_count: int
    skipped_blocks: int


@dataclass(frozen=True)
class NotionDuplicatePage:
    page_id: str
    title: str
    existing_note_id: int
    existing_title: str


@dataclass(frozen=True)
class NotionFailedPage:
    page_id: str
    title: str | None  # 페이지를 읽기 전에 실패하면 모름
    reason: str


@dataclass
class NotionImportResult:
    imported: list[NotionImportedPage] = field(default_factory=list)
    duplicates: list[NotionDuplicatePage] = field(default_factory=list)
    failed: list[NotionFailedPage] = field(default_factory=list)
    connection_broken: bool = False

    @property
    def chunk_count(self) -> int:
        return sum(page.chunk_count for page in self.imported)

    @property
    def skipped_blocks(self) -> int:
        return sum(page.skipped_blocks for page in self.imported)


class _Importer:
    def __init__(
        self,
        session: NotionSession,
        db: Session,
        *,
        user_id: int,
        kind: NoteKind,
        clock: Callable[[], float],
        time_budget: float,
    ) -> None:
        self.session = session
        self.db = db
        self.user_id = user_id
        self.kind = kind
        self.clock = clock
        self.deadline = clock() + time_budget
        self.result = NotionImportResult()

    def _fail(self, page_id: str, title: str | None, reason: str) -> None:
        self.result.failed.append(NotionFailedPage(page_id=page_id, title=title, reason=reason))

    def _duplicate(self, page_id: str, title: str, note: Note) -> None:
        self.result.duplicates.append(
            NotionDuplicatePage(page_id=page_id, title=title, existing_note_id=note.id, existing_title=note.title)
        )

    def _check_time(self, title: str | None = None) -> None:
        if self.clock() > self.deadline:
            raise _TimeBudgetExceeded(title)

    def _existing_by_page(self, page_id: str) -> Note | None:
        return self.db.execute(
            select(Note).where(Note.user_id == self.user_id, Note.notion_page_id == page_id)
        ).scalar_one_or_none()

    def _same_content(self, content: str) -> Note | None:
        return find_note_by_content_hash_for_user(
            self.db, user_id=self.user_id, content_hash=compute_content_hash(content)
        )

    def run(self, page_ids: list[str]) -> NotionImportResult:
        self.session.client.set_time_budget(max(self.deadline - self.clock(), 0.0))
        try:
            for index, page_id in enumerate(page_ids):
                try:
                    self._import_one(page_id)
                except _TimeBudgetExceeded as exc:
                    # 지금 페이지는 제목과 함께 한 번, 남은 페이지는 시작하지 않고 실패로
                    self._fail(page_id, exc.title, TIME_BUDGET_REASON)
                    for rest in page_ids[index + 1 :]:
                        self._fail(rest, None, TIME_BUDGET_REASON)
                    break
                except (NotionReconnectRequiredError, NotionNotConnectedError):
                    # 가져오는 도중 끊김 · 다른 창에서 연결을 끊음 — 저장한 페이지는 남긴다
                    self.result.connection_broken = True
                    for rest in page_ids[index:]:
                        self._fail(rest, None, CONNECTION_BROKEN_REASON)
                    break
                except (NotionNotConfiguredError, TokenKeyError):
                    # 도중 갱신이 invalid_client 등 서버 설정 문제 — 503 하나로 끝내지 않고 저장한 결과를 돌려준다(2차 리뷰 R3 · R4)
                    for rest in page_ids[index:]:
                        self._fail(rest, None, NOT_CONFIGURED_REASON)
                    break
                except SQLAlchemyError as exc:
                    # 저장 밖의 DB 읽기(이미 가져옴 · 같은 내용 확인)가 실패 — 500 하나로 끝내지 않고 저장한 결과를 돌려준다(3차 리뷰 R3)
                    self.db.rollback()
                    logger.error("노션 가져오기 중 DB 오류 (user_id=%s, %s)", self.user_id, type(exc).__name__)
                    for rest in page_ids[index:]:
                        self._fail(rest, None, SAVE_FAILED_REASON)
                    break
        finally:
            self.session.client.set_time_budget(None)
        return self.result

    def _read_page(self, page_id: str) -> tuple[str, list[dict[str, Any]]] | None:
        """페이지 제목과 블록 나무. 그 페이지만 실패면 기록하고 None."""
        title: str | None = None
        try:
            self._check_time()
            page = self.session.call(lambda token: self.session.client.get_page(token, page_id))
            title = page_title(page)
            if not _is_live_page(page):
                self._fail(page_id, title, IN_TRASH_REASON)
                return None
            return title, self._fetch_tree(page_id, 1, [0], title)
        except NotionNotFoundError:
            self._fail(page_id, title, NOT_SHARED_REASON)
        except NotionUnavailableError:
            self._fail(page_id, title, UNAVAILABLE_REASON)
        except _TooManyBlocks:
            self._fail(page_id, title, TOO_MANY_BLOCKS_REASON)
        except (NotionDeadlineError, _TimeBudgetExceeded):
            raise _TimeBudgetExceeded(title) from None
        return None

    def _fetch_tree(self, block_id: str, depth: int, counter: list[int], title: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            self._check_time(title)
            start = cursor
            results, cursor = self.session.call(
                lambda token: self.session.client.list_children(token, block_id, start_cursor=start)
            )
            for block in results:
                counter[0] += 1
                if counter[0] > NOTION_MAX_BLOCKS_PER_PAGE:
                    raise _TooManyBlocks
                blocks.append(block)
            if cursor is None:
                break
        for block in blocks:
            # 응답의 블록 번호도 검사한 뒤 주소에 넣는다(1차 리뷰 R2). 형식이 틀리면 안쪽은 읽지 않는다
            child_id = normalize_page_id(str(block.get("id") or ""))
            if (
                block.get("has_children") is True
                and block.get("type") not in ("child_page", "child_database")
                and depth < NOTION_MAX_BLOCK_DEPTH
                and child_id is not None
            ):
                block["children"] = self._fetch_tree(child_id, depth + 1, counter, title)
        return blocks

    def _import_one(self, page_id: str) -> None:
        existing = self._existing_by_page(page_id)
        self.db.commit()  # 노션을 부르는 동안 트랜잭션을 열어 두지 않는다(1차 리뷰 D)
        if existing is not None:
            self._duplicate(page_id, existing.title, existing)
            return

        read = self._read_page(page_id)
        if read is None:
            return
        title, blocks = read

        rendered = render_notion_page(title, blocks)
        document = rendered.document
        same_content = self._same_content(document.content)
        if same_content is not None:
            self.db.commit()
            self._duplicate(page_id, document.title, same_content)
            return

        try:
            chunks = split_markdown(document.content, max_chunks=MAX_CHUNKS_PER_NOTE)
        except TooManyChunksError:
            self._fail(page_id, document.title, TOO_MANY_CHUNKS_REASON)
            return
        if not chunks:
            self._fail(page_id, document.title, NO_BODY_REASON)
            return

        try:
            note = create_note_for_user(
                self.db,
                user_id=self.user_id,
                title=document.title,
                content=document.content,
                source=document.source,
                kind=self.kind,
                chunks=chunks,
                notion_page_id=page_id,
            )
        except DuplicateNoteError:
            # 확인한 뒤 같은 페이지 · 같은 내용이 먼저 저장된 경우
            raced = self._existing_by_page(page_id) or self._same_content(document.content)
            self.db.commit()
            if raced is not None:
                self._duplicate(page_id, document.title, raced)
            else:
                self._fail(page_id, document.title, SAVE_FAILED_REASON)
            return
        except (SQLAlchemyError, ChunkLocationError) as exc:
            self.db.rollback()
            logger.error("노션 노트 저장 실패 (user_id=%s, %s)", self.user_id, type(exc).__name__)
            self._fail(page_id, document.title, SAVE_FAILED_REASON)
            return

        self.result.imported.append(
            NotionImportedPage(
                page_id=page_id,
                note_id=note.id,
                title=note.title,
                chunk_count=len(chunks),
                skipped_blocks=rendered.skipped_blocks,
            )
        )


def import_pages(
    session: NotionSession,
    db: Session,
    *,
    user_id: int,
    kind: NoteKind,
    page_ids: list[str],
    clock: Callable[[], float] = time.monotonic,
    time_budget: float = NOTION_IMPORT_TIME_BUDGET_SECONDS,
) -> NotionImportResult:
    """고른 페이지(normalize_page_ids를 거친 번호)를 노트로 가져온다. user_id는 세션에서 꺼낸 값만(D-004).

    부르는 쪽이 claim_import · release_import로 사용자당 하나를 지킨다(API 라우터).
    """
    importer = _Importer(session, db, user_id=user_id, kind=kind, clock=clock, time_budget=time_budget)
    return importer.run(page_ids)
