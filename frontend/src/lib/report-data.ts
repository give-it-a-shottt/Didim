import "server-only";

import { fetchBackendPublic } from "@/lib/backend";
import { isReportRuns, type ReportRun } from "@/lib/report";

/** 평가 회차를 새 회차부터 읽는다(로그인 없이). 서버에 닿지 못하면 null — 화면은 '불러오지 못함'으로 보인다. */
export async function getReportRuns(): Promise<ReportRun[] | null> {
  const response = await fetchBackendPublic("/api/report");
  if (!response?.ok) return null;
  try {
    const data: unknown = await response.json();
    return isReportRuns(data) ? data.runs : null;
  } catch {
    return null;
  }
}
