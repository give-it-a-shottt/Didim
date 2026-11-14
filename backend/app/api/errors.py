"""여러 라우터가 같이 쓰는 오류 문구와 AI 오류 → HTTP 상태 변환 (F-006 1차 리뷰 R1 — 라우터끼리 서로 가져다 쓰지 않게).

AI를 부르는 기능(문제 만들기 · 카드 후보 찾기)은 오류를 똑같이 다룬다:
- 형식이 틀린 AI 답 → 502(문구는 기능마다), AI 설정 오류(키 거절 · 모델 이름 틀림) → 500, 나머지(AI 서버 한도 ·
  연결 안 됨 · 우리 요청이 거절됨 — 사용자가 고칠 수 없음) → 503. 화면에는 설정 내용을 보여 주지 않는다.
"""

from collections.abc import Callable, Sequence

from fastapi import HTTPException, status

from app.llm import LLMClient, LLMConfigError, LLMError, LLMInvalidOutput, Message, MockLLMClient
from app.llm import get_llm_client, load_llm_settings

NOTE_NOT_FOUND_DETAIL = "노트를 찾을 수 없어요."
UNAVAILABLE_DETAIL = "지금은 AI에 연결할 수 없어요. 잠시 뒤 다시 시도해 주세요."
AI_NOT_CONFIGURED_DETAIL = "서버의 AI 설정이 완료되지 않았어요."
# 사용자당 AI 작업은 기능을 가리지 않고 1개(D-020, app/services/note_claim.py)
OTHER_AI_WORK_DETAIL = "다른 AI 작업(문제 만들기 · 카드 후보 찾기 · 공고 분석 · 자소서 초안)이 진행 중이에요. 끝난 뒤 다시 시도해 주세요."


def daily_limit_detail(limit: int) -> str:
    return f"오늘 AI 사용량({limit}회)을 다 썼어요. 한국 시간 0시에 다시 쓸 수 있어요."


def llm_client_or_500(mock_responder: Callable[[Sequence[Message]], str]) -> LLMClient:
    """설정대로 AI를 고른다. LLM_PROVIDER=mock(기본)이면 기능별 가짜 답을 주는 mock(키 없이 화면 확인용). 설정이 틀리면 500."""
    try:
        settings = load_llm_settings()
        if settings.provider == "mock":
            return MockLLMClient(responder=mock_responder)
        return get_llm_client(settings)
    except LLMConfigError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=AI_NOT_CONFIGURED_DETAIL) from exc


def llm_error_status(exc: LLMError, *, invalid_output_detail: str) -> tuple[int, str]:
    if isinstance(exc, LLMInvalidOutput):
        return status.HTTP_502_BAD_GATEWAY, invalid_output_detail
    if isinstance(exc, LLMConfigError):  # 키 거절 · 모델 이름 틀림 등은 부른 뒤에야 알 수 있다
        return status.HTTP_500_INTERNAL_SERVER_ERROR, AI_NOT_CONFIGURED_DETAIL
    # LLMRateLimited(AI 서버 한도) · LLMUnavailable · LLMRequestError(우리 요청이 거절됨 — 사용자가 고칠 수 없음)
    return status.HTTP_503_SERVICE_UNAVAILABLE, UNAVAILABLE_DETAIL
