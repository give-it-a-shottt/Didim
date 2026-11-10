"""기록 검색의 공통 약속 (F-003, D-016).

검색 방식(지금은 키워드, 나중에 임베딩 · 섞기)은 모두 `Searcher` 모양을 따른다. 기능 코드는 방식을 몰라도 되고,
방식을 바꿀 때는 app/search/__init__.py의 get_searcher만 바꾼다(LLM 교체 구조 D-014와 같은 생각).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session


class SearchUnavailableError(RuntimeError):
    """이 DB에서는 이 검색 방식을 쓸 수 없을 때. 예) 키워드 검색은 PostgreSQL pg_trgm이 필요해서 SQLite에서는 못 쓴다."""


class SearchTimeoutError(RuntimeError):
    """검색 한 번이 시간 상한(SEARCH_TIMEOUT_MS)을 넘어 멈췄을 때. 세션은 이미 rollback된 상태다."""


@dataclass(frozen=True)
class SearchQuery:
    """사용자가 넣은 검색어와, 거기서 뽑은 낱말들. 키워드 방식은 낱말을, 임베딩 방식은 원문을 쓴다."""

    text: str
    terms: Sequence[str]


@dataclass(frozen=True)
class SearchHit:
    """검색 결과 조각 하나. 위치(start · end)는 노트 원문의 파이썬 글자 위치다(Chunk와 같음)."""

    chunk_id: int
    note_id: int
    note_title: str
    heading_path: str
    start_offset: int
    end_offset: int
    content: str
    score: float


class Searcher(Protocol):
    # 검색 로그에 남는 방식 이름. 방식별 평가 점수를 비교할 때 쓴다(D-016).
    method: str

    def search(self, db: Session, *, user_id: int, query: SearchQuery, limit: int) -> list[SearchHit]:
        """user_id의 조각만 찾아 점수 높은 순서로 limit개까지 돌려준다(D-004)."""
        ...
