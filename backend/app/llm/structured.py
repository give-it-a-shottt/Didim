"""AI 답을 정해진 JSON 스키마로 받고 검사한다 (원칙 3, D-014).

EXAONE 문서에는 "JSON으로만 답하기"(구조화 출력) 기능이 없어서, 검사는 우리 쪽에서 한다.
1. 요청에 "이 스키마에 맞는 JSON 하나만"이라는 안내와 스키마를 붙인다.
2. 답 안의 `{` 위치마다 JSON 객체를 읽어 본다(```json 감싸기 · 앞뒤 설명 문장이 있어도 됨).
3. 읽힌 객체를 pydantic 모델로 검사한다(타입 · 필수 칸). 처음 통과한 객체를 쓴다.
4. 틀리면 무엇이 틀렸는지 알려 주고 1번 더 요청한다. 그래도 틀리면 LLMInvalidOutput.

재시도까지 합친 전체 시간은 180초로 막는다(넘으면 LLMUnavailable).
429 · 연결 오류 같은 호출 오류는 여기서 다시 부르지 않고 그대로 올려 보낸다(그 규칙은 openai_compat.py).
"""

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.base import LLMClient, LLMError, LLMInvalidOutput, LLMReply, LLMUnavailable, LLMUsage, Message
from app.llm.settings import (
    DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS,
    LLM_MAX_FORMAT_ATTEMPTS,
    LLM_MAX_TRANSIENT_ATTEMPTS,
    MAX_JSON_CANDIDATES,
    MAX_REPLY_CHARS,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_DECODER = json.JSONDecoder()
MAX_REPORTED_ERRORS = 5  # 다시 요청할 때 알려 줄 오류 개수(너무 길어지지 않게)


@dataclass(frozen=True)
class StructuredReply(Generic[T]):
    value: T  # 스키마 검사를 통과한 결과
    reply: LLMReply  # 마지막(통과한) 호출의 원래 답 — 모델 이름 등
    attempts: int  # 형식 검사 시도 횟수. 실제 HTTP 호출 수는 usage.calls(연결 재시도 포함)
    usage: LLMUsage  # 모든 시도를 합친 사용량. 하루 상한(원칙 4)은 이 값으로 센다


class _FormatProblem(Exception):
    """답이 형식에 맞지 않음(이 파일 안에서만 씀).

    detail: 위치 · 설명. AI에게 다시 요청할 때만 쓰고 오류 문구에는 넣지 않는다(답 값이 섞일 수 있음).
    kinds:  오류 종류만(예: "missing×2"). 오류 문구 · 로그에 쓴다.
    """

    def __init__(self, detail: str, kinds: str) -> None:
        super().__init__(kinds)
        self.detail = detail
        self.kinds = kinds


@dataclass
class _Progress:
    usage: LLMUsage


def iter_json_object_texts(text: str) -> Iterator[str]:
    """답 안에서 JSON 객체로 읽히는 부분을 앞에서부터 돌려준다.

    정규식 대신 `{` 위치마다 표준 json으로 읽어 본다. 앞뒤 설명에 중괄호가 있어도 다음 `{`로 넘어간다.
    읽어 볼 시작점 수는 MAX_JSON_CANDIDATES로 막는다(중괄호가 많은 답에서 오래 걸리지 않게).
    """
    start = text.find("{")
    tried = 0
    while start != -1 and tried < MAX_JSON_CANDIDATES:
        tried += 1
        try:
            obj, end = _DECODER.raw_decode(text, start)
        except (ValueError, RecursionError):
            start = text.find("{", start + 1)
            continue
        if isinstance(obj, dict):
            yield text[start:end]
            start = text.find("{", end)  # 읽힌 객체 안쪽의 { 는 그 객체의 일부라 건너뛴다
        else:
            start = text.find("{", start + 1)


def describe_validation_error(exc: ValidationError) -> str:
    """검사 오류를 짧은 문장으로(위치 + 설명). AI에게 다시 요청할 때만 쓴다."""
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    parts = []
    for error in errors[:MAX_REPORTED_ERRORS]:
        location = ".".join(str(part) for part in error["loc"]) or "(전체)"
        parts.append(f"{location}: {error['msg']}")
    if len(errors) > MAX_REPORTED_ERRORS:
        parts.append(f"외 {len(errors) - MAX_REPORTED_ERRORS}개")
    return "; ".join(parts)


def summarize_error_kinds(exc: ValidationError) -> str:
    """검사 오류의 종류만 센다(예: "missing×2, int_parsing×1"). 답 값 · 키 이름이 들어가지 않는다."""
    counts = Counter(error["type"] for error in exc.errors(include_url=False))
    return ", ".join(f"{kind}×{count}" for kind, count in counts.items())


def _check_reply(content: str, schema: type[T]) -> T:
    if len(content) > MAX_REPLY_CHARS:
        raise _FormatProblem(f"답이 너무 길어요({MAX_REPLY_CHARS}자 초과).", "reply_too_long")

    first_error: ValidationError | None = None
    for candidate in iter_json_object_texts(content):
        try:
            return schema.model_validate_json(candidate)
        except ValidationError as exc:
            first_error = first_error or exc

    if first_error is None:
        raise _FormatProblem("답에서 JSON 객체를 찾지 못했어요.", "no_json_object")
    raise _FormatProblem(describe_validation_error(first_error), summarize_error_kinds(first_error))


def schema_instruction(schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return (
        "답은 아래 JSON 스키마에 맞는 JSON 객체 하나만 보내세요. "
        "설명 문장이나 코드 블록 표시(```)는 붙이지 마세요.\n"
        f"JSON 스키마: {schema_json}"
    )


def _with_schema_instruction(messages: Sequence[Message], schema: type[BaseModel]) -> list[Message]:
    """스키마 안내를 system 메시지에 붙인다.

    system이 이미 맨 앞에 있으면 그 끝에 이어 붙이고, 없으면 맨 앞에 새로 넣는다.
    일부 로컬 모델은 system 메시지가 두 개거나 중간에 있으면 거절하기 때문이다.
    """
    instruction = schema_instruction(schema)
    if messages and messages[0].role == "system":
        first = messages[0]
        return [Message("system", f"{first.content}\n\n{instruction}"), *messages[1:]]
    return [Message("system", instruction), *messages]


def _fix_request(detail: str) -> str:
    return f"앞의 답은 정해진 형식에 맞지 않았어요: {detail}\n스키마에 맞는 JSON 객체 하나만 다시 보내 주세요."


async def complete_json(
    client: LLMClient,
    messages: Sequence[Message],
    schema: type[T],
    *,
    max_attempts: int = LLM_MAX_FORMAT_ATTEMPTS,
    deadline_seconds: float = DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS,
) -> StructuredReply[T]:
    """AI를 불러 schema 모양의 결과를 받는다. 형식이 틀리면 max_attempts번까지 다시 요청한다.

    재시도까지 합친 전체 시간이 deadline_seconds를 넘으면 LLMUnavailable.
    어떤 오류로 끝나든 그때까지 쓴 사용량이 오류의 usage에 붙는다.
    """
    if not messages:
        raise ValueError("messages가 비어 있어요.")
    if max_attempts < 1:
        raise ValueError("max_attempts는 1 이상이어야 해요.")
    if not deadline_seconds > 0:
        raise ValueError("deadline_seconds는 0보다 커야 해요.")

    progress = _Progress(usage=LLMUsage())
    deadline = asyncio.timeout(deadline_seconds)
    try:
        async with deadline:
            return await _complete_with_retries(client, messages, schema, max_attempts, progress)
    except TimeoutError:
        if not deadline.expired():  # 우리 마감이 아닌 다른 TimeoutError는 그대로 올린다
            raise
        logger.warning("LLM 전체 시간 상한(%.0f초) 초과, 스키마 %s", deadline_seconds, schema.__name__)
        raise LLMUnavailable(
            f"AI 응답이 전체 시간 상한({deadline_seconds:.0f}초)을 넘었어요.",
            # 끝나지 않은 chat()이 연결 재시도를 몇 번 했는지 여기선 알 수 없다.
            # 적게 세지 않도록 최대치(LLM_MAX_TRANSIENT_ATTEMPTS)로 센다(2차 리뷰 S1).
            usage=progress.usage + LLMUsage(calls=LLM_MAX_TRANSIENT_ATTEMPTS),
        ) from None


async def _complete_with_retries(
    client: LLMClient,
    messages: Sequence[Message],
    schema: type[T],
    max_attempts: int,
    progress: _Progress,
) -> StructuredReply[T]:
    conversation = _with_schema_instruction(messages, schema)
    last_problem: _FormatProblem | None = None
    last_content = ""

    for attempt in range(1, max_attempts + 1):
        try:
            reply = await client.chat(conversation)
        except LLMError as exc:
            exc.usage = progress.usage + exc.usage  # 앞선 형식 시도의 사용량까지 붙여 올린다
            raise
        progress.usage = progress.usage + reply.usage

        try:
            value = _check_reply(reply.content, schema)
        except _FormatProblem as problem:
            if reply.finish_reason == "length":
                problem = _FormatProblem(f"답이 길이 제한에서 잘렸어요. {problem.detail}", f"truncated, {problem.kinds}")
            logger.warning(
                "LLM 답 형식 오류(%s: %s), 시도 %d/%d", schema.__name__, problem.kinds, attempt, max_attempts
            )
            last_problem, last_content = problem, reply.content
            # 다음 요청에는 틀린 답과 무엇이 틀렸는지를 붙여서 고쳐 달라고 한다.
            # 빈 답 · 너무 긴 답은 assistant 메시지로 되돌려 보내지 않는다.
            echo = [Message("assistant", reply.content)] if 0 < len(reply.content) <= MAX_REPLY_CHARS else []
            conversation = [*conversation, *echo, Message("user", _fix_request(problem.detail))]
            continue
        return StructuredReply(value=value, reply=reply, attempts=attempt, usage=progress.usage)

    kinds = last_problem.kinds if last_problem else ""
    logger.warning("LLM 답 형식 오류로 포기(%s: %s)", schema.__name__, kinds)
    raise LLMInvalidOutput(
        f"AI 답이 정해진 형식({schema.__name__})에 맞지 않아요({max_attempts}번 시도, 오류 종류: {kinds}).",
        attempts=max_attempts,
        raw_content=last_content,
        detail=last_problem.detail if last_problem else "",
        usage=progress.usage,
    )
