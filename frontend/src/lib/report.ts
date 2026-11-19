// 평가 리포트(SET_02_001, F-010) 응답 모양과 표시 규칙. 서버 응답은 backend/app/api/report.py.
// 대표 수치의 이름 · 종류는 서버(app/services/eval_report.py)가 정해서 보내므로 화면은 그대로 그린다.

export type ReportMetric = {
  key: string;
  label: string;
  kind: "rate" | "count" | "per" | string;
  value: number | null; // null = 판정 대기(labels_pending > 0) 또는 값 없음
};

export type ReportEval = {
  key: string;
  title: string;
  status: "ok" | "partial" | "failed" | string;
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
  data: Record<string, number>;
  evals: ReportEval[];
};

// 데이터 규모 칸 이름(backend/scripts/eval_all.py data_sizes). README 표도 같은 목록을 쓴다(backend/app/services/eval_report.py
// DATA_LABELS) — 이름 · 순서를 바꾸면 두 곳을 같이 고친다. formatMetric도 eval_report.format_value와 같은 규칙.
const DATA_LABELS: Record<string, string> = {
  quiz_notes: "퀴즈 노트",
  card_notes: "경험 노트",
  experiences: "심은 경험",
  postings: "공고",
  requirements: "요구 역량",
  draft_questions: "자소서 문항",
};

export function dataSizeItems(data: Record<string, number>): string[] {
  return Object.entries(DATA_LABELS)
    .filter(([key]) => typeof data[key] === "number")
    .map(([key, label]) => `${label} ${data[key]}개`);
}

/** 수치 한 칸을 글자로. 값이 없으면 판정 대기인지 그냥 없는지 구분한다. */
export function formatMetric(metric: ReportMetric, labelsPending: number): string {
  if (metric.value === null) return labelsPending > 0 ? "판정 대기" : "—";
  if (metric.kind === "rate") return `${(metric.value * 100).toFixed(1)}%`;
  if (metric.kind === "per") return metric.value.toFixed(2);
  return `${metric.value}개`;
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
    (value.value === null || (typeof value.value === "number" && Number.isFinite(value.value)))
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
    isRecord(value.data) &&
    Object.values(value.data).every((size) => typeof size === "number") &&
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
