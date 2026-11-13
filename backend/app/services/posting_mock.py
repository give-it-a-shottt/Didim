"""공고 분석(F-007)의 가짜 AI 답 — 키 없이 화면 흐름을 확인할 때(LLM_PROVIDER=mock). 품질은 보지 않는다."""

import json
from collections.abc import Sequence

from app.config import MATCH_MIN_QUOTE_CHARS, POSTING_MAX_QUOTE_CHARS, POSTING_MIN_QUOTE_CHARS
from app.llm.base import Message
from app.services.text_clean import visible_chars


def _user_payload(messages: Sequence[Message]) -> dict:  # type: ignore[type-arg]
    user_messages = [message for message in messages if message.role == "user"]
    try:
        payload = json.loads(user_messages[0].content) if user_messages else {}
    except json.JSONDecodeError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def mock_analysis_responder(messages: Sequence[Message]) -> str:
    """① · ② 공통 가짜 답(보낸 내용 모양으로 단계를 가린다). 화면 흐름 확인용이라 품질은 보지 않는다.

    ①: 공고 본문에서 글머리 기호가 붙은 줄을 앞에서부터 5개까지 역량으로(인용은 실제 그 줄).
       이름에 '(mock)'을 붙이지 않는다 — 가짜 카드 제목의 '(mock)'과 키워드가 겹쳐 엉뚱한 카드가 후보가 됐다
       (2026-11-13 화면 확인 때 Kubernetes 역량에 docker 카드). 가짜 표시는 ②의 이유 글에 남긴다.
    ②: 역량마다 첫 후보 카드의 첫 글 앞부분을 인용으로.
    """
    payload = _user_payload(messages)
    if "posting" in payload:
        requirements = []
        for line in str(payload.get("posting", "")).splitlines():
            text = line.strip().lstrip("-•*·").strip()
            if not line.strip().startswith(("-", "•", "*", "·")) or visible_chars(text) < POSTING_MIN_QUOTE_CHARS:
                continue
            text = text[:POSTING_MAX_QUOTE_CHARS].strip()
            requirements.append(
                {"name": text[:15], "kind": "preferred" if "우대" in text else "required", "quote": text}
            )
            if len(requirements) >= 5:
                break
        return json.dumps({"requirements": requirements}, ensure_ascii=False)

    cards = {item.get("card_id"): item for item in payload.get("cards", []) if isinstance(item, dict)}
    matches = []
    for requirement in payload.get("requirements", []):
        for card_id in requirement.get("candidate_card_ids", [])[:1]:
            for field_item in cards.get(card_id, {}).get("fields", []):
                text = str(field_item.get("quote") or field_item.get("answer") or "")[:40].strip()
                if visible_chars(text) >= MATCH_MIN_QUOTE_CHARS:
                    matches.append(
                        {
                            "requirement_id": requirement.get("requirement_id"),
                            "card_id": card_id,
                            "slot": field_item.get("slot"),
                            "quote": text,
                            "reason": "(mock) 이 카드의 글이 역량 키워드와 겹쳐요.",
                        }
                    )
                    break
    return json.dumps({"matches": matches}, ensure_ascii=False)
