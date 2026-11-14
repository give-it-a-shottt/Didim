import { ApiRequestError, apiRequest } from "@/lib/api-request";
import { isObject, isStringArray } from "@/lib/json";

// 경험 카드(F-006) 응답 모양 · 확인 함수 · 브라우저 요청. 서버 컴포넌트(lib/cards-data.ts)와 브라우저가 같이 쓴다.
// 서버: backend/app/api/cards.py. 카드에는 원문 인용 · 사용자 답 · 근거 링크만 있다(D-003) — AI 질문은 화면 안내일 뿐.

export const CARD_SLOTS = ["situation", "task", "action", "result"] as const;
export type CardSlot = (typeof CARD_SLOTS)[number];

export const SLOT_LABELS: Record<CardSlot, string> = {
  situation: "상황",
  task: "과제",
  action: "행동",
  result: "결과",
};

export type CardStatus = "candidate" | "saved";

// 서버(backend/app/config.py)와 같은 값 — 안내 문구 · 입력 칸 상한용. 실제 상한은 서버가 지킨다.
export const CARD_TITLE_MAX_CHARS = 100;
export const CARD_MAX_ANSWER_CHARS = 2000;
export const CARD_MAX_CANDIDATES_PER_NOTE = 3;

export type CardSummary = {
  id: number;
  title: string;
  status: string;
  noteId: number | null;
  noteTitle: string | null; // null = 노트가 지워짐('원문 없음')
  blankCount: number;
  evidenceCount: number;
  updatedAt: string; // ISO
  blankSlots: CardSlot[];
};

export type CardField = {
  slot: CardSlot;
  quote: string | null; // 원문 인용(고칠 수 없음)
  quoteStart: number | null;
  quoteEnd: number | null;
  chunkId: number | null;
  question: string | null; // 빈칸 질문(AI) — 카드 내용 아님
  answer: string | null; // 내 답
};

export type CardDetail = {
  id: number;
  title: string;
  status: string;
  noteId: number | null;
  noteTitle: string | null;
  updatedAt: string;
  blankCount: number;
  evidenceCount: number;
  fields: CardField[];
};

export type FindResult = {
  cardIds: number[];
  quotedFields: number;
  emptiedFields: number;
  chunksSent: number;
  chunksTotal: number;
  remainingToday: number;
};

export function cardHref(cardId: number): string {
  return `/cards/${cardId}`;
}

export function isCardSlot(value: unknown): value is CardSlot {
  return typeof value === "string" && (CARD_SLOTS as readonly string[]).includes(value);
}

/** 빈칸 = 인용도 내 답도 없는 칸 */
export function isBlank(field: Pick<CardField, "quote" | "answer">): boolean {
  return field.quote === null && field.answer === null;
}

const KOREA_DATE = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit" });

/** "2026-11-05T03:00:00Z" → "11.05"(한국 날짜). 읽지 못하면 빈 글자. */
export function formatCardDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const parts = KOREA_DATE.formatToParts(date);
  const month = parts.find((part) => part.type === "month")?.value;
  const day = parts.find((part) => part.type === "day")?.value;
  return month && day ? `${month}.${day}` : "";
}

/** 제목에 검색어가 든 카드만(대소문자 무시). 자소서 탭의 카드 목록 · [카드 연결] 창이 같이 쓴다.
 *  검색어가 비어도 항상 새 배열을 돌려준다 — 부르는 쪽이 바로 .sort()를 거는데, 받은 props 배열을 바꾸면
 *  같은 카드 목록을 받은 다른 부품의 순서까지 바뀐다(3차 리뷰 R1). */
export function filterCardsByTitle<T extends { title: string }>(cards: readonly T[], search: string): T[] {
  const term = search.trim().toLocaleLowerCase("ko-KR");
  return term ? cards.filter((card) => card.title.toLocaleLowerCase("ko-KR").includes(term)) : [...cards];
}

// --- 응답 확인 ---

const isNullableString = (value: unknown): value is string | null => value === null || typeof value === "string";
const isNullableNumber = (value: unknown): value is number | null => value === null || typeof value === "number";

export function toCardSummary(value: unknown): CardSummary | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.title !== "string" ||
    typeof value.status !== "string" ||
    !isNullableNumber(value.note_id) ||
    !isNullableString(value.note_title) ||
    typeof value.blank_count !== "number" ||
    typeof value.evidence_count !== "number" ||
    typeof value.updated_at !== "string" ||
    !isStringArray(value.blank_slots) ||
    !value.blank_slots.every(isCardSlot)
  ) {
    return null;
  }
  return {
    id: value.id,
    title: value.title,
    status: value.status,
    noteId: value.note_id,
    noteTitle: value.note_title,
    blankCount: value.blank_count,
    evidenceCount: value.evidence_count,
    updatedAt: value.updated_at,
    blankSlots: value.blank_slots,
  };
}

