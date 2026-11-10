"""LLM 연결 구조 테스트 (D-014).

외부 API를 부르지 않는다. 실제 서버 대신 httpx.MockTransport로 가짜 응답(성공 · 429 · 401 · 5xx · 타임아웃 ·
깨진 본문)을 만들고, 재시도 대기는 기다리지 않는 sleep으로 바꿔서 확인한다.
"""

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import BaseModel

from app.llm import (
    LLMConfigError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMReply,
    LLMRequestError,
    LLMSettings,
    LLMUnavailable,
    LLMUsage,
    Message,
    MockLLMClient,
    OpenAICompatibleClient,
    complete_json,
    get_llm_client,
    load_llm_settings,
)
from app.llm.settings import (
    DEFAULT_LLM_TIMEOUT_SECONDS,
    EXAONE_BASE_URL,
    EXAONE_MODEL,
    LLM_MAX_TRANSIENT_ATTEMPTS,
    LOCAL_LLM_DEFAULT_BASE_URL,
    MAX_JSON_CANDIDATES,
    MAX_REPLY_CHARS,
)

FAKE_KEY = "test-key-should-never-appear-in-errors"
LLM_ENV_NAMES = (
    "LLM_PROVIDER",
    "EXAONE_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_REASONING_EFFORT",
    "LLM_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """셸이나 .env에 있는 실제 LLM 설정이 테스트에 섞이지 않게 모두 지운다."""
    for name in LLM_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _exaone_settings(**overrides: object) -> LLMSettings:
    values: dict[str, object] = {
        "provider": "exaone",
        "base_url": EXAONE_BASE_URL,
        "model": EXAONE_MODEL,
        "reasoning_effort": "low",
        "timeout_seconds": 60.0,
        "api_key": FAKE_KEY,
    }
    values.update(overrides)
    return LLMSettings(**values)  # type: ignore[arg-type]


def _ok_body(content: str = "\n\n안녕하세요!", **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "model": EXAONE_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "reasoning_content": "인사에 답한다."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 12, "total_tokens": 17},
    }
    body.update(extra)
    return body


class FakeServer:
    """정해 둔 응답을 차례로 돌려주는 가짜 AI 서버. 받은 요청을 기록한다."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def client(self, settings: LLMSettings | None = None) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            settings or _exaone_settings(),
            transport=httpx.MockTransport(self.handler),
            sleep=self.sleep,
        )


def _chat(client: OpenAICompatibleClient | MockLLMClient, text: str = "안녕"):
    return asyncio.run(client.chat([Message("user", text)]))


def _raises(exc_type: type[Exception], fn: Callable[[], object]) -> Exception:
    with pytest.raises(exc_type) as info:
        fn()
    assert FAKE_KEY not in str(info.value), "오류 문구에 API 키가 들어가면 안 된다"
    return info.value


# ---------------------------------------------------------------- 설정 읽기


def test_default_provider_is_mock_and_needs_no_key() -> None:
    settings = load_llm_settings()
    assert settings.provider == "mock"
    assert isinstance(get_llm_client(settings), MockLLMClient)


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    _raises(LLMConfigError, load_llm_settings)


def test_exaone_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "exaone")
    _raises(LLMConfigError, load_llm_settings)


def test_exaone_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", " EXAONE ")
    monkeypatch.setenv("EXAONE_API_KEY", FAKE_KEY)
    settings = load_llm_settings()
    assert (settings.base_url, settings.model, settings.reasoning_effort) == (EXAONE_BASE_URL, EXAONE_MODEL, "low")
    assert isinstance(get_llm_client(settings), OpenAICompatibleClient)


def test_settings_repr_hides_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "exaone")
    monkeypatch.setenv("EXAONE_API_KEY", FAKE_KEY)
    assert FAKE_KEY not in repr(load_llm_settings())


def test_exaone_rejects_unknown_reasoning_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "exaone")
    monkeypatch.setenv("EXAONE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("LLM_REASONING_EFFORT", "medium")  # EXAONE은 low · high · max만
    _raises(LLMConfigError, load_llm_settings)


def test_key_is_never_sent_over_plain_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "exaone")
    monkeypatch.setenv("EXAONE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("LLM_BASE_URL", "http://example.com/v1")
    _raises(LLMConfigError, load_llm_settings)


def test_local_requires_model_and_uses_ollama_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "local")
    _raises(LLMConfigError, load_llm_settings)

    monkeypatch.setenv("LLM_MODEL", "exaone3.5:2.4b")
    settings = load_llm_settings()
    assert settings.base_url == LOCAL_LLM_DEFAULT_BASE_URL
    assert settings.api_key == ""
    assert settings.reasoning_effort == ""  # 넣지 않으면 요청에 보내지 않음


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "nan", "inf"])
def test_timeout_must_be_positive_number(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", raw)
    _raises(LLMConfigError, load_llm_settings)


def test_provider_argument_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "exaone")  # 키 없음 → exaone이면 실패
    assert load_llm_settings("mock").provider == "mock"


