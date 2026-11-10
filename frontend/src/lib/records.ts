import "server-only";

import { fetchBackendAsUser } from "@/lib/backend";

// 기록 검색 · 노트 상세를 서버 컴포넌트에서 FastAPI로 부른다(F-003, D-012 서버 데이터는 서버 컴포넌트).

// 검색어 글자 수 상한. 서버(backend/app/config.py MAX_SEARCH_QUERY_CHARS)와 같은 값이다.
export const MAX_SEARCH_QUERY_CHARS = 200;

export type SearchResult = {
  chunkId: number;
  noteId: number;
  noteTitle: string;
  headingPath: string;
  excerpt: string;
  matchedTerms: string[];
};

export type SearchOutcome =
  | { status: "ok"; results: SearchResult[] }
  | { status: "unavailable"; message: string } // 503: 이 DB에서 검색 불가 · 시간 상한(3초) 넘음 — 서버가 준 이유
  | { status: "error" };

const DEFAULT_UNAVAILABLE_MESSAGE = "지금은 기록 검색을 쓸 수 없어요. 잠시 뒤 다시 해 주세요.";

export type NoteChunk = {
  id: number;
  headingPath: string;
  // 노트 원문의 코드 포인트 위치(파이썬 글자 단위). 자바스크립트 위치로 바꾸는 것은 components/note-markdown.tsx가 한다.
  startOffset: number;
  endOffset: number;
};

export type NoteDetail = {
  id: number;
  title: string;
  kind: string;
  content: string;
  chunks: NoteChunk[];
};

export type NoteOutcome = { status: "ok"; note: NoteDetail } | { status: "not-found" } | { status: "error" };

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function toSearchResult(value: unknown): SearchResult | null {
  if (
    !isObject(value) ||
    typeof value.chunk_id !== "number" ||
    typeof value.note_id !== "number" ||
    typeof value.note_title !== "string" ||
    typeof value.heading_path !== "string" ||
    typeof value.excerpt !== "string" ||
    !isStringArray(value.matched_terms)
  ) {
    return null;
  }
  return {
    chunkId: value.chunk_id,
    noteId: value.note_id,
    noteTitle: value.note_title,
    headingPath: value.heading_path,
    excerpt: value.excerpt,
    matchedTerms: value.matched_terms,
  };
}

export async function searchRecords(query: string): Promise<SearchOutcome> {
  const params = new URLSearchParams({ q: query });
  const response = await fetchBackendAsUser(`/api/search?${params.toString()}`);
  if (response === null) {
    return { status: "error" };
  }
  if (response.status === 503) {
    const body = await readJson(response);
    const detail = isObject(body) && typeof body.detail === "string" ? body.detail : null;
    return { status: "unavailable", message: detail ?? DEFAULT_UNAVAILABLE_MESSAGE };
  }
  const body = response.ok ? await readJson(response) : null;
  if (!isObject(body) || !Array.isArray(body.results)) {
    return { status: "error" };
  }
  const results = body.results.map(toSearchResult);
  if (results.some((result) => result === null)) {
    return { status: "error" };
  }
  return { status: "ok", results: results as SearchResult[] };
}

function toNoteChunk(value: unknown): NoteChunk | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.heading_path !== "string" ||
    typeof value.start_offset !== "number" ||
    typeof value.end_offset !== "number"
  ) {
    return null;
  }
  return {
    id: value.id,
    headingPath: value.heading_path,
    startOffset: value.start_offset,
    endOffset: value.end_offset,
  };
}

export async function getNote(noteId: number): Promise<NoteOutcome> {
  const response = await fetchBackendAsUser(`/api/notes/${noteId}`);
  if (response === null) {
    return { status: "error" };
  }
  if (response.status === 404) {
    return { status: "not-found" };
  }
  const body = response.ok ? await readJson(response) : null;
  if (
    !isObject(body) ||
    typeof body.id !== "number" ||
    typeof body.title !== "string" ||
    typeof body.kind !== "string" ||
    typeof body.content !== "string" ||
    !Array.isArray(body.chunks)
  ) {
    return { status: "error" };
  }
  const chunks = body.chunks.map(toNoteChunk);
  if (chunks.some((chunk) => chunk === null)) {
    return { status: "error" };
  }
  return {
    status: "ok",
    note: { id: body.id, title: body.title, kind: body.kind, content: body.content, chunks: chunks as NoteChunk[] },
  };
}
