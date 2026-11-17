"""근거가 붙은 문장에 인용 밖 사실이 덧붙었는지 규칙으로 의심한다 (D-028, F-008 '확인 필요').

근거 검사(draft_evidence)는 '인용이 카드 칸에 글자 그대로 있나'만 본다. 그래서 진짜 인용을 달고 문장에만 없는
결과를 덧붙이면 통과한다(심은 문장 0/9 · 실제 AI 0/4, 2026-11-15 · 16). 여기 규칙 두 개가 그 빈틈을 의심한다.
AI를 부르지 않는다(원칙 4) — 같은 글이면 언제나 같은 답이라 평가 수치가 재현된다(D-005).

- R1 unknown_token: 문장의 숫자 · 영문 낱말이 근거 카드(제목 · 모든 칸의 원문 인용 · 내 답) 어디에도 없다.
- R3 result_without_record: 근거 카드의 결과(result) 칸이 비어 있는데 문장에 성과 표현(줄였 · 단축 · 해결 …)이 있다.

인용 밖(같은 카드의 다른 칸)의 숫자는 의심하지 않는다 — 진짜 문장도 상황 · 행동 칸을 섞어 써서 잘못 경고가
너무 많았다(R2, 20/49). 한국어 맥락 바꿈('팀' → '개인 프로젝트')은 규칙으로 잡지 않는다(알려진 한계).
R3 표현 목록은 평가 문장을 보고 만들었다. 목록을 바꾸는 것은 사용자가 정한다(D-028, 7차 리뷰 R4).

평가(draft_evaluation · interview_evaluation)도 숫자 · 영문 낱말을 같은 함수로 뽑는다.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#]+")  # 두 글자 이상(C# · N+1 포함)

# 성과 · 결과를 말하는 표현(R3). 결과 칸이 빈 카드에 이 말이 붙으면 기록에 없는 성과를 덧붙였을 수 있다.
# '방지했' · '개선했'은 뺐다 — 행동을 설명할 때도 써서(예: "동시 요청을 방지했습니다") 잘못 경고가 났다
# (2회차 평가 5/53 중 2개, 사용자 선택 2026-11-17).
RESULT_EXPRESSIONS = re.compile(
    r"줄였|줄어|줄었|줄이는 데 성공|단축|빨라|높였|높아졌|늘었|늘렸|향상|해결(?:했|하였|되)|"
    r"잡았|성공(?:했|하였|적)|없앴|사라졌|절감|감소(?:했|하였|시켰)|증가(?:했|하였|시켰)"
)

CLAIM_UNKNOWN_TOKEN = "unknown_token"  # R1
CLAIM_RESULT_WITHOUT_RECORD = "result_without_record"  # R3
CLAIM_REASONS = (CLAIM_UNKNOWN_TOKEN, CLAIM_RESULT_WITHOUT_RECORD)


def numbers_in(text: str) -> set[str]:
    """글 속 숫자(쉼표는 뺌: 1,200 → 1200)."""
    return {match.replace(",", "") for match in _NUMBER.findall(text)}


def words_in(text: str) -> set[str]:
    """글 속 영문 낱말(두 글자 이상, 소문자로)."""
    return {match.casefold() for match in _LATIN.findall(text)}


@dataclass(frozen=True)
class CardFacts:
    """규칙이 카드에서 보는 것 — 카드마다 한 번만 만들어 그 카드를 근거로 단 문장들이 같이 쓴다(7차 리뷰 R2)."""

    numbers: frozenset[str]
    text: str  # 제목 · 칸 글을 이은 것(소문자)
    result_recorded: bool  # 결과 칸에 원문 인용이나 내 답이 있는가

    @classmethod
    def of(cls, texts: Iterable[str | None], *, result_recorded: bool) -> "CardFacts":
        joined = "\n".join(text for text in texts if text)
        return cls(numbers=frozenset(numbers_in(joined)), text=joined.casefold(), result_recorded=result_recorded)


@dataclass(frozen=True)
class ClaimCheck:
    """문장 하나의 의심 결과. reasons가 비면 의심 없음."""

    reasons: list[str] = field(default_factory=list)  # CLAIM_REASONS 중 걸린 것(순서 고정)
    unknown_tokens: list[str] = field(default_factory=list)  # R1에 걸린 숫자 · 영문 낱말(가나다순)

    @property
    def flagged(self) -> bool:
        return bool(self.reasons)

    @property
    def key(self) -> str:
        """걸린 이유를 한 줄로(예: "unknown_token:40|result_without_record"). [확인함] 때 저장하고, 읽을 때 지금 값과
        비교해 다르면 다시 경고한다 — 카드가 바뀌어 이유가 달라지면 확인이 풀린다(Q-029, 사용자 선택 2026-11-17)."""
        parts = []
        for reason in self.reasons:
            tokens = ",".join(self.unknown_tokens) if reason == CLAIM_UNKNOWN_TOKEN else ""
            parts.append(f"{reason}:{tokens}" if tokens else reason)
        return "|".join(parts)


def check_claims(sentence: str, facts: CardFacts) -> ClaimCheck:
    """근거 카드의 글 · 결과 칸 기록 여부로 문장을 의심한다.

    숫자는 낱개로 정확히 비교한다('3'이 '30' 안에 있다고 통과시키지 않음). 영문은 카드 글 안에 있으면 통과
    (대소문자 무시) — 줄여 쓴 낱말(remark-gf)까지 의심하지 않게(평가 규칙 판정과 같은 기준).
    """
    unknown = sorted(
        [token for token in numbers_in(sentence) if token not in facts.numbers]
        + [token for token in words_in(sentence) if token not in facts.text]
    )
    reasons = []
    if unknown:
        reasons.append(CLAIM_UNKNOWN_TOKEN)
    if not facts.result_recorded and RESULT_EXPRESSIONS.search(sentence):
        reasons.append(CLAIM_RESULT_WITHOUT_RECORD)
    return ClaimCheck(reasons=reasons, unknown_tokens=unknown)
