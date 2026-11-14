"""여러 라우터가 같이 쓰는 요청 · 응답 모델 도우미 (F-008 3차 리뷰 R1 — 라우터끼리 서로 가져다 쓰거나 복사하지 않게, errors.py와 같은 생각).

- ServiceOut: 서비스가 돌려준 dataclass를 속성 이름 그대로 읽는 응답 모델(`model_validate(dataclass)` 한 줄로 옮김).
  필드를 하나 더하면 서비스 dataclass와 응답 모델 두 곳만 고친다(F-007 2차 R1).
- RAW_INPUT_SLACK: 본문 크기 상한. 길이 검사는 공백을 정리한 뒤 서비스에서 하지만, 터무니없이 큰 본문은 서비스까지 가기 전에
  422로 막는다. 정리 전 글(앞뒤 · 안쪽 공백, 빈 줄)이 서비스 상한보다 길 수 있어 이 배수까지 받는다(카드 API와 같은 생각).
"""

from pydantic import BaseModel, ConfigDict

RAW_INPUT_SLACK = 5


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
