"""OpenAI 호환 채팅 API 클라이언트 — exaone · local 공통 (D-014).

EXAONE · Ollama · LM Studio는 모두 `POST {base_url}/chat/completions` 같은 모양이라,
주소(base_url) · 모델 이름 · 키만 바꿔서 이 클래스 하나로 부른다.

재시도 규칙(이 파일은 "연결" 문제만 다룬다. 답 형식 검사 · 전체 시간 상한은 structured.py):
- 네트워크 오류 · 타임아웃 · 408 · 5xx · 깨진 응답 본문 → 잠깐 쉬고 1번 더. 그래도 안 되면 LLMUnavailable
- 429 → 다시 부르지 않고 바로 LLMRateLimited (원칙 4: 부른 기능이 부분 결과를 보존)
- 401 · 402 · 403 · 404 · 3xx → LLMConfigError, 그 밖의 4xx → LLMRequestError (다시 불러도 같으니 재시도 안 함)
"""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any

import httpx

from app.llm.base import (
    LLMConfigError,
    LLMError,
    LLMRateLimited,
    LLMReply,
    LLMRequestError,
    LLMUnavailable,
    LLMUsage,
    Message,
)
from app.llm.settings import (
    LLM_CONNECT_TIMEOUT_SECONDS,
    LLM_MAX_TRANSIENT_ATTEMPTS,
    LLM_TRANSIENT_RETRY_DELAY_SECONDS,
    LLMSettings,
)

logger = logging.getLogger(__name__)

SleepFn = Callable[[float], Awaitable[None]]


