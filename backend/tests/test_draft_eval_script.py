"""자소서 초안 평가 스크립트(scripts/draft_eval.py)의 파일 · 실패 처리 테스트 (F-008 6차 리뷰 R3).

평가 자체(AI · 실제 세트)는 pytest에 넣지 않는다 — 여기서는 결과 파일을 안전하게 쓰는지, 공고 준비 실패를
그 공고만 실패로 남기는지, 다시 채점이 깨진 파일을 알리는지만 본다.
"""

import asyncio
import json
from pathlib import Path

import pytest

from app.services.card_evaluation import ExperienceKey, NoteKey
from app.services.draft_evaluation import QuestionKey
from app.services.eval_retry import RetryPolicy
from app.services.posting_evaluation import PostingKey, RequirementKey
from scripts import draft_eval

POSTING = "자격 요건\n- React 화면 개발 경험"
KEY = PostingKey(requirements=(RequirementKey(quote="React 화면 개발 경험", kind="required", cards=("e1",)),))
NOTE = "# 노트\n\n## 화면 만들기\n상품 목록이 느렸다.\n\nReact.memo로 카드를 감쌌다.\n\n렌더링이 40ms로 줄었다.\n"
QUESTION = QuestionKey(kind="answerable", text="성능을 개선한 경험을 써 주세요.", char_limit=300)


def test_rescore_reports_broken_files(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert draft_eval._rescore(broken) == 1
    bad_label = tmp_path / "bad.json"
    question = {"file": "p01.md", "index": 1, "kind": "trap", "question": "q",
                "sentences": [{"id": "s1", "text": "t", "supported": True, "human": "yes"}]}
    bad_label.write_text(json.dumps({"mode": "ai", "questions": [question]}), encoding="utf-8")
    assert draft_eval._rescore(bad_label) == 1
    assert json.loads(bad_label.read_text(encoding="utf-8"))["questions"][0]["sentences"][0]["human"] == "yes"  # 그대로


def test_failed_posting_setup_marks_only_that_posting_and_goes_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "n.md").write_text(NOTE, encoding="utf-8")
    card_keys = {"n.md": NoteKey(experiences=(ExperienceKey(id="e1", sections=("화면 만들기",)),))}
    plan = [(Path("p01-a.md"), POSTING, KEY, (QUESTION, QUESTION)), (Path("p02-b.md"), POSTING, KEY, (QUESTION,))]
    real = draft_eval.create_eval_application

    def failing_first(db, *, file_name, **kwargs):
        if file_name == "p01-a.md":
            raise ValueError("정답 카드에 원문 인용 칸이 없어요: ['e1']")
        return real(db, file_name=file_name, **kwargs)

    monkeypatch.setattr(draft_eval, "create_eval_application", failing_first)
    saved: list[int] = []
    results = asyncio.run(draft_eval._evaluate_all(
        plan, card_keys, tmp_path, mode=draft_eval.MODE_PLANTED, client=None, policy=RetryPolicy(),
        on_result=lambda items: saved.append(len(items)),
    ))
    assert [(result.file_name, result.error) for result in results] == [
        ("p01-a.md", "ValueError"), ("p01-a.md", "ValueError"), ("p02-b.md", None),
    ]
    assert results[0].error_detail == "정답 카드에 원문 인용 칸이 없어요: ['e1']"
    assert results[2].sentences and saved == [2, 3]  # 실패한 공고도 결과 파일에 바로 남김


def test_summary_lines_say_when_claim_checks_were_not_computed(capsys: pytest.CaptureFixture[str]) -> None:
    """옛 결과 파일을 다시 채점하면 '확인 필요까지' 줄 대신 계산하지 않았다는 안내가 나온다(8차 리뷰 R3)."""
    old = draft_eval.result_from_dict(
        {
            "file": "p01-backend.md", "index": 1, "kind": "answerable", "question": "문항", "char_limit": 500,
            "sentences": [{"id": "p01-q1-s1", "text": "빌드를 단축했습니다.", "supported": True, "human": True}],
        }
    )
    draft_eval._print_summary("nvidia", draft_eval.summarize([old]), [])
    draft_eval._print_planted_summary(draft_eval.summarize_planted([old]))
    out = capsys.readouterr().out
    assert out.count(draft_eval.NOT_CHECKED_LINE) == 2
    assert "'확인 필요'까지(D-028): 잡음" not in out
