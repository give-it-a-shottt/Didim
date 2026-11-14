import "server-only";

import { fetchBackendAsUser } from "@/lib/backend";
import { type ApplicationDrafts, toApplicationDrafts } from "@/lib/drafts";
import { readJson } from "@/lib/json";

// 자소서 초안(F-008)을 서버 컴포넌트에서 FastAPI로 부른다. 처음 화면을 그릴 때 필요한 서버 데이터라 서버 컴포넌트(D-012).
// 그 뒤 고치는 동안은 브라우저의 TanStack Query 캐시가 이어받는다(draft-workspace.tsx).

export type DraftsOutcome = { status: "ok"; drafts: ApplicationDrafts } | { status: "not-found" } | { status: "error" };

export async function getDrafts(applicationId: number): Promise<DraftsOutcome> {
  const response = await fetchBackendAsUser(`/api/applications/${applicationId}/drafts`);
  if (response === null) return { status: "error" };
  if (response.status === 404) return { status: "not-found" };
  const drafts = response.ok ? toApplicationDrafts(await readJson(response)) : null;
  return drafts === null ? { status: "error" } : { status: "ok", drafts };
}
