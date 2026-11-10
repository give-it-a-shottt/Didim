"""기록 검색 (F-003, D-016). 기능 코드는 이 패키지에서 가져다 쓴다.

    searcher = get_searcher()                         # 지금은 키워드(pg_trgm). 임베딩은 평가로 비교한 뒤
    hits = searcher.search(db, user_id=..., query=SearchQuery(text, extract_terms(text)), limit=5)
"""

from app.search.base import SearchHit, SearchQuery, Searcher, SearchTimeoutError, SearchUnavailableError
from app.search.keyword import KeywordSearcher
from app.search.query import extract_terms, make_excerpt


def get_searcher() -> Searcher:
    """지금 쓰는 검색 방식. API는 Depends(get_searcher)로 받아서, 방식을 바꿀 때 이 함수만 고친다."""
    return KeywordSearcher()


__all__ = [
    "KeywordSearcher",
    "SearchHit",
    "SearchQuery",
    "SearchTimeoutError",
    "SearchUnavailableError",
    "Searcher",
    "extract_terms",
    "get_searcher",
    "make_excerpt",
]
