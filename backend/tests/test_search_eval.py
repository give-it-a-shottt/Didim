"""검색 평가 채점 규칙 테스트 (F-003 완료 기준 5).

평가 스크립트(scripts/search_eval.py)는 개발 DB의 내 기록을 쓰므로 pytest에 넣지 않는다.
대신 채점 규칙(app/search/evaluation.py)을 여기서 고정한다.
"""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.search import KeywordSearcher, SearchHit, SearchQuery
from app.search.evaluation import EvalSetError, ExpectedChunk, evaluate, parse_eval_set
from app.services.auth_service import GoogleProfile, get_or_create_google_user
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user

EXAMPLE_SET = Path(__file__).resolve().parent.parent / "eval" / "search_eval.example.json"


def _hit(chunk_id: int, title: str, heading: str) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id, note_id=1, note_title=title, heading_path=heading, start_offset=0, end_offset=1,
        content="x", score=1.0,
    )


class _FixedSearcher:
    method = "fixed"

    def __init__(self, answers: dict[str, list[SearchHit]]) -> None:
        self.answers = answers

    def search(self, db: Session, *, user_id: int, query: SearchQuery, limit: int) -> list[SearchHit]:
        return self.answers.get(query.text, [])[:limit]


def test_example_set_in_repo_is_valid() -> None:
    items = parse_eval_set(json.loads(EXAMPLE_SET.read_text(encoding="utf-8")))
    assert len(items) == 3
    assert items[2].expected == (ExpectedChunk(note_title="데이터베이스", heading_path=None),)
    assert items[1].tag == "다른낱말"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "최상위는"),
        ({"items": []}, "최상위는"),
        ({"items": [{"query": " ", "expected": [{"note_title": "a"}]}]}, "1번째 질문 query"),
        ({"items": [{"query": "q", "expected": []}]}, "1번째 질문 expected"),
        ({"items": [{"query": "q", "expected": [{"heading_path": "# a"}]}]}, "1번째 질문 note_title"),
        ({"items": [{"query": "q", "expected": [{"note_title": "a"}], "tag": 3}]}, "1번째 질문 tag"),
    ],
)
def test_broken_eval_set_says_which_question_is_wrong(data: object, message: str) -> None:
    with pytest.raises(EvalSetError, match=message):
        parse_eval_set(data)


def test_hit_rate_counts_questions_with_an_expected_chunk_in_top_k_and_splits_by_tag() -> None:
    items = parse_eval_set(
        {
            "items": [
                {"query": "q1", "expected": [{"note_title": "A", "heading_path": "# A > ## x"}]},
                {"query": "q2", "expected": [{"note_title": "B"}], "tag": "다른낱말"},
                {"query": "q3", "expected": [{"note_title": "C"}], "tag": "다른낱말"},
            ]
        }
    )
    searcher = _FixedSearcher(
        {
            "q1": [_hit(1, "A", "# A > ## y"), _hit(2, "A", "# A > ## x")],  # 2위에 정답(제목 경로까지 일치)
            "q2": [_hit(3, "B", "# B > ## 아무거나")],  # 제목 경로를 비운 정답 → 노트만 맞으면 됨
            "q3": [_hit(4, "A", "# A > ## x")],  # 오답
        }
    )

    report = evaluate(None, searcher, user_id=1, items=items, k=5)  # type: ignore[arg-type]

    assert [item.hit_rank for item in report.items] == [2, 1, None]
    assert (report.hits, round(report.hit_rate, 2)) == (2, 0.67)
    assert report.by_tag == {"다른낱말": (1, 2)}
    assert report.method == "fixed"
    assert report.items[2].top == [{"note_title": "A", "heading_path": "# A > ## x", "score": 1.0}]


def test_expected_chunk_outside_top_k_does_not_count() -> None:
    items = parse_eval_set({"items": [{"query": "q", "expected": [{"note_title": "Z"}]}]})
    searcher = _FixedSearcher({"q": [_hit(index, "A", "") for index in range(5)] + [_hit(9, "Z", "")]})

    assert evaluate(None, searcher, user_id=1, items=items, k=5).hits == 0  # type: ignore[arg-type]


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL", "").strip(), reason="키워드 검색(pg_trgm)은 PostgreSQL에서만")
def test_keyword_search_baseline_on_a_tiny_set(db_session: Session) -> None:
    """실제 키워드 검색으로 채점이 끝까지 도는지. '다른낱말' 질문은 키워드 검색이 놓치는 것이 정상(D-016 비교 대상)."""
    user = get_or_create_google_user(db_session, GoogleProfile(sub="s-eval", email="e@example.com", name="E"))
    content = "# React 정리\n\n## useEffect\nuseEffect는 그려진 뒤 부수 효과를 실행해요.\n"
    create_note_for_user(db_session, user_id=user.id, title="React 정리", content=content, chunks=split_markdown(content))
    items = parse_eval_set(
        {
            "items": [
                {"query": "useEffect를 언제 쓰나요", "expected": [{"note_title": "React 정리"}]},
                {"query": "렌더링 이후 작업", "expected": [{"note_title": "React 정리"}], "tag": "다른낱말"},
            ]
        }
    )

    report = evaluate(db_session, KeywordSearcher(), user_id=user.id, items=items)

    assert [item.hit_rank for item in report.items] == [1, None]
    assert report.by_tag == {"다른낱말": (0, 1)}
