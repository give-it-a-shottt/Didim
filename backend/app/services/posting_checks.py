"""공고 분석(F-007)의 검사 결과 이름 — ① 역량 뽑기 · ② 매칭 · 평가 로그가 같이 쓴다."""

# 버린 이유(posting_analysis_logs.drop_reasons의 키). 평가 리포트에서 이유별로 센다.
DROP_QUOTE_TOO_SHORT = "quote_too_short"
DROP_QUOTE_TOO_LONG = "quote_too_long"
DROP_QUOTE_NOT_FOUND = "quote_not_found"  # 인용이 공고 · 카드 칸에 글자 그대로 없음(지어낸 글일 수 있음)
DROP_EMPTY_NAME = "empty_name"  # ①: 역량 이름이 비었음
DROP_DUPLICATE = "duplicate"  # ①: 같은 이름의 역량 / ②: 같은 역량 · 같은 카드
DROP_TOO_MANY = "too_many"  # ①: 공고당 최대 개수 / ②: 역량당 최대 개수를 넘음
DROP_UNKNOWN_REQUIREMENT = "unknown_requirement"  # ②: 보내지 않은 역량 번호
DROP_NOT_CANDIDATE = "card_not_candidate"  # ②: 그 역량에 보낸 후보가 아닌 카드(다른 사용자 카드 포함)
DROP_UNKNOWN_SLOT = "unknown_slot"  # ②: 칸 이름이 틀림
DROP_NO_REASON = "no_reason"  # ②: 맞는 이유가 비었음
DROP_CARD_GONE = "card_gone"  # ②: AI를 부르는 동안 카드가 지워짐

OUTCOME_NONE_FOUND = "none_found"  # 남은 역량 · 매칭이 0개
OUTCOME_NO_CANDIDATES = "no_candidates"  # ②: 키워드 후보 카드가 없어 AI를 부르지 않음

QUOTE_SOURCE_QUOTE = "quote"  # 카드 칸의 원문 인용(내 노트 문장)
QUOTE_SOURCE_ANSWER = "answer"  # 카드 칸의 내 답
