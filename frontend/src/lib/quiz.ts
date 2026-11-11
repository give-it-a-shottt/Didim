import { parseDbId } from "@/lib/ids";
import { detailOf, isObject, isStringArray, readJson } from "@/lib/json";

// 퀴즈 · 복습(F-004) 응답 모양과 확인 함수. 서버 컴포넌트(lib/quiz-data.ts)와 브라우저(퀴즈 풀기 · 문제 만들기)가 같이 쓴다.
// 서버: backend/app/api/quizzes.py. 목록에는 정답 · 해설 · 인용이 없고, 답을 낸 뒤에만 받는다.

// 노트당 최대 문제 수. 서버(backend/app/config.py MAX_QUIZZES_PER_NOTE)와 같은 값 — 안내 문구용, 실제 상한은 서버가 지킨다.
export const MAX_QUIZZES_PER_NOTE = 10;

export type QuizKind = "mcq" | "ox";

export type QuizCard = {
  id: number;
  noteId: number;
  noteTitle: string;
  kind: string;
  question: string;
  choices: string[];
  nextReviewOn: string; // YYYY-MM-DD(한국 날짜)
  inWrongNotes: boolean;
};

export type AnswerResult = {
  correct: boolean;
  answerIndex: number;
  explanation: string;
  noteId: number;
  noteTitle: string;
  chunkId: number;
  quote: string;
  nextReviewOn: string;
  inWrongNotes: boolean;
};

export type GenerateResult = {
  created: number;
  dropped: number;
  remainingToday: number;
};

// --- 세션: 백엔드에 세션 표가 없어서 주소가 세션 종류를 뜻한다(사용자 확인 2026-11-11) ---
// /quiz/today = 오늘 복습, /quiz/wrong = 오답노트 다시 풀기, /quiz/note-12 = 노트 12만 풀기

export type QuizSession = { kind: "today" } | { kind: "wrong" } | { kind: "note"; noteId: number };

export function parseQuizSession(sessionId: string): QuizSession | null {
  if (sessionId === "today") return { kind: "today" };
  if (sessionId === "wrong") return { kind: "wrong" };
  const match = /^note-(\d+)$/.exec(sessionId);
  const noteId = match ? parseDbId(match[1]) : null;
  return noteId === null ? null : { kind: "note", noteId };
}

export function noteSessionHref(noteId: number): string {
  return `/quiz/note-${noteId}`;
}

/** 근거 칩 링크. 검색 결과(F-003)와 같은 모양 — 노트 상세가 그 조각을 강조하고 스크롤한다. */
export function evidenceHref(noteId: number, chunkId: number): string {
  return `/records/${noteId}?chunk=${chunkId}#chunk-${chunkId}`;
}

export const QUIZ_KIND_LABELS: Record<QuizKind, string> = { mcq: "객관식", ox: "OX" };

export function quizKindLabel(kind: string): string {
  return kind in QUIZ_KIND_LABELS ? QUIZ_KIND_LABELS[kind as QuizKind] : kind;
}

/** "2026-11-12" → "11월 12일". 시간대 변환 없이 글자만 읽는다(서버가 이미 한국 날짜로 준다). */
export function formatReviewDate(isoDate: string): string {
  const match = /^\d{4}-(\d{2})-(\d{2})$/.exec(isoDate);
  return match ? `${Number(match[1])}월 ${Number(match[2])}일` : isoDate;
}

// --- 응답 확인 ---

export function toQuizCard(value: unknown): QuizCard | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.note_id !== "number" ||
    typeof value.note_title !== "string" ||
    typeof value.kind !== "string" ||
    typeof value.question !== "string" ||
    !isStringArray(value.choices) ||
    typeof value.next_review_on !== "string" ||
    typeof value.in_wrong_notes !== "boolean"
  ) {
    return null;
  }
  return {
    id: value.id,
    noteId: value.note_id,
    noteTitle: value.note_title,
    kind: value.kind,
    question: value.question,
    choices: value.choices,
    nextReviewOn: value.next_review_on,
    inWrongNotes: value.in_wrong_notes,
  };
}

