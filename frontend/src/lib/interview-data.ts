import "server-only";

import { fetchBackendAsUser } from "@/lib/backend";
import { type ApplicationInterview, toApplicationInterview } from "@/lib/interview";
import { readJson } from "@/lib/json";

// 지원 상세 [면접 연습] 탭(F-009)을 서버 컴포넌트에서 FastAPI로 부른다. 처음 화면을 그릴 때 필요한 서버 데이터라
// 서버 컴포넌트(D-012). 메모를 고치는 동안은 화면(interview-workspace.tsx)이 응답으로 바꿔 끼운다.

export type InterviewOutcome = { status: "ok"; interview: ApplicationInterview } | { status: "not-found" } | { status: "error" };

export async function getApplicationInterview(applicationId: number): Promise<InterviewOutcome> {
  const response = await fetchBackendAsUser(`/api/applications/${applicationId}/interview`);
  if (response === null) return { status: "error" };
  if (response.status === 404) return { status: "not-found" };
  const interview = response.ok ? toApplicationInterview(await readJson(response)) : null;
  return interview === null ? { status: "error" } : { status: "ok", interview };
}
