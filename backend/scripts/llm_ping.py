"""실제 AI 연결 확인 — "안녕" 한 문장을 보내고 답을 찍는다 (D-014).

backend 폴더에서:
    uv run --env-file .env python -m scripts.llm_ping           # LLM_PROVIDER 설정대로
    uv run --env-file .env python -m scripts.llm_ping exaone    # 설정과 상관없이 exaone으로

키 · 주소 같은 설정값은 출력하지 않는다. pytest에는 넣지 않는다
(테스트가 외부 API · 키 · 사용량에 기대지 않게, D-014).
"""

import asyncio
import sys
import time

from app.llm import LLMError, Message, get_llm_client, load_llm_settings

PING_MESSAGE = "안녕"
MAX_PRINT_CHARS = 300


async def _ping(provider: str | None) -> int:
    try:
        settings = load_llm_settings(provider)
        client = get_llm_client(settings)
        started = time.perf_counter()
        reply = await client.chat([Message("user", PING_MESSAGE)])
    except LLMError as exc:
        print(f"실패: {type(exc).__name__}: {exc}")
        return 1
    elapsed = time.perf_counter() - started

    print(f"성공: provider={settings.provider}, model={reply.model}, {elapsed:.1f}초, finish_reason={reply.finish_reason}")
    print(f"사용량: 호출 {reply.usage.calls}번, 토큰 입력 {reply.usage.prompt_tokens} · 출력 {reply.usage.completion_tokens}")
    print(f"답: {reply.content[:MAX_PRINT_CHARS]}")
    return 0


def main() -> None:
    # Windows에서 출력을 파이프로 넘기면 기본 인코딩(cp949)이 일부 글자를 못 써서 멈춘다
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    provider = sys.argv[1] if len(sys.argv) > 1 else None
    raise SystemExit(asyncio.run(_ping(provider)))


if __name__ == "__main__":
    main()
