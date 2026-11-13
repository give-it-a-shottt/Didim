import "server-only";

import { cache } from "react";
import {
  type ApplicationDetail,
  type ApplicationSummary,
  toApplicationDetail,
  toApplicationSummary,
} from "@/lib/applications";
import { fetchBackendAsUser } from "@/lib/backend";
import { isObject, readJson } from "@/lib/json";

// 지원(F-007)을 서버 컴포넌트에서 FastAPI로 부른다. 처음 화면을 그릴 때 필요한 서버 데이터라 서버 컴포넌트(D-012).

export type ApplicationListOutcome =
  | { status: "ok"; total: number; applications: ApplicationSummary[] }
  | { status: "error" };

export type ApplicationOutcome =
  | { status: "ok"; application: ApplicationDetail }
  | { status: "not-found" }
  | { status: "error" };

export async function getApplicationList(): Promise<ApplicationListOutcome> {
  const response = await fetchBackendAsUser("/api/applications");
  if (response === null || !response.ok) return { status: "error" };
  const body = await readJson(response);
  if (!isObject(body) || typeof body.total !== "number" || !Array.isArray(body.applications)) {
    return { status: "error" };
  }
  const applications = body.applications.map(toApplicationSummary);
  if (applications.some((item) => item === null)) return { status: "error" };
  return { status: "ok", total: body.total, applications: applications as ApplicationSummary[] };
}

/** 지원 상세. 머리(layout)와 탭(page)이 같은 요청 안에서 같이 부르므로 cache로 한 번만 부른다. */
export const getApplication = cache(async (id: number): Promise<ApplicationOutcome> => {
  const response = await fetchBackendAsUser(`/api/applications/${id}`);
  if (response === null) return { status: "error" };
  if (response.status === 404) return { status: "not-found" };
  const application = response.ok ? toApplicationDetail(await readJson(response)) : null;
  return application === null ? { status: "error" } : { status: "ok", application };
});
