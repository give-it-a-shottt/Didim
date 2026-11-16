"""여러 라우터가 같이 쓰는 요청 · 응답 모델 도우미 (F-008 3차 리뷰 R1 — 라우터끼리 서로 가져다 쓰거나 복사하지 않게, errors.py와 같은 생각).

- ServiceOut: 서비스가 돌려준 dataclass를 속성 이름 그대로 읽는 응답 모델(`model_validate(dataclass)` 한 줄로 옮김).
  필드를 하나 더하면 서비스 dataclass와 응답 모델 두 곳만 고친다(F-007 2차 R1).
- InterviewQuestionOut: 면접 질문 하나(F-009) — 카드 상세 응답(api/cards.py)과 면접 API(api/interview.py)가 같이 쓴다.
- RAW_INPUT_SLACK: 본문 크기 상한. 길이 검사는 공백을 정리한 뒤 서비스에서 하지만, 터무니없이 큰 본문은 서비스까지 가기 전에
  422로 막는다. 정리 전 글(앞뒤 · 안쪽 공백, 빈 줄)이 서비스 상한보다 길 수 있어 이 배수까지 받는다(카드 API와 같은 생각).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

RAW_INPUT_SLACK = 5


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InterviewQuestionOut(ServiceOut):
    id: int
    card_id: int
    position: int
    slot: str  # 근거 칸(situation · task · action · result)
    question: str
    quote: str  # 근거 인용(만든 때 그 칸 글에 글자 그대로 있던 글)
    quote_source: str  # quote(카드의 원문 인용) · answer(카드의 내 답)
    evidence_status: str  # ok · changed(카드 칸 글이 바뀌어 인용이 없음) · card_gone
    memo: str | None
    answered_at: datetime | None
    updated_at: datetime
