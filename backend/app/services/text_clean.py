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
