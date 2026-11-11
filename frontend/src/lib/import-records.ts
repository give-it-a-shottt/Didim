// 기록 가져오기(F-002) 요청과 응답 모양. 서버: POST /api/notes/import (backend/app/api/notes.py)

import { detailOf, readJson } from "@/lib/json";

// 서버(backend/app/config.py · app/importers/markdown.py)와 같은 값. 화면에서 먼저 알려 주려고 두고, 최종 확인은 서버가 한다.
export const MAX_IMPORT_FILES = 20;
export const MAX_IMPORT_FILE_MB = 1;
export const MAX_IMPORT_TOTAL_MB = MAX_IMPORT_FILES * MAX_IMPORT_FILE_MB;
export const ACCEPTED_EXTENSIONS = ".md,.markdown";
const BYTES_PER_MB = 1024 * 1024;

export type NoteKind = "study" | "project";

export const NOTE_KIND_LABELS: Record<NoteKind, string> = {
  study: "학습 노트",
  project: "프로젝트 · 경험",
};

/** 노트 종류 값 → 화면 이름. 모르는 값이면 그대로 보여 준다(서버에 새 종류가 생겨도 깨지지 않게). */
export function noteKindLabel(kind: string): string {
  return kind in NOTE_KIND_LABELS ? NOTE_KIND_LABELS[kind as NoteKind] : kind;
}

export type ImportResponse = {
  summary: { notes: number; chunks: number; duplicates: number; failed: number };
  imported: { filename: string; note_id: number; title: string; chunk_count: number }[];
  duplicates: { filename: string; existing_note_id: number; existing_title: string }[];
  failed: { filename: string; reason: string }[];
};

export type ImportOutcome =
  | { ok: true; data: ImportResponse }
  | { ok: false; message: string; needsLogin: boolean };

const FALLBACK_ERROR = "기록을 올리지 못했어요. 잠시 후 다시 시도해 주세요.";
const NETWORK_ERROR = "네트워크 문제로 올리지 못했어요. 연결을 확인하고 다시 시도해 주세요.";

// 보내기 전에 화면에서 거르는 이유. 서버는 합계가 너무 크면 본문을 다 받기 전에 413을 돌려주는데,
// Next.js 프록시(rewrites)를 거치면 브라우저에는 413 대신 연결 끊김으로 보인다(직접 확인, 2026-11-10).
export function checkSelection(files: File[]): string | null {
  if (files.length > MAX_IMPORT_FILES) return `한 번에 ${MAX_IMPORT_FILES}개까지 올릴 수 있어요.`;
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  if (totalBytes > MAX_IMPORT_TOTAL_MB * BYTES_PER_MB) {
    return `한 번에 올릴 수 있는 용량(${MAX_IMPORT_TOTAL_MB}MB)을 넘었어요.`;
  }
  return null;
}

function isImportResponse(body: unknown): body is ImportResponse {
  return (
    typeof body === "object" &&
    body !== null &&
    "summary" in body &&
    "imported" in body &&
    "duplicates" in body &&
    "failed" in body
  );
}


// 어떤 경우에도 예외를 던지지 않고 결과(성공 · 실패 문구)를 돌려준다. 화면이 '처리 중'에 멈추지 않게.
export async function importMarkdownFiles(files: File[], kind: NoteKind): Promise<ImportOutcome> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("kind", kind);

  let response: Response;
  try {
    response = await fetch("/api/notes/import", { method: "POST", body: form });
  } catch {
    return { ok: false, message: NETWORK_ERROR, needsLogin: false };
  }

  const body = await readJson(response);
  if (response.ok) {
    return isImportResponse(body) ? { ok: true, data: body } : { ok: false, message: FALLBACK_ERROR, needsLogin: false };
  }
  if (response.status === 401) {
    return { ok: false, message: "로그인이 만료되었어요. 다시 로그인해 주세요.", needsLogin: true };
  }
  // 400 · 413은 서버가 이유를 적어 보낸다. 422(값 형식) · 500은 사용자에게 보여 줄 이유가 없어 기본 문구.
  const detail = response.status === 400 || response.status === 413 ? detailOf(body) : null;
  return { ok: false, message: detail ?? FALLBACK_ERROR, needsLogin: false };
}
