import { ApiRequestError, apiRequest } from "@/lib/api-request";
import { type CardSlot, isCardSlot } from "@/lib/cards";
import { isObject } from "@/lib/json";

// 근거 달린 자소서 초안(F-008) 응답 모양 · 확인 함수 · 브라우저 요청. 서버 컴포넌트(lib/drafts-data.ts)와 브라우저가 같이 쓴다.
// 서버: backend/app/api/drafts.py. 근거는 항상 내 카드 칸 글(원문 인용 · 내 답)이고, 근거 상태는 서버가 읽을 때마다
// 지금 카드와 다시 비교한 값이다(AI 없음 — 사용자 확인 2026-11-14).

export type EvidenceStatus = "ok" | "none" | "card_gone" | "changed";
export type QuoteSource = "quote" | "answer"; // 카드 칸의 원문 인용 · 내 답

/** [카드 연결]로 붙일 근거: 내 저장 카드의 칸 하나에서 원문 인용 또는 내 답 통째로(백엔드 EvidenceLink와 같은 이름). */
export type EvidenceLink = { cardId: number; slot: CardSlot; quoteSource: QuoteSource };

/** 화면 부품에 내려 주는 요청 하나의 상태(진행 중 · 오류)와 실행 함수. 부품은 TanStack Query를 몰라도 된다(2차 리뷰 R1). */
export type RequestState<Run> = { pending: boolean; error: Error | null; run: Run };
export type SentenceOrigin = "ai" | "edited" | "user";

export type Evidence = {
  cardId: number | null; // 카드가 지워졌으면 null
  cardTitle: string | null;
  noteTitle: string | null;
  slot: CardSlot;
  quote: string; // 카드 칸 글(내 기록 원문 — 명조로 보여 준다)
  quoteSource: QuoteSource;
  addedBy: "ai" | "user"; // user = [카드 연결]
};

export type DraftSentence = {
  id: number;
  position: number;
  text: string;
  origin: SentenceOrigin;
  originalText: string | null; // AI가 쓴 원래 문장
  evidenceStatus: EvidenceStatus;
  evidence: Evidence | null;
};

export type Draft = {
  id: number;
  questionId: number;
  version: number;
  completedAt: string | null;
  updatedAt: string;
  chars: number;
  charLimit: number | null;
  editedPercent: number;
  sentenceCount: number;
  unsupportedCount: number;
  sentences: DraftSentence[];
};

export type DraftQuestion = { id: number; position: number; text: string; charLimit: number | null; draft: Draft | null };

export type ApplicationDrafts = {
  applicationId: number;
  analysisDone: boolean; // 공고 분석 ② 매칭을 끝냈는가
  matchedCardIds: number[]; // 초안 쓰기에 보낼 수 있는 카드(많이 매칭된 순)
  checkedAt: string; // 근거를 다시 검사한 시각
  questions: DraftQuestion[];
};

// 서버(backend/app/config.py)와 같은 값 — 안내 문구 · 입력 칸 상한용. 실제 상한은 서버가 지킨다.
export const DRAFT_MAX_CARDS_SENT = 10;
export const DRAFT_SENTENCE_MAX_CHARS = 500;
export const DRAFT_DEFAULT_TARGET_CHARS = 700;

export const draftsQueryKey = (applicationId: number) => ["drafts", applicationId] as const;

/** 문항 상태 배지(Figma Didim/문항 항목): 시작 전(초안 없음) · 작성 중 · 완료(사용자 확인 2026-11-14). */
export function questionStage(question: DraftQuestion): "시작 전" | "작성 중" | "완료" {
  if (question.draft === null) return "시작 전";
  return question.draft.completedAt === null ? "작성 중" : "완료";
}

/** "487 / 700자" · 제한이 없으면 "487자". */
export function charCountLabel(chars: number, limit: number | null): string {
  return limit === null ? `${chars.toLocaleString("ko-KR")}자` : `${chars.toLocaleString("ko-KR")} / ${limit.toLocaleString("ko-KR")}자`;
}

const KOREA_TIME = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false });

/** ISO 시각 → "15:24"(한국 시간). 읽지 못하면 빈 글자. */
export function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : KOREA_TIME.format(date);
}

// --- 응답 확인 ---

