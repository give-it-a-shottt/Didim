"""가짜 AI (D-014) — 키 없이 개발 · 테스트할 때 쓴다(LLM_PROVIDER=mock, 기본값).

미리 넣어 둔 답을 순서대로 돌려준다. 오류 객체를 넣으면 그 차례에 그 오류를 낸다.
예) MockLLMClient(['{"x": 1', '{"x": 1}'])  → 첫 답은 깨진 JSON, 두 번째는 맞는 JSON(재시도 확인용)
    MockLLMClient([LLMRateLimited("429")])  → 사용량 초과 상황 확인용
준비한 답이 다 떨어지면 default_reply를 돌려준다(None이면 오류).

⚠️ 기본 답은 JSON이 아니라서, mock 상태로 complete_json을 부르면 LLMInvalidOutput으로 끝난다.
AI를 쓰는 첫 기능부터 기능별 가짜 답(그 스키마에 맞는 JSON)을 등록해서 키 없이도 화면이 돌게 한다.
"""

from collections import deque
from collections.abc import Iterable, Sequence

from app.llm.base import LLMConfigError, LLMError, LLMReply, LLMUsage, Message

MOCK_MODEL_NAME = "mock"
MOCK_DEFAULT_REPLY = "(mock) 안녕하세요. 가짜 AI의 응답이에요."

MockItem = str | Exception


class MockLLMClient:
    def __init__(self, replies: Iterable[MockItem] = (), *, default_reply: str | None = MOCK_DEFAULT_REPLY) -> None:
        self._queue: deque[MockItem] = deque(replies)
        self._default_reply = default_reply
        self.calls: list[list[Message]] = []  # 받은 메시지 기록(테스트에서 무엇을 보냈는지 확인)

    def queue(self, *replies: MockItem) -> None:
        self._queue.extend(replies)

    async def chat(self, messages: Sequence[Message]) -> LLMReply:
        if not messages:
            raise ValueError("messages가 비어 있어요.")
        self.calls.append(list(messages))

        if self._queue:
            item = self._queue.popleft()
        elif self._default_reply is not None:
            item = self._default_reply
        else:
            raise LLMConfigError("mock에 준비된 답이 없어요.")

        if isinstance(item, LLMError):
            item.usage = LLMUsage(calls=1)  # 실제 서버처럼 오류가 난 호출도 1번으로 센다
        if isinstance(item, Exception):
            raise item
        return LLMReply(content=item.strip(), model=MOCK_MODEL_NAME, finish_reason="stop")
