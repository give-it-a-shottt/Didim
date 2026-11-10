"""기록 검색 API (F-003).

GET /api/search?q=…&limit=5 — 내 기록 조각을 최대 5개 찾는다. 검색어를 주소에 담는 방식(GET)은 화면이 서버 컴포넌트로
결과를 그리게 하려고 골랐다(검색어가 접속 기록에 남을 수 있음을 알고 고름, 사용자 확인).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import MAX_SEARCH_QUERY_CHARS, MAX_SEARCH_RESULTS
from app.db.models import User
from app.db.session import get_db
from app.search import Searcher, SearchTimeoutError, SearchUnavailableError, get_searcher
from app.services.search_service import search_records

router = APIRouter(prefix="/search", tags=["search"])

EMPTY_QUERY_DETAIL = "검색어를 입력해 주세요."
UNAVAILABLE_DETAIL = "지금은 기록 검색을 쓸 수 없어요."
TIMEOUT_DETAIL = "검색이 오래 걸려 멈췄어요. 낱말을 줄이거나 더 구체적인 낱말로 찾아보세요."


class SearchResultOut(BaseModel):
    chunk_id: int
    note_id: int
    note_title: str
    heading_path: str
    start_offset: int
    end_offset: int
    excerpt: str
    matched_terms: list[str]
    score: float


class SearchResponse(BaseModel):
    query: str
    terms: list[str]
    method: str
    results: list[SearchResultOut]


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(min_length=1, max_length=MAX_SEARCH_QUERY_CHARS),
    limit: int = Query(default=MAX_SEARCH_RESULTS, ge=1, le=MAX_SEARCH_RESULTS),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    searcher: Searcher = Depends(get_searcher),
) -> SearchResponse:
    """400: 검색어가 공백뿐 / 401: 로그인 안 함 / 422: 검색어가 너무 김 · limit 범위 밖
    503: 이 DB에서 검색 불가 · 검색이 시간 상한(3초)을 넘음 — 화면은 detail 문구를 그대로 보여 준다."""
    if not q.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=EMPTY_QUERY_DETAIL)
    try:
        outcome = search_records(db, searcher, user_id=current_user.id, text=q, limit=limit)
    except SearchUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=UNAVAILABLE_DETAIL) from exc
    except SearchTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=TIMEOUT_DETAIL) from exc

    return SearchResponse(
        query=outcome.query,
        terms=list(outcome.terms),
        method=outcome.method,
        results=[
            SearchResultOut(
                chunk_id=item.hit.chunk_id,
                note_id=item.hit.note_id,
                note_title=item.hit.note_title,
                heading_path=item.hit.heading_path,
                start_offset=item.hit.start_offset,
                end_offset=item.hit.end_offset,
                excerpt=item.excerpt,
                matched_terms=item.matched_terms,
                score=item.hit.score,
            )
            for item in outcome.results
        ],
    )
