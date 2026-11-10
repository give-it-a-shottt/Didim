"""기록 검색 서비스 (F-003): 검색 → 발췌 만들기 → 검색 로그 저장."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import SEARCH_SCORE_DIGITS
from app.db.models import SearchLog
from app.search import SearchHit, SearchQuery, Searcher, extract_terms, make_excerpt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResultItem:
    hit: SearchHit
    excerpt: str
    matched_terms: list[str]


@dataclass(frozen=True)
class SearchOutcome:
    query: str
    terms: tuple[str, ...]
    method: str
    results: list[SearchResultItem]


def search_records(db: Session, searcher: Searcher, *, user_id: int, text: str, limit: int) -> SearchOutcome:
    """user_id의 기록 조각을 찾는다. 검색이 끝나면 로그를 남긴다(D-005).

    검색 방식을 못 쓰면 SearchUnavailableError, 시간 상한을 넘으면 SearchTimeoutError(세션은 이미 rollback됨).
    두 경우 모두 로그는 남기지 않는다.
    """
    query_text = text.strip()
    terms = extract_terms(query_text)
    hits = searcher.search(db, user_id=user_id, query=SearchQuery(text=query_text, terms=terms), limit=limit)

    results = []
    for hit in hits:
        excerpt, matched = make_excerpt(hit.content, terms)
        results.append(SearchResultItem(hit=hit, excerpt=excerpt, matched_terms=matched))

    _save_log(db, user_id=user_id, query=query_text, method=searcher.method, hits=hits)
    return SearchOutcome(query=query_text, terms=terms, method=searcher.method, results=results)


def _save_log(db: Session, *, user_id: int, query: str, method: str, hits: Sequence[SearchHit]) -> None:
    """검색 로그를 저장한다. 저장에 실패해도 검색 결과는 돌려준다(로그는 평가용이라 사용자 화면을 막지 않음).

    실패 로그에는 검색어를 쓰지 않는다(개인 기록이 서버 로그에 남지 않게, F-002와 같은 기준).
    """
    db.add(
        SearchLog(
            user_id=user_id,
            query=query,
            method=method,
            results=[{"chunk_id": hit.chunk_id, "score": round(hit.score, SEARCH_SCORE_DIGITS)} for hit in hits],
        )
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("검색 로그 저장 실패 user_id=%s error=%s", user_id, type(exc).__name__)