# ---------------------------------------------------------------- OpenAI 호환 클라이언트


def test_chat_success_parses_exaone_reply() -> None:
    server = FakeServer(httpx.Response(200, json=_ok_body()))
    reply = _chat(server.client())

    assert reply.content == "안녕하세요!"  # 앞의 "\n\n"을 걷어 냄
    assert reply.reasoning == "인사에 답한다."
    assert reply.finish_reason == "stop"
    assert reply.usage == LLMUsage(calls=1, prompt_tokens=5, completion_tokens=12)

    request = server.requests[0]
    assert str(request.url) == f"{EXAONE_BASE_URL}/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    sent = json.loads(request.content)
    assert sent == {
        "model": EXAONE_MODEL,
        "messages": [{"role": "user", "content": "안녕"}],
        "reasoning_effort": "low",
    }
    assert server.sleeps == []


def test_local_sends_no_auth_header_and_no_reasoning_effort() -> None:
    settings = LLMSettings(provider="local", base_url=LOCAL_LLM_DEFAULT_BASE_URL, model="m")
    server = FakeServer(httpx.Response(200, json=_ok_body("hi")))
    _chat(server.client(settings))

    request = server.requests[0]
    assert "Authorization" not in request.headers
    assert "reasoning_effort" not in json.loads(request.content)


def test_rate_limit_is_not_retried_and_reads_retry_after() -> None:
    server = FakeServer(httpx.Response(429, headers={"Retry-After": "12"}, json={"error": "limit"}))
    exc = _raises(LLMRateLimited, lambda: _chat(server.client()))
    assert exc.retry_after_seconds == 12.0  # type: ignore[attr-defined]
    assert len(server.requests) == 1


def test_rate_limit_with_date_retry_after_gives_none() -> None:
    server = FakeServer(httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}))
    exc = _raises(LLMRateLimited, lambda: _chat(server.client()))
    assert exc.retry_after_seconds is None  # type: ignore[attr-defined]


@pytest.mark.parametrize("status", [401, 402, 403, 404, 302])
def test_config_errors_are_not_retried(status: int) -> None:
    server = FakeServer(httpx.Response(status, headers={"Location": "https://elsewhere.example"}))
    _raises(LLMConfigError, lambda: _chat(server.client()))
    assert len(server.requests) == 1


@pytest.mark.parametrize("status", [400, 413, 422])
def test_rejected_requests_are_not_retried(status: int) -> None:
    server = FakeServer(httpx.Response(status, json={"error": {"message": "too long"}}))
    exc = _raises(LLMRequestError, lambda: _chat(server.client()))
    assert exc.status_code == status  # type: ignore[attr-defined]
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    "first",
    [
        httpx.Response(503),
        httpx.Response(408),
        httpx.Response(200, text="<html>gateway</html>"),  # JSON이 아닌 본문
        httpx.Response(200, json={"choices": []}),  # 모양이 깨진 응답
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
    ],
    ids=["503", "408", "non-json", "empty-choices", "timeout", "connect-error"],
)
def test_transient_failure_is_retried_once_then_succeeds(first: httpx.Response | Exception) -> None:
    server = FakeServer(first, httpx.Response(200, json=_ok_body("다시 성공")))
    reply = _chat(server.client())
    assert reply.content == "다시 성공"
    assert len(server.requests) == 2
    assert server.sleeps == [1.0]


def test_transient_failure_gives_up_after_max_attempts() -> None:
    server = FakeServer(*[httpx.Response(502) for _ in range(LLM_MAX_TRANSIENT_ATTEMPTS)])
    exc = _raises(LLMUnavailable, lambda: _chat(server.client()))
    assert "HTTP 502" in str(exc)
    assert len(server.requests) == LLM_MAX_TRANSIENT_ATTEMPTS


