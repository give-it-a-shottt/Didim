"""키워드 검색 — PostgreSQL pg_trgm (F-003, D-016).

낱말마다 "조각 안에 이 낱말과 비슷한 구간이 있는가"(word_similarity)를 보고, 비슷한 낱말 점수를 더해 순위를 매긴다.
- 조사가 붙은 낱말도 찾는다: "useEffect를" ↔ "useEffect는" 0.82, "컴포넌트를" ↔ "컴포넌트" 0.67 (2026-11-10 실측).
- 한계: 띄어쓰기가 다르면 못 찾는다("상태관리" ↔ "상태 관리" 0.4), 뜻이 같고 낱말이 다르면 못 찾는다.
  이 한계가 평가 세트로 드러나면 임베딩을 붙여 비교한다(D-016).

쿼리는 세 단계다(F-003 1차 리뷰 A).
1. 후보(MATERIALIZED CTE): `content %> 낱말`(비슷함이 기준 이상)로 GIN 색인을 타서 고르고, 후보마다 낱말별 비슷함을
   한 번만 계산해 담아 둔다. MATERIALIZED는 PostgreSQL이 CTE를 바깥 쿼리로 펼치지 못하게 막는 울타리다.
   (펼치면 계산식이 정렬 키에 다시 복사되고, 노트 조인 때문에 노트마다 색인 검색을 반복하는 계획이 나왔다.
    리뷰가 제안한 서브쿼리 + OFFSET 0은 PostgreSQL 17에서 펼쳐져 울타리가 되지 않았다 — 2026-11-10 EXPLAIN 확인)
2. 순위: 기준을 넘은 낱말의 비슷함만 더해 점수 높은 순으로 limit개(아직 본문 · 제목은 안 붙임).
3. 결과: 고른 limit개에만 조각 본문 · 노트 제목을 붙인다.
흔한 낱말이 거의 모든 조각에 맞으면 1단계가 여전히 클 수 있어, 한 번의 검색은 SEARCH_TIMEOUT_MS에서 멈춘다.
"""

from functools import reduce
from operator import add

from sqlalchemy import Float, Row, Select, Text, and_, case, desc, func, literal, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.config import SEARCH_TIMEOUT_MS, SEARCH_WORD_SIMILARITY_THRESHOLD
from app.db.models import Chunk, Note
from app.search.base import SearchHit, SearchQuery, SearchTimeoutError, SearchUnavailableError

PG_TRGM_REQUIRED_MESSAGE = "키워드 검색은 PostgreSQL(pg_trgm)에서만 돼요."
# PostgreSQL이 statement_timeout으로 쿼리를 멈췄을 때의 오류 코드(query_canceled)
_QUERY_CANCELED_SQLSTATE = "57014"


def _matches(term: str) -> ColumnElement[bool]:
    """조각 본문에 낱말과 충분히 비슷한 구간이 있는가(= term <% content). 색인을 쓰려면 색인 컬럼이 왼쪽에 있어야 한다."""
    return Chunk.content.op("%>", is_comparison=True)(literal(term, Text))


def _build_statement(*, user_id: int, terms: tuple[str, ...], limit: int) -> Select[tuple[object, ...]]:
    similarities = [
        func.word_similarity(literal(term, Text), Chunk.content, type_=Float).label(f"s{index}")
        for index, term in enumerate(terms)
    ]
    candidates = (
        select(Chunk.id.label("chunk_id"), Chunk.note_id, Chunk.position, *similarities)
        .where(Chunk.user_id == user_id, or_(*(_matches(term) for term in terms)))
        .cte("candidates")
        .prefix_with("MATERIALIZED")  # 울타리 — 낱말별 비슷함을 행마다 한 번만, 색인 검색도 한 번만
    )
    threshold = literal(SEARCH_WORD_SIMILARITY_THRESHOLD, Float)
    score = reduce(
        add,
        (
            case((candidates.c[f"s{index}"] >= threshold, candidates.c[f"s{index}"]), else_=literal(0.0, Float))
            for index in range(len(terms))
        ),
    ).label("score")
    ranked = (
        select(candidates.c.chunk_id, score)
        .order_by(desc(score), candidates.c.note_id, candidates.c.position)
        .limit(limit)
        .subquery("ranked")
    )
    return (
        select(
            Chunk.id,
            Chunk.note_id,
            Note.title,
            Chunk.heading_path,
            Chunk.start_offset,
            Chunk.end_offset,
            Chunk.content,
            ranked.c.score,
        )
        .join(ranked, ranked.c.chunk_id == Chunk.id)
        # 노트도 같은 사용자 것인지 한 번 더 건다(조각 · 노트 user_id가 어긋나는 일이 없게, D-004).
        .join(Note, and_(Note.id == Chunk.note_id, Note.user_id == user_id))
        .where(Chunk.user_id == user_id)
        .order_by(desc(ranked.c.score), Chunk.note_id, Chunk.position)
    )


def run_with_search_settings(db: Session, stmt: Select[tuple[object, ...]]) -> list[Row[tuple[object, ...]]]:
    """이번 트랜잭션에만 검색 설정(시간 상한 · 비슷함 기준)을 걸고 실행한다. 시간을 넘기면 SearchTimeoutError.

    set_config(..., true)는 SET LOCAL과 같다: 트랜잭션이 끝나면(로그 저장 commit · rollback) 원래 값으로 돌아간다.
    """
    db.execute(select(func.set_config("statement_timeout", str(SEARCH_TIMEOUT_MS), True)))
    db.execute(
        select(func.set_config("pg_trgm.word_similarity_threshold", str(SEARCH_WORD_SIMILARITY_THRESHOLD), True))
    )
    try:
        return list(db.execute(stmt).all())
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) == _QUERY_CANCELED_SQLSTATE:
            db.rollback()  # 멈춘 트랜잭션은 더 쓸 수 없다
            raise SearchTimeoutError("검색이 시간 상한을 넘었어요.") from exc
        raise


class KeywordSearcher:
    method = "keyword"

    def search(self, db: Session, *, user_id: int, query: SearchQuery, limit: int) -> list[SearchHit]:
        if db.get_bind().dialect.name != "postgresql":
            raise SearchUnavailableError(PG_TRGM_REQUIRED_MESSAGE)
        terms = tuple(query.terms)
        if not terms:
            return []

        rows = run_with_search_settings(db, _build_statement(user_id=user_id, terms=terms, limit=limit))
        return [
            SearchHit(
                chunk_id=row.id,
                note_id=row.note_id,
                note_title=row.title,
                heading_path=row.heading_path,
                start_offset=row.start_offset,
                end_offset=row.end_offset,
                content=row.content,
                score=float(row.score),
            )
            for row in rows
        ]