function toCardField(value: unknown): CardField | null {
  if (
    !isObject(value) ||
    !isCardSlot(value.slot) ||
    !isNullableString(value.quote) ||
    !isNullableNumber(value.quote_start) ||
    !isNullableNumber(value.quote_end) ||
    !isNullableNumber(value.chunk_id) ||
    !isNullableString(value.question) ||
    !isNullableString(value.answer)
  ) {
    return null;
  }
  return {
    slot: value.slot,
    quote: value.quote,
    quoteStart: value.quote_start,
    quoteEnd: value.quote_end,
    chunkId: value.chunk_id,
    question: value.question,
    answer: value.answer,
  };
}

export function toCardDetail(value: unknown): CardDetail | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.title !== "string" ||
    typeof value.status !== "string" ||
    !isNullableNumber(value.note_id) ||
    !isNullableString(value.note_title) ||
    typeof value.updated_at !== "string" ||
    typeof value.blank_count !== "number" ||
    typeof value.evidence_count !== "number" ||
    !Array.isArray(value.fields)
  ) {
    return null;
  }
  const fields = value.fields.map(toCardField);
  if (fields.some((field) => field === null)) return null;
  return {
    id: value.id,
    title: value.title,
    status: value.status,
    noteId: value.note_id,
    noteTitle: value.note_title,
    updatedAt: value.updated_at,
    blankCount: value.blank_count,
    evidenceCount: value.evidence_count,
    fields: fields as CardField[],
  };
}

// --- 브라우저에서 부르는 요청(TanStack Query의 queryFn · mutationFn, D-012 — 요청 · 오류는 lib/api-request.ts) ---

function detailOrThrow(body: unknown): CardDetail {
  const detail = toCardDetail(body);
  if (detail === null) {
    throw new ApiRequestError("카드를 읽지 못했어요. 새로 고침해 확인해 주세요.");
  }
  return detail;
}

/** [카드 후보 찾기]. 409(이미 찾음 · 찾는 중) · 422 · 429 · 502 · 503은 서버 문구(detail)를 그대로 보여 준다. */
export async function findCandidates(noteId: number): Promise<FindResult> {
  const body = await apiRequest("POST", `/api/notes/${noteId}/cards/candidates`, "카드 후보를 찾지 못했어요. 잠시 뒤 다시 시도해 주세요.");
  if (
    !isObject(body) ||
    !Array.isArray(body.card_ids) ||
    !body.card_ids.every((id) => typeof id === "number") ||
    typeof body.quoted_fields !== "number" ||
    typeof body.emptied_fields !== "number" ||
    typeof body.chunks_sent !== "number" ||
    typeof body.chunks_total !== "number" ||
    typeof body.remaining_today !== "number"
  ) {
    throw new ApiRequestError("찾은 결과를 읽지 못했어요. 새로 고침해 확인해 주세요.");
  }
  return {
    cardIds: body.card_ids as number[],
    quotedFields: body.quoted_fields,
    emptiedFields: body.emptied_fields,
    chunksSent: body.chunks_sent,
    chunksTotal: body.chunks_total,
    remainingToday: body.remaining_today,
  };
}

export async function fetchCard(cardId: number): Promise<CardDetail> {
  return detailOrThrow(await apiRequest("GET", `/api/cards/${cardId}`, "카드를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요."));
}

/** 후보 → 저장(제목 확인). 이미 저장한 카드면 제목만 바뀐다. */
export async function saveCard(cardId: number, title: string): Promise<CardDetail> {
  return detailOrThrow(
    await apiRequest("POST", `/api/cards/${cardId}/save`, "카드를 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.", { title }),
  );
}

export async function deleteCard(cardId: number): Promise<void> {
  await apiRequest("DELETE", `/api/cards/${cardId}`, "카드를 지우지 못했어요. 잠시 뒤 다시 시도해 주세요.");
}

/** 내 답 저장(빈 글자면 답을 지움) · 인용 빼기. 인용을 뺄 때도 지금 입력한 답을 같이 보낸다(답이 지워지지 않게). */
export async function updateField(
  cardId: number,
  slot: CardSlot,
  { answer, removeQuote = false }: { answer: string; removeQuote?: boolean },
): Promise<CardDetail> {
  return detailOrThrow(
    await apiRequest("PUT", `/api/cards/${cardId}/fields/${slot}`, "칸을 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.", {
      answer,
      remove_quote: removeQuote,
    }),
  );
}