class _TransientError(Exception):
    """다시 불러 보면 될 수도 있는 오류(이 파일 안에서만 쓰고 밖으로는 LLMUnavailable로 바꿔 내보냄)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _int_or_zero(value: Any) -> int:
    # bool은 int의 하위 타입이라 따로 막는다(True가 1토큰으로 읽히지 않게). 음수도 버린다.
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _parse_retry_after(raw: str | None) -> float | None:
    """Retry-After 헤더의 초 단위 값만 읽는다. 날짜 형식이거나 이상하면 None."""
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: LLMSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        """transport · sleep은 테스트에서 가짜 서버 · 기다리지 않는 sleep을 넣을 때만 쓴다."""
        if settings.provider not in ("exaone", "local") or not settings.base_url or not settings.model:
            raise LLMConfigError("OpenAI 호환 클라이언트에는 exaone 또는 local 설정(주소 · 모델)이 필요해요.")
        self._settings = settings
        self._url = f"{settings.base_url}/chat/completions"
        self._transport = transport
        self._sleep = sleep

    async def chat(self, messages: Sequence[Message]) -> LLMReply:
        if not messages:
            raise ValueError("messages가 비어 있어요.")

        body: dict[str, Any] = {
            "model": self._settings.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if self._settings.reasoning_effort:
            body["reasoning_effort"] = self._settings.reasoning_effort

        headers: dict[str, str] = {}
        if self._settings.api_key:
            headers["Authorization"] = f"Bearer {self._settings.api_key}"

        timeout = httpx.Timeout(
            self._settings.timeout_seconds,
            connect=min(LLM_CONNECT_TIMEOUT_SECONDS, self._settings.timeout_seconds),
        )

        last_error: _TransientError | None = None
        # follow_redirects=False(기본): 다른 주소로 넘겨도 따라가지 않는다(키를 다른 곳에 보내지 않게)
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            for attempt in range(1, LLM_MAX_TRANSIENT_ATTEMPTS + 1):
                if attempt > 1:
                    await self._sleep(LLM_TRANSIENT_RETRY_DELAY_SECONDS)
                try:
                    reply = await self._send_once(client, body, headers)
                except _TransientError as exc:
                    last_error = exc
                    logger.warning(
                        "LLM 호출 실패(%s), 시도 %d/%d", exc.reason, attempt, LLM_MAX_TRANSIENT_ATTEMPTS
                    )
                    continue
                except LLMError as exc:
                    exc.usage = LLMUsage(calls=attempt)  # 앞서 실패한 시도까지 센다
                    raise
                return replace(reply, usage=replace(reply.usage, calls=attempt))

        reason = last_error.reason if last_error else "unknown"
        raise LLMUnavailable(
            f"AI 서버에서 답을 받지 못했어요({reason}, {LLM_MAX_TRANSIENT_ATTEMPTS}번 시도).",
            usage=LLMUsage(calls=LLM_MAX_TRANSIENT_ATTEMPTS),
        ) from last_error

    def _auth_hint(self) -> str:
        if self._settings.provider == "exaone":
            return "EXAONE_API_KEY를 확인해 주세요."
        return "local AI 서버의 인증 설정을 확인해 주세요."

    async def _send_once(
        self,
        client: httpx.AsyncClient,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> LLMReply:
        try:
            response = await client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException as exc:  # TransportError의 하위라 먼저 잡는다
            raise _TransientError("timeout") from exc
        except httpx.RequestError as exc:
            raise _TransientError("network") from exc

        status = response.status_code
        # 응답 본문은 오류 문구에 넣지 않는다(보낸 내용이 되돌아와 로그에 남을 수 있어서). 상태 코드만 쓴다.
        if status == 429:
            raise LLMRateLimited(
                "AI 사용량 한도에 걸렸어요(429).",
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
            )
        if status in (401, 403):
            raise LLMConfigError(f"AI 서버가 키를 거절했어요({status}). {self._auth_hint()}")
        if status == 402:  # 유료 전환 · 잔액 부족 등(D-014 "유료 전환 가능"). 보내는 내용 문제가 아니다
            raise LLMConfigError("AI 서버가 결제 · 사용 권한 문제로 거절했어요(402). 계정 상태를 확인해 주세요.")
        if status == 404:
            raise LLMConfigError("AI 서버 주소나 모델을 찾지 못했어요(404). LLM_BASE_URL · LLM_MODEL을 확인해 주세요.")
        if 300 <= status < 400:
            raise LLMConfigError(f"AI 서버가 다른 주소로 넘기려 해요({status}). LLM_BASE_URL을 확인해 주세요.")
        if status == 408 or status >= 500:
            raise _TransientError(f"HTTP {status}")
        if 400 <= status < 500:
            raise LLMRequestError(f"AI 서버가 요청을 거절했어요({status}).", status_code=status)
        if not 200 <= status < 300:
            raise _TransientError(f"HTTP {status}")

        return self._parse_reply(response)

    def _parse_reply(self, response: httpx.Response) -> LLMReply:
        """OpenAI 호환 응답에서 답을 꺼낸다. 모양이 깨졌으면 다시 불러 볼 오류로 본다."""
        try:
            data = response.json()
        except (ValueError, RecursionError) as exc:  # RecursionError: 아주 깊게 중첩된 본문
            raise _TransientError("invalid response body") from exc

        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise _TransientError("invalid response body")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise _TransientError("invalid response body")

        content = message.get("content")
        if content is None:  # 길이 제한에 걸리면 답 없이 끝날 수 있다 → 빈 답으로 돌려주고 형식 검사에서 처리
            content = ""
        if not isinstance(content, str):
            raise _TransientError("invalid response body")

        reasoning = message.get("reasoning_content")
        finish_reason = choice.get("finish_reason")
        model = data.get("model")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}

        return LLMReply(
            content=content.strip(),  # EXAONE은 답 앞에 "\n\n"이 붙을 수 있다(D-014)
            model=model if isinstance(model, str) and model else self._settings.model,
            reasoning=reasoning if isinstance(reasoning, str) else None,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            usage=LLMUsage(
                calls=1,
                prompt_tokens=_int_or_zero(usage.get("prompt_tokens")),
                completion_tokens=_int_or_zero(usage.get("completion_tokens")),
            ),
        )