def test_null_content_becomes_empty_string() -> None:
    body = _ok_body()
    body["choices"][0]["message"]["content"] = None  # type: ignore[index]
    body["choices"][0]["finish_reason"] = "length"  # type: ignore[index]
    reply = _chat(FakeServer(httpx.Response(200, json=body)).client())
    assert (reply.content, reply.finish_reason) == ("", "length")


def test_usage_ignores_non_integer_values() -> None:
    body = _ok_body(usage={"prompt_tokens": True, "completion_tokens": "12"})
    reply = _chat(FakeServer(httpx.Response(200, json=body)).client())
    assert reply.usage == LLMUsage(calls=1)


# ---------------------------------------------------------------- mock


def test_mock_returns_queued_replies_then_default() -> None:
    mock = MockLLMClient(["첫째", LLMRateLimited("429")])
    assert _chat(mock).content == "첫째"
    with pytest.raises(LLMRateLimited):
        _chat(mock)
    assert _chat(mock).content.startswith("(mock)")
    assert len(mock.calls) == 3


def test_mock_without_default_fails_clearly() -> None:
    with pytest.raises(LLMConfigError):
        _chat(MockLLMClient(default_reply=None))


# ---------------------------------------------------------------- JSON 형식 검사 · 재시도


class QuizItem(BaseModel):
    question: str
    answer: str
    source_chunk_id: int


def _complete(mock: MockLLMClient, messages: list[Message] | None = None):
    return asyncio.run(complete_json(mock, messages or [Message("user", "퀴즈를 만들어 줘")], QuizItem))


@pytest.mark.parametrize(
    "content",
    [
        '{"question": "Q", "answer": "A", "source_chunk_id": 3}',
        '```json\n{"question": "Q", "answer": "A", "source_chunk_id": 3}\n```',
        '여기 있어요:\n{"question": "Q", "answer": "A", "source_chunk_id": 3}\n참고하세요.',
        '```\n{"question": "Q", "answer": "A", "source_chunk_id": 3}\n```',  # 언어 표시 없는 코드 블록
        '```json\n{"question": "Q", "answer": "A", "source_chunk_id": 3}',  # 닫히지 않은 코드 블록
        '형식은 {question, answer}예요: {"question": "Q", "answer": "A", "source_chunk_id": 3} {끝}',
        '예시: {"question": "예"}\n답: {"question": "Q", "answer": "A", "source_chunk_id": 3}',
        '{"question": "Q", "answer": "A", "source_chunk_id": 3}' + " " * 100_000 + "x",
        '[{"question": "Q", "answer": "A", "source_chunk_id": 3}]',  # 배열로 감싸도 안의 객체를 검사
    ],
    ids=[
        "plain",
        "fenced",
        "with-prose",
        "fence-no-lang",
        "unclosed-fence",
        "braces-in-prose",
        "example-object-first",
        "long-whitespace",
        "array-wrapped",
    ],
)
def test_complete_json_accepts_common_reply_shapes(content: str) -> None:
    result = _complete(MockLLMClient([content]))
    assert result.value == QuizItem(question="Q", answer="A", source_chunk_id=3)
    assert result.attempts == 1
    assert result.usage == LLMUsage(calls=1)


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        ("", "no_json_object"),
        ("그냥 문장이에요.", "no_json_object"),
        ("{" * 50_000, "no_json_object"),  # 중괄호가 아주 많아도 시작점 수 상한으로 금방 끝남
        ("x" * (MAX_REPLY_CHARS + 1), "reply_too_long"),
        # 시작점 상한: 깨진 { 가 상한만큼 앞에 있으면 뒤의 맞는 객체까지 가지 않는다
        ("{x " * MAX_JSON_CANDIDATES + '{"question": "Q", "answer": "A", "source_chunk_id": 3}', "no_json_object"),
    ],
    ids=["empty", "prose-only", "many-braces", "too-long", "candidate-limit"],
)
def test_complete_json_rejects_replies_without_valid_object(content: str, kind: str) -> None:
    with pytest.raises(LLMInvalidOutput) as info:
        _complete(MockLLMClient([content, content]))
    assert kind in str(info.value)


def test_complete_json_retries_once_with_problem_description() -> None:
    secret_note = "팀원 김OO의 전화번호 010-0000-0000"
    bad = json.dumps({"question": secret_note, "answer": "A", "source_chunk_id": "세 번째"}, ensure_ascii=False)
    good = '{"question": "Q", "answer": "A", "source_chunk_id": 3}'
    mock = MockLLMClient([bad, good])

    result = _complete(mock)
    assert result.attempts == 2
    assert result.value.source_chunk_id == 3

    retry_messages = mock.calls[1]
    assert retry_messages[-2] == Message("assistant", bad)  # 틀린 답을 보여 주고
    fix = retry_messages[-1]
    assert fix.role == "user" and "source_chunk_id" in fix.content  # 어느 칸이 틀렸는지 알려 줌
    assert "세 번째" not in fix.content  # 검사 오류 설명에는 답 원문 값을 넣지 않음


