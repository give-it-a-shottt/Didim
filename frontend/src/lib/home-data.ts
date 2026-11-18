import "server-only";

import { fetchBackendAsUser } from "@/lib/backend";
import { type Home, toHome } from "@/lib/home";
import { readJson } from "@/lib/json";

// 홈(F-012)을 서버 컴포넌트에서 FastAPI GET /api/home으로 부른다. 처음 화면을 그릴 때 필요한 서버 데이터(D-012).
export type HomeOutcome = { status: "ok"; home: Home } | { status: "error" };

export async function getHome(): Promise<HomeOutcome> {
  const response = await fetchBackendAsUser("/api/home");
  if (response === null || !response.ok) return { status: "error" };
  const home = toHome(await readJson(response));
  return home === null ? { status: "error" } : { status: "ok", home };
}
