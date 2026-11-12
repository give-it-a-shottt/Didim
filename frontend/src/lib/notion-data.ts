import "server-only";

import { fetchBackendAsUser } from "@/lib/backend";
import { readJson } from "@/lib/json";
import { type NotionStatus, toNotionStatus } from "@/lib/notion-status";

// 설정 화면이 처음 그릴 때 필요한 노션 연결 상태(F-005). 서버 데이터라 서버 컴포넌트에서 부른다(D-012).
export async function getNotionStatus(): Promise<NotionStatus | null> {
  const response = await fetchBackendAsUser("/api/notion/status");
  if (response === null || !response.ok) return null;
  return toNotionStatus(await readJson(response));
}
