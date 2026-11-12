"""노션 REST API 클라이언트 (F-005). HTTP만 맡는다 — DB · 토큰 저장 · 변환은 다른 곳.

- 토큰 교환 · 갱신 · 회수: POST /v1/oauth/token · /v1/oauth/revoke, HTTP Basic(client_id:client_secret).
  갱신하면 갱신 토큰도 새것으로 바뀐다(rotation) → 받은 쌍을 매번 저장해야 한다(호출하는 쪽 책임).
  토큰 요청은 다시 보내지 않는다: 응답만 잃었는데 다시 보내면, 이미 바뀐 갱신 토큰(또는 한 번 쓴 코드)이라
  invalid_grant가 되어 멀쩡한 연결이 '끊김'이 될 수 있다(1차 리뷰 R2).
- 페이지 목록: POST /v1/search(filter object=page), 페이지: GET /v1/pages/{id}, 블록: GET /v1/blocks/{id}/children.
- 노션 호출 한도(평균 초당 약 3번)에 맞춰 요청 사이를 띄우고, 429는 Retry-After만큼(상한 있음), 5xx · 연결 실패는
  잠깐 쉬고 다시 한다. 401 · 404 같은 '다시 해도 같은' 오류는 바로 올린다.
- 시간 예산(set_time_budget)을 주면 호출 하나 안에서도 넘기지 않는다: 요청 시간 상한과 재시도 대기를 남은 시간으로
  자르고, 남은 시간이 없으면 NotionDeadlineError(가져오기 시간 예산 — 1차 리뷰 C).
- 토큰 · 응답 본문은 로그에 남기지 않는다(개인 기록 · 비밀 값).

테스트는 transport에 httpx.MockTransport를 넣어 실제 노션 없이 돈다(tests/test_notion.py).
"""

import base64
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import (
    NOTION_API_BASE,
    NOTION_API_PAGE_SIZE,
    NOTION_API_VERSION,
    NOTION_HTTP_TIMEOUT_SECONDS,
    NOTION_MAX_RETRIES,
    NOTION_MAX_RETRY_WAIT_SECONDS,
    NOTION_MIN_REQUEST_INTERVAL_SECONDS,
    NOTION_MIN_REQUEST_SECONDS,
    NOTION_SERVER_ERROR_RETRY_WAIT_SECONDS,
)

logger = logging.getLogger(__name__)


class NotionError(RuntimeError):
    """노션 호출 실패의 공통 부모."""


class NotionAuthError(NotionError):
    """401 — 접근 토큰이 만료 · 회수됨. 갱신해 보고, 갱신도 안 되면 다시 연결."""


class NotionNotFoundError(NotionError):
    """404 · 403 — 페이지가 없거나 이 연결에 공유되지 않음(검색이면 통합 권한 부족)."""


class NotionUnavailableError(NotionError):
    """노션 서버 오류 · 연결 실패 · 한도(429)가 다시 해도 풀리지 않음 · 응답 형식이 틀림."""


class NotionDeadlineError(NotionError):
    """마감 시각(가져오기 시간 예산)을 넘겨 더 부르지 않음."""