/** 응답의 quizzes 배열을 확인한다. 하나라도 모양이 틀리면 null(화면은 "불러오지 못했어요"). */
export function toQuizCards(body: unknown): QuizCard[] | null {
  if (!isObject(body) || !Array.isArray(body.quizzes)) {
    return null;
  }
  const cards = body.quizzes.map(toQuizCard);
  return cards.some((card) => card === null) ? null : (cards as QuizCard[]);
}

function toAnswerResult(value: unknown): AnswerResult | null {
  if (
    !isObject(value) ||
    typeof value.correct !== "boolean" ||
    typeof value.answer_index !== "number" ||
    typeof value.explanation !== "string" ||
    typeof value.note_id !== "number" ||
    typeof value.note_title !== "string" ||
    typeof value.chunk_id !== "number" ||
    typeof value.quote !== "string" ||
    typeof value.next_review_on !== "string" ||
    typeof value.in_wrong_notes !== "boolean"
  ) {
    return null;
  }
  return {
    correct: value.correct,
    answerIndex: value.answer_index,
    explanation: value.explanation,
    noteId: value.note_id,
    noteTitle: value.note_title,
    chunkId: value.chunk_id,
    quote: value.quote,
    nextReviewOn: value.next_review_on,
    inWrongNotes: value.in_wrong_notes,
  };
}

// --- 브라우저에서 부르는 요청(TanStack Query useMutation의 mutationFn, D-012) ---
// 브라우저는 같은 주소의 /api/*로 부르고 Next가 FastAPI로 넘긴다(next.config.ts rewrites, D-010).

/** 실패 이유를 담은 오류. 화면은 message를 그대로 보여 주고, needsLogin이면 로그인 링크를 같이 둔다. */
export class QuizRequestError extends Error {
  readonly needsLogin: boolean;
  readonly status: number | null;

  constructor(message: string, { needsLogin = false, status = null }: { needsLogin?: boolean; status?: number | null } = {}) {
    super(message);
    this.name = "QuizRequestError";
    this.needsLogin = needsLogin;
    this.status = status;
  }
}

const NETWORK_ERROR = "네트워크 문제로 보내지 못했어요. 연결을 확인하고 다시 시도해 주세요.";
const LOGIN_ERROR = "로그인이 풀렸어요. 다시 로그인해 주세요.";

async function postJson(path: string, payload?: unknown): Promise<{ response: Response; body: unknown }> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
  } catch {
    throw new QuizRequestError(NETWORK_ERROR);
  }
  const body = await readJson(response);
  if (response.status === 401) {
    throw new QuizRequestError(LOGIN_ERROR, { needsLogin: true, status: 401 });
  }
  return { response, body };
}

export async function submitAnswer(quizId: number, chosenIndex: number): Promise<AnswerResult> {
  const { response, body } = await postJson(`/api/quizzes/${quizId}/answer`, { chosen_index: chosenIndex });
  if (!response.ok) {
    throw new QuizRequestError(detailOf(body) ?? "답을 보내지 못했어요. 잠시 뒤 다시 시도해 주세요.", {
      status: response.status,
    });
  }
  const result = toAnswerResult(body);
  if (result === null) {
    throw new QuizRequestError("채점 결과를 읽지 못했어요. 잠시 뒤 다시 시도해 주세요.", { status: response.status });
  }
  return result;
}

/** [문제 만들기]. 409(이미 있음 · 만드는 중) · 422 · 429 · 502 · 503은 서버 문구(detail)를 그대로 보여 준다. */
export async function generateQuizzes(noteId: number): Promise<GenerateResult> {
  const { response, body } = await postJson(`/api/notes/${noteId}/quizzes`);
  if (!response.ok) {
    throw new QuizRequestError(detailOf(body) ?? "문제를 만들지 못했어요. 잠시 뒤 다시 시도해 주세요.", {
      status: response.status,
    });
  }
  if (
    !isObject(body) ||
    typeof body.created !== "number" ||
    typeof body.dropped !== "number" ||
    typeof body.remaining_today !== "number"
  ) {
    throw new QuizRequestError("만든 결과를 읽지 못했어요. 새로 고침해 확인해 주세요.", { status: response.status });
  }
  return { created: body.created, dropped: body.dropped, remainingToday: body.remaining_today };
}
