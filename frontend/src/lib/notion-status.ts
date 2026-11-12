// 노션 연결(F-005) 상태 모양 · 안내 문구. 서버 컴포넌트(설정 화면)와 브라우저가 같이 쓴다 — 요청 코드는 넣지 않는다
// (브라우저 요청은 lib/notion.ts, 서버 요청은 lib/notion-data.ts, F-005 1차 리뷰 R1).

import { isObject } from "@/lib/json";

// 연결 시작은 요청이 아니라 주소 이동(/api/notion/connect → 노션 동의 화면 → /api/notion/callback → /settings)이다.
export const NOTION_CONNECT_PATH = "/api/notion/connect";

export type NotionStatus = {
  configured: boolean; // 서버에 노션 client ID · secret · 암호화 키가 있는지
  status: "none" | "connected" | "broken";
  workspaceName: string | null;
};

export function toNotionStatus(body: unknown): NotionStatus | null {
  if (!isObject(body) || typeof body.configured !== "boolean") return null;
  if (body.status !== "none" && body.status !== "connected" && body.status !== "broken") return null;
  const workspaceName = typeof body.workspace_name === "string" ? body.workspace_name : null;
  return { configured: body.configured, status: body.status, workspaceName };
}

// 설정 화면으로 돌아올 때 붙는 ?notion_error= 값 → 안내 문구 (backend/app/api/notion.py _settings_redirect)
const CONNECT_ERRORS: Record<string, string> = {
  access_denied: "노션 연결을 취소했어요.",
  invalid_state: "연결 요청이 만료됐거나 맞지 않아요. [연결]을 다시 눌러 주세요.",
  exchange_failed: "노션에서 연결을 확인하지 못했어요. 잠시 후 다시 연결해 주세요.",
  not_configured: "서버에 노션 연결 설정이 아직 없어요.",
  save_failed: "연결 정보를 저장하지 못했어요. 잠시 후 다시 연결해 주세요.",
};

export function connectNotice(
  notion: string | undefined,
  notionError: string | undefined,
): { ok: boolean; message: string } | null {
  if (notion === "connected") return { ok: true, message: "노션을 연결했어요. 기록 추가에서 페이지를 골라 가져올 수 있어요." };
  if (notionError) return { ok: false, message: CONNECT_ERRORS[notionError] ?? CONNECT_ERRORS.exchange_failed };
  return null;
}
