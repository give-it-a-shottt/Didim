"""자소서 초안(F-008)의 가짜 AI 답 — 키 없이 화면 흐름을 확인할 때(LLM_PROVIDER=mock). 품질은 보지 않는다.

F-007 posting_mock.py처럼 운영 코드(draft_writing.py)와 따로 둔다(F-008 1차 리뷰 R1).
"""

import json
from collections.abc import Sequence

from app.config import DRAFT_MIN_QUOTE_CHARS
from app.llm.base import Message
from app.services.text_clean import visible_chars


def mock_draft_responder(messages: Sequence[Message]) -> str:
    """가짜 답(LLM_PROVIDER=mock) — 키 없이 화면 흐름을 확인할 때. 품질은 보지 않는다.

    카드마다 첫 칸 글로 근거 달린 문장 하나, 끝에 근거 없는 다짐 문장 하나(화면의 '근거 없음' 경고를 보려고).
    """
    user_messages = [message for message in messages if message.role == "user"]
    try:
        payload = json.loads(user_messages[0].content) if user_messages else {}
    except json.JSONDecodeError:
        payload = {}
    sentences: list[dict[str, object]] = []
    for card in payload.get("cards", []) if isinstance(payload, dict) else []:
        for field_item in card.get("fields", []):
            text = str(field_item.get("quote") or field_item.get("answer") or "")[:60].strip()
            if visible_chars(text) >= DRAFT_MIN_QUOTE_CHARS:
                sentences.append(
                    {
                        "text": f"{card.get('title', '')} 경험에서 {text}",
                        "card_id": card.get("card_id"),
                        "slot": field_item.get("slot"),
                        "quote": text,
                    }
                )
                break
    sentences.append({"text": "(mock) 이 경험을 살려 팀에 기여하겠습니다.", "card_id": None, "slot": None, "quote": None})
    return json.dumps({"sentences": sentences}, ensure_ascii=False)
