"""LLM 호출의 공통 모양 (D-014).

기능 코드(퀴즈 · 카드 · 자소서)는 이 파일의 `LLMClient` 모양만 알고, 실제로 어느 AI(mock · exaone · local)를
부르는지는 모른다. 그래서 설정 하나로 AI를 바꿔 끼울 수 있다.

오류는 "부른 쪽이 다르게 행동해야 하는 경우"마다 하나씩 나눈다.
- LLMConfigError    설정이 틀림(키 없음 · 키 거절 · 모델 이름 틀림 · 결제). 다시 불러도 안 됨 → 설정을 고쳐야 함
- LLMRequestError   우리 요청 내용이 거절됨(400 · 413 · 422 등). 다시 불러도 안 됨 → 보내는 내용을 고쳐야 함
- LLMRateLimited    사용량 초과(429). 다시 부르지 않고 바로 알림 → 부른 기능이 부분 결과를 보존(원칙 4)
- LLMUnavailable    네트워크 · 타임아웃 · 서버 오류(5xx) · 전체 시간 초과. 한 번 다시 불러 본 뒤에도 안 될 때
- LLMInvalidOutput  답이 정해진 JSON 형식이 아님. 한 번 다시 요청한 뒤에도 틀릴 때(원칙 3)

오류 문구에는 API 키 · 보낸 내용 · 받은 내용을 넣지 않는다(로그로 새어 나가지 않게).
모든 결과와 오류에는 `usage`(실제 HTTP 호출 수 · 토큰)가 붙는다. 하루 상한(원칙 4)은 이 값으로 센다.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMUsage:
    """AI 사용량. 실패한 호출도 calls에 센다(서버가 요청을 받았을 수 있으므로 적게 세지 않는 쪽으로).

    토큰은 서버가 알려 준 만큼만 더한다. 실패한 호출 · 토큰을 안 알려 주는 서버는 0으로 남는다.
    """

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            calls=self.calls + other.calls,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True)
class LLMReply:
    """AI 한 번 부르기(chat)의 결과. 연결 재시도가 있었으면 usage.calls가 2 이상이다."""

    content: str  # 답 본문. 앞뒤 공백 · 줄바꿈은 걷어 냄(EXAONE은 답 앞에 "\n\n"이 붙을 수 있음)
    model: str
    reasoning: str | None = None  # EXAONE의 추론 과정(message.reasoning_content). 화면에 보여 주지 않음
    finish_reason: str | None = None  # "stop"이면 정상 종료, "length"면 길이 제한에 걸려 잘림
    usage: LLMUsage = field(default_factory=lambda: LLMUsage(calls=1))


class LLMClient(Protocol):
    """모든 AI 클라이언트가 지키는 모양. 메시지를 받아 답 하나를 돌려준다."""

    async def chat(self, messages: Sequence[Message]) -> LLMReply: ...


class LLMError(RuntimeError):
    """LLM 호출 오류의 공통 부모. 부르는 쪽에서 한 번에 잡을 때 쓴다.

    usage: 이 오류가 나기까지 쓴 사용량. 오류를 올려 보내는 층마다 앞서 쓴 사용량을 더한다.
    """

    def __init__(self, message: str, *, usage: LLMUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage if usage is not None else LLMUsage()


class LLMConfigError(LLMError):
    """설정이 틀렸을 때. 다시 불러도 결과가 같으니 재시도하지 않는다."""


class LLMRequestError(LLMError):
    """AI 서버가 우리 요청 내용을 거절했을 때(400 · 413 · 422 등). 재시도하지 않는다."""

    def __init__(self, message: str, *, status_code: int, usage: LLMUsage | None = None) -> None:
        super().__init__(message, usage=usage)
        self.status_code = status_code


class LLMRateLimited(LLMError):
    """사용량 한도에 걸렸을 때(429). 재시도하지 않고 부른 기능이 부분 결과를 보존한다."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        usage: LLMUsage | None = None,
    ) -> None:
        super().__init__(message, usage=usage)
        self.retry_after_seconds = retry_after_seconds


class LLMUnavailable(LLMError):
    """네트워크 · 타임아웃 · 서버 오류가 재시도 후에도 계속되거나, 전체 시간 상한을 넘었을 때."""


class LLMInvalidOutput(LLMError):
    """답이 정해진 JSON 형식에 맞지 않을 때(재시도 후에도).

    오류 문구(str)에는 오류 종류만 넣는다. 자세한 위치 · 설명(`detail`)과 마지막 답 원문(`raw_content`)은
    사용자 기록이 섞일 수 있어서 속성에만 둔다. 평가 로그(원칙 5)에 쓸 때도 이 점을 지킨다.
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        raw_content: str,
        detail: str = "",
        usage: LLMUsage | None = None,
    ) -> None:
        super().__init__(message, usage=usage)
        self.attempts = attempts
        self.raw_content = raw_content
        self.detail = detail
