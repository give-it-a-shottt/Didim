"""평가 리포트 (F-010 완료 기준 3, D-029) — 로그인 없이 읽는 공개 API.

한 번에 돌리기(scripts/eval_all.py)가 레포에 남긴 회차 요약(eval/summary/run-*.json)을 새 회차부터 돌려준다.
가상 데이터로 잰 수치라 개인 기록이 없다(D-005). DB를 보지 않는다. 결과 파일 경로는 화면에 필요 없어서 빼고 보낸다.
수치마다 표시 글자(display), 회차마다 데이터 칸 이름(data_items)을 같이 보낸다 — 표시 규칙은 eval_report 한 곳이고
화면 · README가 같은 글자를 쓴다(F-010 1 · 2차 리뷰 R1, 사용자 선택 2026-11-19).
"""

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError

from app.config import EVAL_SUMMARY_DIR
from app.services.eval_report import list_summaries, with_display

router = APIRouter(tags=["report"])

MAX_REPORT_RUNS = 10  # 회차 비교는 최근 10회까지


class MetricOut(BaseModel):
    key: str
    label: str
    kind: str  # rate(0~1) · count · per(초안당 등)
    value: float | None  # None = 판정 대기 또는 값 없음
    display: str  # 화면에 그대로 보일 글자 — '75.0%' · '0.58' · '5개' · '판정 대기' · '—'


class EvalOut(BaseModel):
    key: str
    title: str
    status: str  # ok · partial · failed
    error: str | None = None
    model: str | None = None
    labels_pending: int = 0
    metrics: list[MetricOut]


class DataItemOut(BaseModel):
    key: str
    label: str  # '심은 경험' 등 — eval_report.DATA_LABELS
    count: int
    display: str  # 화면 · README에 그대로 보일 글자 — '심은 경험 20개'


class RunOut(BaseModel):
    run_id: str
    started_at: str | None = None
    finished_at: str | None = None
    provider: str | None = None
    model: str | None = None
    commit: str | None = None
    data: dict[str, int]
    data_items: list[DataItemOut]  # data를 정해 둔 이름 · 순서로(화면은 이것만 그린다)
    evals: list[EvalOut]


class ReportOut(BaseModel):
    runs: list[RunOut]


@router.get("/report", response_model=ReportOut)
def read_report() -> ReportOut:
    runs: list[RunOut] = []
    for raw in list_summaries(EVAL_SUMMARY_DIR):
        try:
            runs.append(RunOut.model_validate(with_display(raw)))
        except ValidationError:
            continue  # 모양이 틀린 회차 하나 때문에 리포트 전체가 500이 되지 않게
        if len(runs) == MAX_REPORT_RUNS:
            break
    return ReportOut(runs=runs)
