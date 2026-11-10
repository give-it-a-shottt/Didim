"""LLM 연결 (D-014). 기능 코드는 이 패키지에서 가져다 쓴다.

    client = get_llm_client()                       # LLM_PROVIDER로 mock · exaone · local 중 하나
    result = await complete_json(client, messages, QuizSchema)
    result.value                                    # 스키마 검사를 통과한 결과
    result.usage                                    # 호출 수 · 토큰(하루 상한용)
"""

from app.llm.base import (
    LLMClient,
    LLMConfigError,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMReply,
    LLMRequestError,
    LLMUnavailable,
    LLMUsage,
    Message,
)
from app.llm.mock import MockLLMClient
from app.llm.openai_compat import OpenAICompatibleClient
from app.llm.settings import LLMSettings, load_llm_settings
from app.llm.structured import StructuredReply, complete_json


def get_llm_client(settings: LLMSettings | None = None) -> LLMClient:
    """설정에 맞는 AI 클라이언트를 만든다. 설정이 틀리면 LLMConfigError."""
    settings = settings if settings is not None else load_llm_settings()
    if settings.provider == "mock":
        return MockLLMClient()
    return OpenAICompatibleClient(settings)


__all__ = [
    "LLMClient",
    "LLMConfigError",
    "LLMError",
    "LLMInvalidOutput",
    "LLMRateLimited",
    "LLMReply",
    "LLMRequestError",
    "LLMSettings",
    "LLMUnavailable",
    "LLMUsage",
    "Message",
    "MockLLMClient",
    "OpenAICompatibleClient",
    "StructuredReply",
    "complete_json",
    "get_llm_client",
    "load_llm_settings",
]
