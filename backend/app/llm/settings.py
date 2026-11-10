"""LLM 설정 읽기 (D-014). 값은 backend/.env에서 읽고, 키는 서버에서만 쓴다.

LLM_PROVIDER          mock(기본) | exaone | local
EXAONE_API_KEY        exaone일 때 필요
LLM_BASE_URL          주소를 바꿀 때만(기본: exaone은 공식 API 주소, local은 이 컴퓨터의 Ollama 주소).
                      Ollama를 다른 컴퓨터(예: 집 데스크톱)에서 켜면 그 컴퓨터 주소를 넣는다
LLM_MODEL             모델 이름(exaone은 기본값 있음, local은 꼭 필요)
LLM_REASONING_EFFORT  exaone: low(기본) | high | max. local은 넣을 때만 보낸다
LLM_TIMEOUT_SECONDS   데이터가 오가는 간격의 상한(기본 60초). 재시도를 합친 전체 상한은 아래 상수(180초)
"""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.llm.base import LLMConfigError

LLM_PROVIDERS = ("mock", "exaone", "local")
DEFAULT_LLM_PROVIDER = "mock"  # 키 없이 개발 · 테스트가 돌아가게(D-014)

# K-EXAONE 2.5 (2026-11-09 공개 문서 기준, D-014)
EXAONE_BASE_URL = "https://api.exaone.ai/v1"
EXAONE_MODEL = "k-exaone_v2.5"
EXAONE_REASONING_EFFORTS = ("low", "high", "max")
DEFAULT_EXAONE_REASONING_EFFORT = "low"  # 가장 빠르고 가벼움. 품질이 모자라면 기능별로 올린다

# 내 컴퓨터의 오픈소스 모델(Ollama 기본 주소). localhost 대신 127.0.0.1(T-002)
LOCAL_LLM_DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"

# EXAONE은 답하기 전에 항상 추론부터 해서 일반 API보다 오래 걸릴 수 있다
# 아래 값은 사용자 확인(2026-11-10).
# 60초는 "데이터가 오가는 간격"의 상한이라, 재시도까지 합친 전체 시간은 따로 막는다(180초, complete_json).
DEFAULT_LLM_TIMEOUT_SECONDS = 60.0
LLM_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS = 180.0

# 재시도 규칙 — "처음 1번 + 다시 1번"
LLM_MAX_TRANSIENT_ATTEMPTS = 2  # 네트워크 · 타임아웃 · 5xx
LLM_TRANSIENT_RETRY_DELAY_SECONDS = 1.0
LLM_MAX_FORMAT_ATTEMPTS = 2  # 답이 JSON 형식에 안 맞을 때

# 답 검사 상한 — 비정상적으로 긴 답 · 중괄호가 많은 답에서 검사가 오래 걸리지 않게
MAX_REPLY_CHARS = 200_000
MAX_JSON_CANDIDATES = 20  # 답 안에서 JSON 객체 시작점({)을 몇 개까지 읽어 볼지

_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str = ""
    model: str = ""
    reasoning_effort: str = ""  # 빈 값이면 요청에 넣지 않는다
    timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS
    # repr=False: 설정 객체를 로그로 찍어도 키가 나오지 않게
    api_key: str = field(default="", repr=False)


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _read_timeout() -> float:
    raw = _env("LLM_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_LLM_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise LLMConfigError("LLM_TIMEOUT_SECONDS는 0보다 큰 숫자(초)여야 해요.") from None
    if not value > 0 or value == float("inf"):
        raise LLMConfigError("LLM_TIMEOUT_SECONDS는 0보다 큰 숫자(초)여야 해요.")
    return value


def _check_base_url(base_url: str, *, has_key: bool) -> str:
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LLMConfigError("LLM_BASE_URL은 http:// 또는 https://로 시작하는 주소여야 해요.")
    # 키를 암호화 안 된 주소로 보내지 않는다. 내 컴퓨터 안(127.0.0.1)은 예외.
    if has_key and parts.scheme != "https" and parts.hostname not in _LOCAL_HOSTS:
        raise LLMConfigError("API 키를 보내는 주소는 https://여야 해요.")
    return base_url.rstrip("/")


def load_llm_settings(provider: str | None = None) -> LLMSettings:
    """환경변수에서 LLM 설정을 읽고 검사한다. 틀리면 이유를 적은 LLMConfigError.

    provider를 넘기면 LLM_PROVIDER 대신 그 값을 쓴다(연결 확인 스크립트용).
    """
    name = (provider if provider is not None else _env("LLM_PROVIDER")).strip().lower()
    name = name or DEFAULT_LLM_PROVIDER
    if name not in LLM_PROVIDERS:
        raise LLMConfigError(f"LLM_PROVIDER는 {' | '.join(LLM_PROVIDERS)} 중 하나여야 해요.")

    if name == "mock":
        return LLMSettings(provider="mock", model="mock")

    timeout_seconds = _read_timeout()

    if name == "exaone":
        api_key = _env("EXAONE_API_KEY")
        if not api_key:
            raise LLMConfigError("LLM_PROVIDER=exaone이면 EXAONE_API_KEY가 필요해요(backend/.env).")
        effort = _env("LLM_REASONING_EFFORT").lower() or DEFAULT_EXAONE_REASONING_EFFORT
        if effort not in EXAONE_REASONING_EFFORTS:
            raise LLMConfigError(
                f"EXAONE의 LLM_REASONING_EFFORT는 {' | '.join(EXAONE_REASONING_EFFORTS)} 중 하나여야 해요."
            )
        return LLMSettings(
            provider="exaone",
            base_url=_check_base_url(_env("LLM_BASE_URL") or EXAONE_BASE_URL, has_key=True),
            model=_env("LLM_MODEL") or EXAONE_MODEL,
            reasoning_effort=effort,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )

    # local: Ollama · LM Studio 같은 OpenAI 호환 서버. 키 없이 부른다.
    model = _env("LLM_MODEL")
    if not model:
        raise LLMConfigError("LLM_PROVIDER=local이면 LLM_MODEL(내려받은 모델 이름)이 필요해요.")
    return LLMSettings(
        provider="local",
        base_url=_check_base_url(_env("LLM_BASE_URL") or LOCAL_LLM_DEFAULT_BASE_URL, has_key=False),
        model=model,
        reasoning_effort=_env("LLM_REASONING_EFFORT").lower(),
        timeout_seconds=timeout_seconds,
    )
