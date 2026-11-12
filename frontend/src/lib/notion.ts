// 노션 연결(F-005) 브라우저 요청 · 응답 모양. 서버: backend/app/api/notion.py
// 연결 상태 모양 · 안내 문구(서버 컴포넌트도 씀)는 lib/notion-status.ts.

import { ApiRequestError, apiRequest } from "@/lib/api-request";
import { isObject } from "@/lib/json";
import type { ImportResponse, NoteKind } from "@/lib/import-records";

// 서버(backend/app/config.py)와 같은 값 — 안내용. 실제 상한은 서버가 지킨다.
export const NOTION_MAX_IMPORT_PAGES = 20;
export const NOTION_MAX_PAGE_LIST = 100;

export type NotionPage = {
  id: string;
  title: string;
  lastEditedTime: string | null;
  importedNoteId: number | null; // 이미 가져온 노트
};

export type NotionPageList = {
  pages: NotionPage[];
  truncated: boolean; // 최근 수정한 100개보다 많아 오래된 페이지가 빠짐
};

function toNotionPage(item: unknown): NotionPage | null {
  if (!isObject(item) || typeof item.id !== "string" || typeof item.title !== "string") return null;
  return {
    id: item.id,
    title: item.title,
    lastEditedTime: typeof item.last_edited_time === "string" ? item.last_edited_time : null,
    importedNoteId: typeof item.imported_note_id === "number" ? item.imported_note_id : null,
  };
}

const SHAPE_ERROR = "노션 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요.";

/** 가져올 수 있는 페이지 목록. 409(연결 안 됨 · 끊김)는 status가 409인 ApiRequestError — 화면이 설정 링크를 같이 보여 준다. */
export async function fetchNotionPages(): Promise<NotionPageList> {
  const body = await apiRequest("GET", "/api/notion/pages", "노션 페이지 목록을 불러오지 못했어요.");
  if (!isObject(body) || !Array.isArray(body.pages)) throw new ApiRequestError(SHAPE_ERROR);
  const pages = body.pages.map(toNotionPage);
  if (pages.some((page) => page === null)) throw new ApiRequestError(SHAPE_ERROR);
  return { pages: pages as NotionPage[], truncated: body.truncated === true };
}

export type NotionImportResult = {
  // 결과 요약 화면을 마크다운 가져오기와 같이 쓰려고 같은 모양으로 바꾼다(filename 자리에 페이지 제목)
  data: ImportResponse;
  skippedBlocks: number;
  connectionBroken: boolean;
};

const UNKNOWN_PAGE = "제목을 모르는 페이지";

function titleOf(value: unknown): string {
  return typeof value === "string" && value ? value : UNKNOWN_PAGE;
}

/** 응답 모양을 확인하며 바꾼다. 노트 번호처럼 꼭 있어야 하는 값이 틀리면 null(가짜 번호로 채우지 않음, 1차 리뷰 R1). */
function toNotionImportResult(body: unknown): NotionImportResult | null {
  if (!isObject(body) || !isObject(body.summary)) return null;
  const { summary } = body;
  if (
    !Array.isArray(body.imported) ||
    !Array.isArray(body.duplicates) ||
    !Array.isArray(body.failed) ||
    typeof summary.notes !== "number" ||
    typeof summary.chunks !== "number"
  ) {
    return null;
  }
  const imported: ImportResponse["imported"] = [];
  for (const item of body.imported) {
    if (!isObject(item) || typeof item.note_id !== "number" || typeof item.chunk_count !== "number") return null;
    imported.push({ filename: titleOf(item.title), note_id: item.note_id, title: titleOf(item.title), chunk_count: item.chunk_count });
  }
  const duplicates: ImportResponse["duplicates"] = [];
  for (const item of body.duplicates) {
    if (!isObject(item) || typeof item.existing_note_id !== "number") return null;
    duplicates.push({
      filename: titleOf(item.title),
      existing_note_id: item.existing_note_id,
      existing_title: titleOf(item.existing_title),
    });
  }
  const failed: ImportResponse["failed"] = [];
  for (const item of body.failed) {
    if (!isObject(item) || typeof item.reason !== "string") return null;
    failed.push({ filename: titleOf(item.title), reason: item.reason });
  }
  return {
    data: {
      summary: { notes: summary.notes, chunks: summary.chunks, duplicates: duplicates.length, failed: failed.length },
      imported,
      duplicates,
      failed,
    },
    skippedBlocks: typeof summary.skipped_blocks === "number" ? summary.skipped_blocks : 0,
    connectionBroken: body.connection_broken === true,
  };
}

export async function importNotionPages(pageIds: string[], kind: NoteKind): Promise<NotionImportResult> {
  const body = await apiRequest("POST", "/api/notion/import", "노션 페이지를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.", {
    page_ids: pageIds,
    kind,
  });
  const result = toNotionImportResult(body);
  if (result === null) throw new ApiRequestError(SHAPE_ERROR);
  return result;
}

export async function disconnectNotion(): Promise<void> {
  await apiRequest("DELETE", "/api/notion/connection", "연결을 끊지 못했어요. 잠시 후 다시 시도해 주세요.");
}