class NotionOAuthError(NotionError):
    """토큰 교환 · 갱신 실패. reason: invalid_grant(코드 · 갱신 토큰이 무효 — 다시 연결) ·
    invalid_client(서버 설정 문제) · failed(그 밖 — 네트워크 · 서버 오류 포함)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class NotionTokens:
    # 토큰 원문은 repr(로그 · 오류 메시지 · 디버거 출력)에 나오지 않게 한다(2차 리뷰 R2)
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int | None  # 초. 노션이 주지 않으면 None
    workspace_id: str
    workspace_name: str
    bot_id: str


@dataclass(frozen=True)
class NotionSearchResult:
    pages: list[dict[str, Any]]
    has_more: bool  # 상한보다 많아 잘렸는지(화면 안내 — 1차 리뷰 F)


def _require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise NotionOAuthError("failed")
    return value


def _parse_tokens(data: Any, *, previous: NotionTokens | None = None) -> NotionTokens:
    """토큰 응답을 읽는다. 갱신 응답에 워크스페이스 정보가 없으면 이전 값을 쓴다."""
    if not isinstance(data, dict):
        raise NotionOAuthError("failed")
    expires_in = data.get("expires_in")
    if not isinstance(expires_in, int) or isinstance(expires_in, bool) or expires_in <= 0:
        expires_in = None
    workspace_name = data.get("workspace_name")
    return NotionTokens(
        access_token=_require_str(data, "access_token"),
        refresh_token=_require_str(data, "refresh_token"),
        expires_in=expires_in,
        workspace_id=str(data.get("workspace_id") or (previous.workspace_id if previous else "")),
        workspace_name=str(workspace_name or (previous.workspace_name if previous else "") or "노션"),
        bot_id=str(data.get("bot_id") or (previous.bot_id if previous else "")),
    )


def _basic_auth(client_id: str, client_secret: str) -> str:
    return "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")


class NotionClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = NOTION_API_BASE,
        min_interval: float = NOTION_MIN_REQUEST_INTERVAL_SECONDS,
        max_retries: int = NOTION_MAX_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = httpx.Client(transport=transport, timeout=NOTION_HTTP_TIMEOUT_SECONDS)
        self._base_url = base_url.rstrip("/")
        self._min_interval = min_interval
        self._max_retries = max(0, max_retries)
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self._deadline: float | None = None

    def close(self) -> None:
        self._http.close()

    def set_time_budget(self, seconds: float | None) -> None:
        """지금부터 seconds초 뒤를 마감으로(이 클라이언트의 시계 기준). None이면 마감 없음."""
        self._deadline = None if seconds is None else self._clock() + seconds

    # ---- OAuth ----

    def exchange_code(self, code: str, *, client_id: str, client_secret: str, redirect_uri: str) -> NotionTokens:
        data = self._token_request(
            "/oauth/token",
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            client_id=client_id,
            client_secret=client_secret,
        )
        tokens = _parse_tokens(data)
        if not tokens.workspace_id or not tokens.bot_id:
            raise NotionOAuthError("failed")
        return tokens

    def refresh(self, refresh_token: str, *, client_id: str, client_secret: str, previous: NotionTokens) -> NotionTokens:
        data = self._token_request(
            "/oauth/token",
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
            client_id=client_id,
            client_secret=client_secret,
        )
        return _parse_tokens(data, previous=previous)

    def revoke(self, access_token: str, *, client_id: str, client_secret: str) -> None:
        """접근 토큰을 노션에서도 회수한다([연결 끊기]). 실패는 NotionOAuthError — 부르는 쪽이 무시해도 된다."""
        self._token_request("/oauth/revoke", {"token": access_token}, client_id=client_id, client_secret=client_secret)

    def _token_request(self, path: str, body: dict[str, str], *, client_id: str, client_secret: str) -> Any:
        # 토큰 요청은 시간 상한을 남은 예산으로 자르지 않는다: 노션은 갱신을 처리했는데 우리가 응답을 못 받으면
        # 다음 갱신이 invalid_grant가 된다. 상한만큼 기다릴 시간이 없으면 아예 보내지 않는다(2차 리뷰 R2).
        remaining = self._remaining()
        if remaining is not None and remaining < NOTION_HTTP_TIMEOUT_SECONDS:
            raise NotionDeadlineError("시간 예산이 부족해 토큰 요청을 보내지 않았어요.")
        try:
            response = self._send(
                "POST",
                path,
                headers={"Authorization": _basic_auth(client_id, client_secret), "Notion-Version": NOTION_API_VERSION},
                json=body,
                retries=0,
                cut_timeout=False,
            )
        except NotionUnavailableError as exc:
            raise NotionOAuthError("failed") from exc
        if response.status_code == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise NotionOAuthError("failed") from exc
        error = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = str(payload.get("error") or "")
        except ValueError:
            pass
        logger.warning("노션 토큰 요청 실패 (%s, status=%s, error=%s)", path, response.status_code, error or "-")
        if error == "invalid_grant":
            raise NotionOAuthError("invalid_grant")
        if error == "invalid_client" or response.status_code == 401:
            raise NotionOAuthError("invalid_client")
        raise NotionOAuthError("failed")

    # ---- 읽기 ----

    def search_pages(self, access_token: str, *, limit: int) -> NotionSearchResult:
        """이 연결에 공유된 페이지를 최근 수정한 것부터 최대 limit개(한 번 요청)."""
        data = self._api(
            "POST",
            "/search",
            access_token,
            json={
                "filter": {"property": "object", "value": "page"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": min(max(limit, 1), NOTION_API_PAGE_SIZE),
            },
        )
        results = data.get("results")
        if not isinstance(results, list):
            raise NotionUnavailableError("노션 응답 형식이 달라요.")
        pages = [item for item in results if isinstance(item, dict)]
        return NotionSearchResult(pages=pages[:limit], has_more=data.get("has_more") is True or len(pages) > limit)

    def get_page(self, access_token: str, page_id: str) -> dict[str, Any]:
        return self._api("GET", f"/pages/{page_id}", access_token)

    def list_children(
        self, access_token: str, block_id: str, *, start_cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, str | int] = {"page_size": NOTION_API_PAGE_SIZE}
        if start_cursor:
            params["start_cursor"] = start_cursor
        data = self._api("GET", f"/blocks/{block_id}/children", access_token, params=params)
        results = data.get("results")
        if not isinstance(results, list):
            raise NotionUnavailableError("노션 응답 형식이 달라요.")
        next_cursor = data.get("next_cursor") if data.get("has_more") else None
        return [item for item in results if isinstance(item, dict)], (
            next_cursor if isinstance(next_cursor, str) and next_cursor else None
        )

    def _api(
        self,
        method: str,
        path: str,
        access_token: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        response = self._send(
            method,
            path,
            headers={"Authorization": f"Bearer {access_token}", "Notion-Version": NOTION_API_VERSION},
            json=json,
            params=params,
            retries=self._max_retries,
        )
        if response.status_code == 401:
            raise NotionAuthError("노션 토큰이 만료됐거나 회수됐어요.")
        if response.status_code in (403, 404):
            raise NotionNotFoundError("노션 페이지를 찾지 못했어요.")
        if response.status_code != 200:
            logger.warning("노션 요청 실패 (%s %s, status=%s)", method, path.split("/")[1], response.status_code)
            raise NotionUnavailableError("노션 요청이 실패했어요.")
        try:
            data = response.json()
        except ValueError as exc:
            raise NotionUnavailableError("노션 응답 형식이 달라요.") from exc
        if not isinstance(data, dict):
            raise NotionUnavailableError("노션 응답 형식이 달라요.")
        return data

    def _remaining(self) -> float | None:
        return None if self._deadline is None else self._deadline - self._clock()

    def _sleep_within_deadline(self, seconds: float) -> None:
        remaining = self._remaining()
        if remaining is not None and seconds >= remaining - NOTION_MIN_REQUEST_SECONDS:
            raise NotionDeadlineError("시간 예산을 넘었어요.")
        self._sleep(seconds)

    def _send(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        retries: int,
        json: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
        cut_timeout: bool = True,
    ) -> httpx.Response:
        """간격을 지켜 보내고, 429 · 5xx · 연결 실패는 retries번까지 다시 한다. 그 밖의 응답은 그대로 돌려준다.

        cut_timeout이면 요청 시간 상한을 남은 예산으로 자른다(읽기 요청). 토큰 요청은 자르지 않는다.
        """
        url = f"{self._base_url}{path}"
        attempt = 0
        while True:
            self._wait_for_slot()
            remaining = self._remaining()
            if remaining is not None and remaining < NOTION_MIN_REQUEST_SECONDS:
                raise NotionDeadlineError("시간 예산을 넘었어요.")
            timeout = (
                min(NOTION_HTTP_TIMEOUT_SECONDS, remaining)
                if cut_timeout and remaining is not None
                else NOTION_HTTP_TIMEOUT_SECONDS
            )
            try:
                response = self._http.request(method, url, headers=headers, json=json, params=params, timeout=timeout)
            except httpx.HTTPError as exc:
                if attempt >= retries:
                    raise NotionUnavailableError("노션에 연결하지 못했어요.") from exc
                attempt += 1
                self._sleep_within_deadline(NOTION_SERVER_ERROR_RETRY_WAIT_SECONDS)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= retries:
                    raise NotionUnavailableError("노션이 잠시 응답하지 않아요.")
                attempt += 1
                self._sleep_within_deadline(self._retry_wait(response))
                continue
            return response

    def _retry_wait(self, response: httpx.Response) -> float:
        if response.status_code != 429:
            return NOTION_SERVER_ERROR_RETRY_WAIT_SECONDS
        raw = response.headers.get("Retry-After", "")
        try:
            seconds = float(raw)
        except ValueError:
            seconds = NOTION_SERVER_ERROR_RETRY_WAIT_SECONDS
        return min(max(seconds, 0.0), NOTION_MAX_RETRY_WAIT_SECONDS)

    def _wait_for_slot(self) -> None:
        now = self._clock()
        if self._last_request_at is not None and self._min_interval > 0:
            gap = now - self._last_request_at
            if gap < self._min_interval:
                self._sleep(self._min_interval - gap)
                now = self._clock()
        self._last_request_at = now