def test_complete_json_gives_up_after_max_attempts() -> None:
    mock = MockLLMClient(["JSON이 아님", '{"question": "Q"}'])
    with pytest.raises(LLMInvalidOutput) as info:
        _complete(mock)
    exc = info.value
    assert exc.attempts == 2
    assert exc.raw_content == '{"question": "Q"}'  # 평가 로그용 원문은 속성에만
    assert '{"question": "Q"}' not in str(exc)
    assert "missing" in str(exc)  # 문구에는 오류 종류만
    assert "answer" in exc.detail  # 위치 · 설명은 속성에만
    assert exc.usage == LLMUsage(calls=2)
    assert len(mock.calls) == 2


def test_complete_json_does_not_retry_rate_limit() -> None:
    mock = MockLLMClient([LLMRateLimited("429"), '{"question": "Q", "answer": "A", "source_chunk_id": 1}'])
    with pytest.raises(LLMRateLimited):
        _complete(mock)
    assert len(mock.calls) == 1


class TruncatingClient:
    """항상 길이 제한에서 잘린 답을 돌려주는 가짜 클라이언트(mock은 finish_reason이 항상 stop이라 따로 만듦)."""

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    async def chat(self, messages):  # type: ignore[no-untyped-def]
        self.calls.append(list(messages))
        return LLMReply(content='{"question": "Q", "ans', model="t", finish_reason="length")


def test_complete_json_marks_truncated_reply() -> None:
    client = TruncatingClient()
    with pytest.raises(LLMInvalidOutput) as info:
        asyncio.run(complete_json(client, [Message("user", "만들어 줘")], QuizItem))
    assert "truncated" in str(info.value)  # 문구에는 종류만
    assert "잘렸어요" in info.value.detail
    assert "잘렸어요" in client.calls[1][-1].content  # 다시 요청할 때도 잘렸다고 알려 줌


def test_schema_instruction_is_prepended_as_system_message() -> None:
    mock = MockLLMClient(['{"question": "Q", "answer": "A", "source_chunk_id": 1}'])
    _complete(mock)
    first = mock.calls[0][0]
    assert first.role == "system" and "source_chunk_id" in first.content
    assert mock.calls[0][1] == Message("user", "퀴즈를 만들어 줘")


def test_schema_instruction_is_merged_into_existing_system_message() -> None:
    mock = MockLLMClient(['{"question": "Q", "answer": "A", "source_chunk_id": 1}'])
    _complete(mock, [Message("system", "너는 복습 퀴즈 출제자야."), Message("user", "만들어 줘")])
    sent = mock.calls[0]
    assert [m.role for m in sent] == ["system", "user"]  # system이 두 개가 되지 않음
    assert sent[0].content.startswith("너는 복습 퀴즈 출제자야.")
    assert "JSON 스키마" in sent[0].content


def test_empty_reply_is_not_sent_back_as_assistant_message() -> None:
    mock = MockLLMClient(["", '{"question": "Q", "answer": "A", "source_chunk_id": 1}'])
    _complete(mock)
    assert [m.role for m in mock.calls[1]] == ["system", "user", "user"]


# ---------------------------------------------------------------- 2차 보강 (1차 리뷰 지적)

GOOD_QUIZ = '{"question": "Q", "answer": "A", "source_chunk_id": 1}'


@pytest.mark.parametrize(
    "body",
    [
        {"choices": ["문자열"]},  # choices[0]이 객체가 아님
        {"choices": [{"finish_reason": "stop"}]},  # message 없음
        {"choices": [{"message": {"content": ["조각"]}}]},  # content가 문자열이 아님
    ],
    ids=["choice-not-object", "no-message", "content-not-string"],
)
def test_broken_reply_shapes_are_retried_then_unavailable(body: dict[str, object]) -> None:
    server = FakeServer(httpx.Response(200, json=body), httpx.Response(200, json=body))
    exc = _raises(LLMUnavailable, lambda: _chat(server.client()))
    assert "invalid response body" in str(exc)
    assert exc.usage == LLMUsage(calls=2)  # type: ignore[attr-defined]


