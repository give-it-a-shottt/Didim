"""검색 평가 (F-003 완료 기준 5, D-005 · D-016).

평가 세트 = 질문과 정답 조각 목록. 정답은 조각 ID가 아니라 "노트 제목 + 제목 경로"로 적는다
(같은 노트를 지웠다 다시 올리면 조각 ID가 바뀌기 때문). 제목 경로를 비우면 그 노트의 어느 조각이든 정답.
점수 = 상위 k개 안에 정답 조각이 하나라도 있는 질문의 비율(hit rate@k). 목표 숫자 없이 기록만 한다(사용자 확인).
질문에 tag(예: "다른낱말" — 뜻은 같고 낱말은 다른 질문)를 달면 tag별 비율도 따로 낸다 → 임베딩 비교의 근거(D-016).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import MAX_SEARCH_RESULTS, MAX_SEARCH_RESULTS_PER_NOTE, SEARCH_SCORE_DIGITS
from app.search.base import SearchHit, SearchQuery, Searcher
from app.search.query import extract_terms


class EvalSetError(ValueError):
    """평가 세트 파일 모양이 틀렸을 때. 몇 번째 질문이 왜 틀렸는지 알려 준다."""


@dataclass(frozen=True)
class ExpectedChunk:
    note_title: str
    heading_path: str | None = None


@dataclass(frozen=True)
class EvalItem:
    query: str
    expected: tuple[ExpectedChunk, ...]
    tag: str = ""


@dataclass(frozen=True)
class ItemResult:
    query: str
    tag: str
    hit_rank: int | None  # 1부터. 상위 k개 안에 정답이 없으면 None
    top: list[dict[str, object]]  # 돌려받은 결과(노트 제목 · 제목 경로 · 점수), 틀린 질문을 들여다볼 때 씀


@dataclass(frozen=True)
class EvalReport:
    method: str
    k: int
    items: list[ItemResult]
    by_tag: dict[str, tuple[int, int]] = field(default_factory=dict)  # tag → (맞힘, 전체)

    @property
    def hits(self) -> int:
        return sum(1 for item in self.items if item.hit_rank is not None)

    @property
    def hit_rate(self) -> float:
        return self.hits / len(self.items) if self.items else 0.0


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvalSetError(f"{where}: 비어 있지 않은 글자여야 해요.")
    return value.strip()


def parse_eval_set(data: object) -> list[EvalItem]:
    """JSON에서 읽은 값을 평가 세트로 바꾼다. 모양: {"items": [{"query", "expected": [{"note_title", "heading_path"?}], "tag"?}]}"""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not data["items"]:
        raise EvalSetError('최상위는 {"items": [...]} 이고 질문이 1개 이상이어야 해요.')
    items: list[EvalItem] = []
    for index, raw in enumerate(data["items"], start=1):
        where = f"{index}번째 질문"
        if not isinstance(raw, dict):
            raise EvalSetError(f"{where}: 객체여야 해요.")
        query = _text(raw.get("query"), f"{where} query")
        raw_expected = raw.get("expected")
        if not isinstance(raw_expected, list) or not raw_expected:
            raise EvalSetError(f"{where} expected: 정답이 1개 이상 있어야 해요.")
        expected = []
        for answer in raw_expected:
            if not isinstance(answer, dict):
                raise EvalSetError(f"{where} expected: 정답은 객체여야 해요.")
            heading = answer.get("heading_path")
            expected.append(
                ExpectedChunk(
                    note_title=_text(answer.get("note_title"), f"{where} note_title"),
                    heading_path=None if heading in (None, "") else _text(heading, f"{where} heading_path"),
                )
            )
        tag = raw.get("tag", "")
        if not isinstance(tag, str):
            raise EvalSetError(f"{where} tag: 글자여야 해요.")
        items.append(EvalItem(query=query, expected=tuple(expected), tag=tag.strip()))
    return items


def is_expected(hit: SearchHit, expected: Sequence[ExpectedChunk]) -> bool:
    return any(
        hit.note_title == answer.note_title and (answer.heading_path is None or hit.heading_path == answer.heading_path)
        for answer in expected
    )


def evaluate(
    db: Session, searcher: Searcher, *, user_id: int, items: Sequence[EvalItem], k: int = MAX_SEARCH_RESULTS
) -> EvalReport:
    """질문마다 user_id의 기록을 검색해 상위 k개 안에 정답이 있는지 본다. 검색 로그(search_logs)는 남기지 않는다."""
    results: list[ItemResult] = []
    by_tag: dict[str, tuple[int, int]] = {}
    for item in items:
        hits = searcher.search(
            db, user_id=user_id, query=SearchQuery(item.query, extract_terms(item.query)), limit=k,
            max_per_note=MAX_SEARCH_RESULTS_PER_NOTE,  # 화면과 같은 규칙으로 잰다
        )
        rank = next((position for position, hit in enumerate(hits, start=1) if is_expected(hit, item.expected)), None)
        results.append(
            ItemResult(
                query=item.query,
                tag=item.tag,
                hit_rank=rank,
                top=[
                    {"note_title": hit.note_title, "heading_path": hit.heading_path, "score": round(hit.score, SEARCH_SCORE_DIGITS)}
                    for hit in hits
                ],
            )
        )
        if item.tag:
            got, total = by_tag.get(item.tag, (0, 0))
            by_tag[item.tag] = (got + (rank is not None), total + 1)
    return EvalReport(method=searcher.method, k=k, items=results, by_tag=by_tag)
