"""검색어 다루기: 낱말 뽑기 · 결과 발췌 만들기 (F-003). DB를 쓰지 않는 순수 함수만 둔다."""

import re
from collections.abc import Sequence

from app.config import (
    MAX_SEARCH_TERMS,
    MIN_SEARCH_TERM_CHARS,
    SEARCH_EXCERPT_CHARS,
    SEARCH_EXCERPT_LEAD_CHARS,
)

# 글자 · 숫자 · 밑줄이 이어진 덩어리를 낱말로 본다(한글 포함). 한계: "C++" · "C#"처럼 기호가 붙은 이름은 기호가 빠진다.
_TERM_PATTERN = re.compile(r"\w+")
# 발췌에서 낱말을 찾을 때 끝에서 떼어 볼 글자 수. 조사("를" · "에서")나 복수형("s")이 붙은 낱말도 원문에서 찾기 위해서다.
_MAX_TRAILING_TRIM = 2


def extract_terms(text: str) -> tuple[str, ...]:
    """검색어에서 낱말을 뽑는다. 너무 짧은 낱말은 버리고, 대소문자만 다른 같은 낱말은 하나로, 최대 MAX_SEARCH_TERMS개."""
    terms: list[str] = []
    seen: set[str] = set()
    for match in _TERM_PATTERN.finditer(text):
        term = match.group()
        key = term.casefold()
        if len(term) < MIN_SEARCH_TERM_CHARS or key in seen:
            continue
        seen.add(key)
        terms.append(term)
        if len(terms) == MAX_SEARCH_TERMS:
            break
    return tuple(terms)


def _term_forms(term: str) -> list[str]:
    """낱말 그대로, 그다음 끝 글자를 1 · 2개 뗀 모양. 남는 길이가 최소 글자 수보다 짧아지면 멈춘다."""
    forms = [term]
    for trim in range(1, _MAX_TRAILING_TRIM + 1):
        shorter = term[:-trim]
        if len(shorter) < MIN_SEARCH_TERM_CHARS:
            break
        forms.append(shorter)
    return forms


def make_excerpt(content: str, terms: Sequence[str]) -> tuple[str, list[str]]:
    """조각에서 결과 줄에 보여 줄 발췌와, 원문에 실제로 들어 있던 낱말 모양을 돌려준다.

    가장 먼저 나오는 낱말 앞쪽부터 SEARCH_EXCERPT_CHARS 글자를 자르고, 줄바꿈 · 연속 공백은 한 칸으로 줄인다.
    화면은 돌려준 낱말을 문자열로 찾아 표시한다(글자 위치를 주고받지 않아 파이썬 · 자바스크립트 글자 단위 차이가 없음).
    """
    matched: list[str] = []
    first_position: int | None = None
    for term in terms:
        for form in _term_forms(term):
            found = re.search(re.escape(form), content, flags=re.IGNORECASE)
            if found:
                matched.append(found.group())
                if first_position is None or found.start() < first_position:
                    first_position = found.start()
                break

    start = 0 if first_position is None else max(0, first_position - SEARCH_EXCERPT_LEAD_CHARS)
    end = min(len(content), start + SEARCH_EXCERPT_CHARS)
    start = max(0, end - SEARCH_EXCERPT_CHARS)  # 끝에 가까우면 앞을 더 보여 준다

    excerpt = " ".join(content[start:end].split())
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(content):
        excerpt = excerpt + "…"
    return excerpt, matched