const isNullableString = (value: unknown): value is string | null => value === null || typeof value === "string";
const isNullableNumber = (value: unknown): value is number | null => value === null || typeof value === "number";
const EVIDENCE_STATUSES: readonly string[] = ["ok", "none", "card_gone", "changed"];
const ORIGINS: readonly string[] = ["ai", "edited", "user"];

function toEvidence(value: unknown): Evidence | null | undefined {
  if (value === null) return null;
  if (
    !isObject(value) ||
    !isNullableNumber(value.card_id) ||
    !isNullableString(value.card_title) ||
    !isNullableString(value.note_title) ||
    !isCardSlot(value.slot) ||
    typeof value.quote !== "string" ||
    (value.quote_source !== "quote" && value.quote_source !== "answer") ||
    (value.added_by !== "ai" && value.added_by !== "user")
  ) {
    return undefined; // 모양이 틀림
  }
  return {
    cardId: value.card_id,
    cardTitle: value.card_title,
    noteTitle: value.note_title,
    slot: value.slot,
    quote: value.quote,
    quoteSource: value.quote_source,
    addedBy: value.added_by,
  };
}

function toSentence(value: unknown): DraftSentence | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.position !== "number" ||
    typeof value.text !== "string" ||
    typeof value.origin !== "string" ||
    !ORIGINS.includes(value.origin) ||
    !isNullableString(value.original_text) ||
    typeof value.evidence_status !== "string" ||
    !EVIDENCE_STATUSES.includes(value.evidence_status)
  ) {
    return null;
  }
  const evidence = toEvidence(value.evidence);
  if (evidence === undefined) return null;
  return {
    id: value.id,
    position: value.position,
    text: value.text,
    origin: value.origin as SentenceOrigin,
    originalText: value.original_text,
    evidenceStatus: value.evidence_status as EvidenceStatus,
    evidence,
  };
}

export function toDraft(value: unknown): Draft | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.question_id !== "number" ||
    typeof value.version !== "number" ||
    !isNullableString(value.completed_at) ||
    typeof value.updated_at !== "string" ||
    typeof value.chars !== "number" ||
    !isNullableNumber(value.char_limit) ||
    typeof value.edited_percent !== "number" ||
    typeof value.sentence_count !== "number" ||
    typeof value.unsupported_count !== "number" ||
    !Array.isArray(value.sentences)
  ) {
    return null;
  }
  const sentences = value.sentences.map(toSentence);
  if (sentences.some((item) => item === null)) return null;
  return {
    id: value.id,
    questionId: value.question_id,
    version: value.version,
    completedAt: value.completed_at,
    updatedAt: value.updated_at,
    chars: value.chars,
    charLimit: value.char_limit,
    editedPercent: value.edited_percent,
    sentenceCount: value.sentence_count,
    unsupportedCount: value.unsupported_count,
    sentences: sentences as DraftSentence[],
  };
}

function toQuestion(value: unknown): DraftQuestion | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.position !== "number" ||
    typeof value.text !== "string" ||
    !isNullableNumber(value.char_limit)
  ) {
    return null;
  }
  const draft = value.draft === null ? null : toDraft(value.draft);
  if (value.draft !== null && draft === null) return null;
  return { id: value.id, position: value.position, text: value.text, charLimit: value.char_limit, draft };
}

export function toApplicationDrafts(value: unknown): ApplicationDrafts | null {
  if (
    !isObject(value) ||
    typeof value.application_id !== "number" ||
    typeof value.analysis_done !== "boolean" ||
    !Array.isArray(value.matched_card_ids) ||
    !value.matched_card_ids.every((item) => typeof item === "number") ||
    typeof value.checked_at !== "string" ||
    !Array.isArray(value.questions)
  ) {
    return null;
  }
  const questions = value.questions.map(toQuestion);
  if (questions.some((item) => item === null)) return null;
  return {
    applicationId: value.application_id,
    analysisDone: value.analysis_done,
    matchedCardIds: value.matched_card_ids as number[],
    checkedAt: value.checked_at,
    questions: questions as DraftQuestion[],
  };
}

/** 문항 하나의 초안을 응답으로 바꾼 새 목록(TanStack Query 캐시에 넣는다). */
export function withDraft(data: ApplicationDrafts, draft: Draft): ApplicationDrafts {
  return {
    ...data,
    questions: data.questions.map((question) => (question.id === draft.questionId ? { ...question, draft } : question)),
  };
}

