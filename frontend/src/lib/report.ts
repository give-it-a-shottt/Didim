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

export function isReportRuns(value: unknown): value is { runs: ReportRun[] } {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { runs?: unknown }).runs)
  );
}
