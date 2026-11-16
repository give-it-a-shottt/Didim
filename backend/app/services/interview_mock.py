"""면접 질문(F-009)의 가짜 AI 답 — 키 없이 화면 흐름을 확인할 때(LLM_PROVIDER=mock). 품질은 보지 않는다.

F-008 draft_mock.py처럼 운영 코드(interview_writing.py)와 따로 둔다.
"""

import json
from collections.abc import Sequence

from app.config import INTERVIEW_MAX_QUESTIONS, INTERVIEW_MIN_QUOTE_CHARS
from app.llm.base import Message
from app.services.text_clean import visible_chars

_SLOT_QUESTIONS = {
    "situation": "그 상황에서 가장 먼저 문제라고 느낀 점은 무엇이었나요?",
    "task": "그 일을 맡았을 때 스스로 정한 목표는 무엇이었나요?",
    "action": "그렇게 하기로 한 이유와, 고려했던 다른 방법은 무엇이었나요?",
    "result": "그 결과를 어떻게 확인했고, 다시 한다면 무엇을 바꾸겠나요?",
}


def mock_interview_responder(messages: Sequence[Message]) -> str:
    """칸마다 고정 질문 하나 + 그 칸 글 앞부분을 인용으로(최대 INTERVIEW_MAX_QUESTIONS개)."""
    user_messages = [message for message in messages if message.role == "user"]
    try:
        payload = json.loads(user_messages[0].content) if user_messages else {}
    except json.JSONDecodeError:
        payload = {}
    questions: list[dict[str, str]] = []
    for item in payload.get("fields", []) if isinstance(payload, dict) else []:
        slot = str(item.get("slot", ""))
        text = str(item.get("quote") or item.get("answer") or "").split("\n")[0][:60].strip()
        if slot in _SLOT_QUESTIONS and visible_chars(text) >= INTERVIEW_MIN_QUOTE_CHARS:
            questions.append({"slot": slot, "question": f"(mock) {_SLOT_QUESTIONS[slot]}", "quote": text})
    return json.dumps({"questions": questions[:INTERVIEW_MAX_QUESTIONS]}, ensure_ascii=False)