// --- 브라우저 요청 (TanStack Query queryFn · mutationFn, D-012) ---

const BAD_RESPONSE = "서버 응답을 읽지 못했어요. 잠시 뒤 다시 시도해 주세요.";

export async function fetchDrafts(applicationId: number): Promise<ApplicationDrafts> {
  const body = await apiRequest("GET", `/api/applications/${applicationId}/drafts`, "자소서를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.");
  const drafts = toApplicationDrafts(body);
  if (drafts === null) throw new ApiRequestError(BAD_RESPONSE);
  return drafts;
}

export type WriteResult = { written: boolean; sentences: number; supported: number; remainingToday: number };

export async function writeDraft(applicationId: number, questionId: number, overwrite: boolean): Promise<WriteResult> {
  const body = await apiRequest(
    "POST",
    `/api/applications/${applicationId}/questions/${questionId}/draft`,
    "초안을 쓰지 못했어요. 이전 초안은 그대로예요. 잠시 뒤 다시 시도해 주세요.",
    { overwrite },
  );
  if (
    !isObject(body) ||
    typeof body.written !== "boolean" ||
    typeof body.sentences !== "number" ||
    typeof body.supported !== "number" ||
    typeof body.remaining_today !== "number"
  ) {
    throw new ApiRequestError(BAD_RESPONSE);
  }
  return { written: body.written, sentences: body.sentences, supported: body.supported, remainingToday: body.remaining_today };
}

/** 고친 목록의 문장 하나. id가 있으면 기존 문장(근거 유지), 없으면 새 문장(근거 없음). */
export type SentenceEdit = {
  id: number | null;
  text: string;
  link?: EvidenceLink;
  unlink?: boolean;
};

export async function updateDraft(draft: Draft, sentences: SentenceEdit[]): Promise<Draft> {
  const body = await apiRequest("PUT", `/api/drafts/${draft.id}`, "고친 문장을 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.", {
    version: draft.version,
    sentences: sentences.map((item) => ({
      id: item.id,
      text: item.text,
      link: item.link ? { card_id: item.link.cardId, slot: item.link.slot, quote_source: item.link.quoteSource } : null,
      unlink: item.unlink ?? false,
    })),
  });
  const saved = toDraft(body);
  if (saved === null) throw new ApiRequestError(BAD_RESPONSE);
  return saved;
}

/** 지금 초안의 문장 목록을 그대로 옮긴 편집 목록(여기서 한 문장만 바꿔 보낸다). */
export function editsOf(draft: Draft): SentenceEdit[] {
  return draft.sentences.map((item) => ({ id: item.id, text: item.text }));
}

export async function setDraftCompleted(draftId: number, completed: boolean): Promise<Draft> {
  const body = await apiRequest("PATCH", `/api/drafts/${draftId}`, "완료 표시를 바꾸지 못했어요. 잠시 뒤 다시 시도해 주세요.", {
    completed,
  });
  const saved = toDraft(body);
  if (saved === null) throw new ApiRequestError(BAD_RESPONSE);
  return saved;
}

export type QuestionEdit = { id: number | null; text: string; charLimit: number | null };

/** 문항 목록 저장. 지울 기존 문항은 removedIds로 직접 보낸다 — 화면이 본 목록과 서버 목록이 다르면 409(다른 탭이 먼저 바꿈). */
export async function replaceQuestions(applicationId: number, questions: QuestionEdit[], removedIds: number[]): Promise<ApplicationDrafts> {
  const body = await apiRequest(
    "PUT",
    `/api/applications/${applicationId}/questions`,
    "문항을 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.",
    {
      questions: questions.map((item) => ({ id: item.id, text: item.text, char_limit: item.charLimit })),
      removed_ids: removedIds,
    },
  );
  const drafts = toApplicationDrafts(body);
  if (drafts === null) throw new ApiRequestError(BAD_RESPONSE);
  return drafts;
}

/** '제출'로 바꾸기 직전에 근거 없는 문장 수를 새로 받는다(서버가 지금 카드와 다시 비교한 값). */
export async function fetchUnsupportedCount(applicationId: number): Promise<number> {
  const body = await apiRequest("GET", `/api/applications/${applicationId}`, "지원 정보를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.");
  if (!isObject(body) || typeof body.unsupported_sentence_count !== "number") throw new ApiRequestError(BAD_RESPONSE);
  return body.unsupported_sentence_count;
}
