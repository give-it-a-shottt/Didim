"""사용자 입력 · AI 출력의 제어 문자 다루기 (F-006 1차 리뷰 R2).

PostgreSQL text · varchar는 NUL(0x00)을 받지 않아 저장(commit) 때 오류가 난다 — 그대로 두면 422가 아니라 500이 된다.
줄바꿈 · 탭 · 캐리지 리턴은 글에 흔히 쓰므로 허용하고, 나머지 제어 문자(유니코드 분류 Cc)는 막거나 지운다.
"""

import unicodedata

_ALLOWED_CONTROLS = frozenset("\n\r\t")


def _is_forbidden(char: str) -> bool:
    return char not in _ALLOWED_CONTROLS and unicodedata.category(char) == "Cc"


def has_forbidden_control(text: str) -> bool:
    """사용자 입력 검사용 — 있으면 422로 돌려준다(조용히 고치지 않고 알린다)."""
    return any(_is_forbidden(char) for char in text)


def strip_forbidden_control(text: str) -> str:
    """AI 출력 정리용 — 사용자가 고칠 수 없는 글이라 지우고 저장한다."""
    return "".join(char for char in text if not _is_forbidden(char))


def visible_chars(text: str) -> int:
    """공백을 뺀 글자 수 — 인용 길이 하한(낱말 하나로 근거 검사를 통과하지 않게)에 쓴다. 퀴즈 · 카드 · 공고 분석 공용."""
    return sum(1 for char in text if not char.isspace())


def clean_one_line(text: str) -> str:
    """AI가 쓴 한 줄 글(이름 · 이유) 정리: 제어 문자를 지우고 공백을 하나로 모은다."""
    return " ".join(strip_forbidden_control(text).split())


def cut_text(text: str, max_chars: int) -> str:
    """max_chars를 넘으면 잘라 끝에 '…'를 붙인다(전체 길이 max_chars)."""
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
