// 평가 리포트(SET_02_001, F-010) 응답 모양. 서버 응답은 backend/app/api/report.py.
// 대표 수치의 이름 · 종류와 표시 글자(display · data_items)는 서버(app/services/eval_report.py)가 정해서 보내므로
// 화면은 그대로 그린다 — 수치를 글자로 바꾸는 규칙을 화면에 두지 않는다(README · 랜딩 · 리포트가 같은 글자).

// 지금 서버가 쓰는 값. 서버가 값을 늘려도 화면이 깨지지 않게 다른 문자열도 받는다(`string & {}` — 목록은 자동 완성에 남음)
export type MetricKind = "rate" | "count" | "per";
export type EvalStatus = "ok" | "partial" | "failed";

export type ReportMetric = {
  key: string;
  label: string;
  kind: MetricKind | (string & {});
  value: number | null; // null = 판정 대기(labels_pending > 0) 또는 값 없음
  display: string; // 화면에 그대로 보일 글자 — "75.0%" · "0.58" · "5개" · "판정 대기" · "—"
};

export type ReportEval = {
  key: string;
  title: string;
  status: EvalStatus | (string & {});
  error: string | null;
  model: string | null;
  labels_pending: number;
  metrics: ReportMetric[];
};

export type ReportRun = {
  run_id: string;
  started_at: string | null;
  finished_at: string | null;
  provider: string | null;
  model: string | null;
  commit: string | null;
  // 서버는 원래 칸 data(키 → 개수)도 보내지만 화면은 쓰지 않아 타입 · 검사에 넣지 않는다(쓰지 않는 칸이 틀려도 리포트를 숨기지 않게)
  data_items: ReportDataItem[]; // 데이터 규모를 서버가 정한 이름 · 순서 · 글자로 — 화면은 이것만 그린다
  evals: ReportEval[];
};

export type ReportDataItem = { key: string; label: string; count: number; display: string }; // display — "심은 경험 20개"

/** 데이터 규모 한 줄 — "심은 경험 20개 · 공고 10개". 글자 · 순서는 서버가 준 그대로 잇기만 한다. */
export function dataSizeText(items: ReportDataItem[]): string {
  return items.map((item) => item.display).join(" · ");
}

/** "2026-11-17T16:44:58+09:00" → "2026-11-17". 형식이 다르면 회차 번호를 쓴다. */
export function runDate(run: ReportRun): string {
  const date = run.started_at?.slice(0, 10);
  return date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : run.run_id;
}

// 배열은 객체로 보지 않는다
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringOrNull(value: unknown): boolean {
  return value === null || value === undefined || typeof value === "string";
}

function isReportMetric(value: unknown): value is ReportMetric {
  return (
    isRecord(value) &&
    typeof value.key === "string" &&
    typeof value.label === "string" &&
    typeof value.kind === "string" &&
    (value.value === null || (typeof value.value === "number" && Number.isFinite(value.value))) &&
    typeof value.display === "string"
  );
}

function isReportDataItem(value: unknown): value is ReportDataItem {
  return (
    isRecord(value) &&
    typeof value.key === "string" &&
    typeof value.label === "string" &&
    typeof value.count === "number" &&
    typeof value.display === "string"
  );
}

function isReportEval(value: unknown): value is ReportEval {
  return (
    isRecord(value) &&
    typeof value.key === "string" &&
    typeof value.title === "string" &&
    typeof value.status === "string" &&
    isStringOrNull(value.error) &&
    isStringOrNull(value.model) &&
    typeof value.labels_pending === "number" &&
    Array.isArray(value.metrics) &&
    value.metrics.every(isReportMetric)
  );
}

function isReportRun(value: unknown): value is ReportRun {
  return (
    isRecord(value) &&
    typeof value.run_id === "string" &&
    isStringOrNull(value.started_at) &&
    isStringOrNull(value.finished_at) &&
    isStringOrNull(value.provider) &&
    isStringOrNull(value.model) &&
    isStringOrNull(value.commit) &&
    Array.isArray(value.data_items) &&
    value.data_items.every(isReportDataItem) &&
    Array.isArray(value.evals) &&
    value.evals.every(isReportEval)
  );
}

/**
 * 응답 모양 검사. 화면이 읽는 칸(evals · metrics · data)까지 본다 — 배열인지만 보면 회차 안쪽이 틀린 응답에서
 * run.evals.find 같은 곳이 서버 렌더 중에 터져 화면 전체가 오류가 된다(e2e tests/report-unavailable.spec.ts).
 * 회차 하나라도 틀리면 응답 전체를 '못 읽음'으로 본다(설계 원칙 3, D-030) — 틀린 회차만 건너뛰면 최신 회차가 틀렸을 때
 * 옛 회차가 '최근 회차'처럼 보인다. 백엔드(report.py)는 회차마다 검사해 틀린 회차를 빼므로 버전이 어긋날 때만 갈린다.
 * 위 타입(ReportMetric · ReportEval · ReportRun)을 바꾸면 이 검사도 같이 고친다.
 */
export function isReportRuns(value: unknown): value is { runs: ReportRun[] } {
  return isRecord(value) && Array.isArray(value.runs) && value.runs.every(isReportRun);
}