def test_deeply_nested_body_is_treated_as_broken_reply() -> None:
    server = FakeServer(httpx.Response(200, content=b"[" * 200_000), httpx.Response(200, json=_ok_body("ok")))
    assert _chat(server.client()).content == "ok"
    assert len(server.requests) == 2


@pytest.mark.parametrize(
    ("second", "expected"),
    [(httpx.Response(429), LLMRateLimited), (httpx.Response(401), LLMConfigError)],
    ids=["then-429", "then-401"],
)
def test_error_after_transient_retry_counts_both_calls(second: httpx.Response, expected: type[Exception]) -> None:
    server = FakeServer(httpx.Response(503), second)
    exc = _raises(expected, lambda: _chat(server.client()))
    assert exc.usage == LLMUsage(calls=2)  # type: ignore[attr-defined]
    assert len(server.requests) == 2


def test_two_timeouts_give_unavailable_with_two_calls() -> None:
    server = FakeServer(httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"))
    exc = _raises(LLMUnavailable, lambda: _chat(server.client()))
    assert "timeout" in str(exc)
    assert exc.usage == LLMUsage(calls=2)  # type: ignore[attr-defined]


@pytest.mark.parametrize("raw", ["nan", "inf", "-1"])
def test_strange_retry_after_gives_none(raw: str) -> None:
    server = FakeServer(httpx.Response(429, headers={"Retry-After": raw}))
    exc = _raises(LLMRateLimited, lambda: _chat(server.client()))
    assert exc.retry_after_seconds is None  # type: ignore[attr-defined]


def test_timeouts_are_passed_to_each_request() -> None:
    server = FakeServer(httpx.Response(200, json=_ok_body()))
    _chat(server.client())
    sent = server.requests[0].extensions["timeout"]
    assert sent["read"] == DEFAULT_LLM_TIMEOUT_SECONDS
    assert sent["connect"] == 5.0


def test_local_auth_error_does_not_mention_exaone_key() -> None:
    settings = LLMSettings(provider="local", base_url=LOCAL_LLM_DEFAULT_BASE_URL, model="m")
    exc = _raises(LLMConfigError, lambda: _chat(FakeServer(httpx.Response(401)).client(settings)))
    assert "EXAONE_API_KEY" not in str(exc)


def test_empty_messages_are_rejected() -> None:
    with pytest.raises(ValueError):
        asyncio.run(FakeServer().client().chat([]))
    with pytest.raises(ValueError):
        asyncio.run(MockLLMClient().chat([]))
    with pytest.raises(ValueError):
        asyncio.run(complete_json(MockLLMClient(), [], QuizItem))


@pytest.mark.parametrize("kwargs", [{"max_attempts": 0}, {"deadline_seconds": 0}])
def test_complete_json_rejects_bad_limits(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        asyncio.run(complete_json(MockLLMClient(), [Message("user", "x")], QuizItem, **kwargs))  # type: ignore[arg-type]


def test_usage_adds_connection_retries_and_format_retries() -> None:
    server = FakeServer(
        httpx.Response(503),  # 1번째 형식 시도 — 연결 재시도
        httpx.Response(200, json=_ok_body("JSON 아님")),  # 1번째 형식 시도 — 형식 틀림
        httpx.Response(200, json=_ok_body(GOOD_QUIZ)),  # 2번째 형식 시도 — 통과
    )
    result = asyncio.run(complete_json(server.client(), [Message("user", "만들어 줘")], QuizItem))
    assert result.attempts == 2
    assert result.usage == LLMUsage(calls=3, prompt_tokens=10, completion_tokens=24)


def test_rate_limit_on_second_format_attempt_keeps_earlier_usage() -> None:
    server = FakeServer(httpx.Response(200, json=_ok_body("JSON 아님")), httpx.Response(429))
    with pytest.raises(LLMRateLimited) as info:
        asyncio.run(complete_json(server.client(), [Message("user", "만들어 줘")], QuizItem))
    assert info.value.usage == LLMUsage(calls=2, prompt_tokens=5, completion_tokens=12)


class SlowClient:
    """답을 아주 늦게 주는 가짜 클라이언트(전체 시간 상한 확인용)."""

    async def chat(self, messages):  # type: ignore[no-untyped-def]
        await asyncio.sleep(10)
        return LLMReply(content=GOOD_QUIZ, model="slow")


def test_complete_json_stops_at_total_deadline(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="app.llm"):
        with pytest.raises(LLMUnavailable) as info:
            asyncio.run(complete_json(SlowClient(), [Message("user", "x")], QuizItem, deadline_seconds=0.05))
    assert "전체 시간 상한" in str(info.value)
    # 끝나지 않은 호출은 연결 재시도 최대치로 센다(적게 세지 않게)
    assert info.value.usage == LLMUsage(calls=LLM_MAX_TRANSIENT_ATTEMPTS)
    assert "전체 시간 상한" in caplog.text


class BadThenSlowClient:
    """첫 답은 형식이 틀리고(토큰 보고), 두 번째 호출은 끝나지 않는 가짜 클라이언트."""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMReply(content="JSON 아님", model="t", usage=LLMUsage(calls=1, prompt_tokens=7, completion_tokens=3))
        await asyncio.sleep(10)
        return LLMReply(content=GOOD_QUIZ, model="t")


def test_deadline_after_earlier_attempt_keeps_its_usage() -> None:
    with pytest.raises(LLMUnavailable) as info:
        asyncio.run(complete_json(BadThenSlowClient(), [Message("user", "x")], QuizItem, deadline_seconds=0.1))
    assert info.value.usage == LLMUsage(
        calls=1 + LLM_MAX_TRANSIENT_ATTEMPTS, prompt_tokens=7, completion_tokens=3
    )


class OwnTimeoutClient:
    """우리 마감과 상관없는 TimeoutError를 내는 가짜 클라이언트."""

    async def chat(self, messages):  # type: ignore[no-untyped-def]
        raise TimeoutError("다른 곳의 타임아웃")


def test_other_timeout_errors_are_not_turned_into_deadline() -> None:
    with pytest.raises(TimeoutError) as info:
        asyncio.run(complete_json(OwnTimeoutClient(), [Message("user", "x")], QuizItem))
    assert not isinstance(info.value, LLMUnavailable)
    assert "다른 곳의 타임아웃" in str(info.value)


class ManyFields(BaseModel):
    a: str
    b: str
    c: str
    d: str
    e: str
    f: str
    g: str


def test_long_error_list_is_shortened_for_retry_request() -> None:
    mock = MockLLMClient(["{}", "{}"])
    with pytest.raises(LLMInvalidOutput) as info:
        asyncio.run(complete_json(mock, [Message("user", "x")], ManyFields))
    assert "외 2개" in info.value.detail
    assert "missing×7" in str(info.value)


class Strict(BaseModel):
    model_config = {"extra": "forbid"}
    question: str


def test_invalid_output_message_does_not_contain_reply_keys() -> None:
    leaked_key = "팀원실명키"
    reply = json.dumps({"question": "Q", leaked_key: 1}, ensure_ascii=False)
    with pytest.raises(LLMInvalidOutput) as info:
        asyncio.run(complete_json(MockLLMClient([reply, reply]), [Message("user", "x")], Strict))
    assert leaked_key not in str(info.value)  # 문구에는 종류(extra_forbidden)만
    assert "extra_forbidden" in str(info.value)


def test_mock_default_reply_is_not_json() -> None:
    """기본 mock은 JSON을 주지 않는다 → 기능마다 가짜 답을 등록해야 한다(mock.py 설명)."""
    with pytest.raises(LLMInvalidOutput):
        asyncio.run(complete_json(MockLLMClient(), [Message("user", "x")], QuizItem))


def test_retry_is_logged_without_key_or_content(caplog: pytest.LogCaptureFixture) -> None:
    server = FakeServer(httpx.Response(503), httpx.Response(200, json=_ok_body("비밀 노트 내용")))
    with caplog.at_level("WARNING", logger="app.llm"):
        _chat(server.client())
    assert "HTTP 503" in caplog.text
    assert FAKE_KEY not in caplog.text
    assert "비밀 노트 내용" not in caplog.text


def test_format_error_logs_contain_only_error_kinds(caplog: pytest.LogCaptureFixture) -> None:
    leaked_key = "팀원실명키"
    secret_value = "비밀 노트 내용"
    reply = json.dumps({"question": secret_value, leaked_key: 1}, ensure_ascii=False)
    with caplog.at_level("WARNING", logger="app.llm"):
        with pytest.raises(LLMInvalidOutput):
            asyncio.run(complete_json(MockLLMClient([reply, reply]), [Message("user", "x")], Strict))
    assert "extra_forbidden" in caplog.text  # 형식 오류 · 포기 로그는 종류만
    assert "포기" in caplog.text
    assert leaked_key not in caplog.text
    assert secret_value not in caplog.text
