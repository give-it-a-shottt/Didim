import { ApiRequestError, apiRequest } from "@/lib/api-request";
import { type CardSlot, isCardSlot } from "@/lib/card-slots";
import { isNullableString, isObject, isStringArray } from "@/lib/json";

// 면접 예상 질문(F-009) — 질문 하나의 모양 · 메모 저장(카드 상세와 [면접 연습] 탭이 같이 씀)과 [면접 연습] 탭(APL_02_004) 응답.
// 서버: backend/app/api/interview.py. [면접 질문 만들기] 요청은 카드 상세 전용이라 lib/cards.ts에 있다.

// 서버(backend/app/config.py의 같은 이름)와 같은 값 — 안내 문구 · 입력 칸 상한용. 실제 상한은 서버가 지킨다.
// 서버 값을 바꾸면 여기도 같이 고친다(메모 상한은 서버에서 CARD_MAX_ANSWER_CHARS를 따른다 — 3차 리뷰 R1).
export const INTERVIEW_MIN_QUESTIONS = 3;
export const INTERVIEW_MAX_QUESTIONS = 5;
export const INTERVIEW_MEMO_MAX_CHARS = 2000;

/** ok · changed(카드 칸 글이 바뀌어 인용이 없음) · card_gone(저장 카드가 아님) */
export type InterviewEvidenceStatus = "ok" | "changed" | "card_gone";

export type InterviewQuestion = {
  id: number;
  cardId: number;
  position: number;
  slot: CardSlot; // 근거 칸
  question: string;
  quote: string; // 근거 인용(만든 때 그 칸 글에 글자 그대로 있던 글)
  quoteSource: "quote" | "answer"; // 카드의 원문 인용 · 내 답
  evidenceStatus: InterviewEvidenceStatus;
  memo: string | null;
  answeredAt: string | null;
  updatedAt: string;
};

const EVIDENCE_STATUSES: readonly string[] = ["ok", "changed", "card_gone"];

export function toInterviewQuestion(value: unknown): InterviewQuestion | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.card_id !== "number" ||
    typeof value.position !== "number" ||
    !isCardSlot(value.slot) ||
    typeof value.question !== "string" ||
    typeof value.quote !== "string" ||
    (value.quote_source !== "quote" && value.quote_source !== "answer") ||
    typeof value.evidence_status !== "string" ||
    !EVIDENCE_STATUSES.includes(value.evidence_status) ||
    !isNullableString(value.memo) ||
    !isNullableString(value.answered_at) ||
    typeof value.updated_at !== "string"
  ) {
    return null;
  }
  return {
    id: value.id,
    cardId: value.card_id,
    position: value.position,
    slot: value.slot,
    question: value.question,
    quote: value.quote,
    quoteSource: value.quote_source,
    evidenceStatus: value.evidence_status as InterviewEvidenceStatus,
    memo: value.memo,
    answeredAt: value.answered_at,
    updatedAt: value.updated_at,
  };
}

/** 목록 전부가 질문 모양이면 배열, 하나라도 틀리면 null */
export function toInterviewQuestions(value: unknown): InterviewQuestion[] | null {
  if (!Array.isArray(value)) return null;
  const questions = value.map(toInterviewQuestion);
  return questions.some((question) => question === null) ? null : (questions as InterviewQuestion[]);
}

export type CardInterview = {
  cardId: number;
  cardTitle: string;
  noteTitle: string | null; // 카드가 나온 노트(지워졌으면 null)
  requirementNames: string[]; // 이 카드가 매칭된 역량(공고에 나온 순서)
  hasQuestions: boolean; // 합치기 전에 이 카드에 질문이 있었는지 — false면 '질문 없는 카드'(카드 상세에서 만들 수 있음)
  questions: InterviewQuestion[]; // 같은 글 질문을 합친 뒤(다른 카드 쪽으로 모두 합쳐지면 빈 목록)
};

export type ApplicationInterview = {
  applicationId: number;
  analysisDone: boolean;
  // 서버가 같은 글 질문을 합친 뒤 센 값(API 계약 · 다른 화면용). 이 탭은 메모를 저장할 때마다 바로 바뀌게 목록에서 다시 센다 —
  // 서버가 이미 합쳐 보내므로 같은 기준이다(interview-workspace.tsx).
  questionCount: number;
  answeredCount: number;
  cards: CardInterview[];
};

/** 화면 목록 한 줄 — 질문과 그 질문이 나온 카드 */
export type InterviewRow = { question: InterviewQuestion; card: CardInterview };

function toCardInterview(value: unknown): CardInterview | null {
  if (
    !isObject(value) ||
    typeof value.card_id !== "number" ||
    typeof value.card_title !== "string" ||
    !isNullableString(value.note_title) ||
    !isStringArray(value.requirement_names) ||
    typeof value.has_questions !== "boolean"
  ) {
    return null;
  }
  const questions = toInterviewQuestions(value.questions);
  if (questions === null) return null;
  return {
    cardId: value.card_id,
    cardTitle: value.card_title,
    noteTitle: value.note_title,
    requirementNames: value.requirement_names,
    hasQuestions: value.has_questions,
    questions,
  };
}

export function toApplicationInterview(value: unknown): ApplicationInterview | null {
  if (
    !isObject(value) ||
    typeof value.application_id !== "number" ||
    typeof value.analysis_done !== "boolean" ||
    typeof value.question_count !== "number" ||
    typeof value.answered_count !== "number" ||
    !Array.isArray(value.cards)
  ) {
    return null;
  }
  const cards = value.cards.map(toCardInterview);
  if (cards.some((card) => card === null)) return null;
  return {
    applicationId: value.application_id,
    analysisDone: value.analysis_done,
    questionCount: value.question_count,
    answeredCount: value.answered_count,
    cards: cards as CardInterview[],
  };
}

/** 카드별 질문을 한 줄 목록으로(Figma APL_02_004). 같은 글의 질문은 서버가 이미 하나로 합쳐 보낸다(답한 질문 우선 —
 *  질문 수 · 답한 수가 서버와 같은 기준, 1차 리뷰 R1 · R4). */
export function interviewRows(data: ApplicationInterview): InterviewRow[] {
  return data.cards.flatMap((card) => card.questions.map((question) => ({ question, card })));
}

/** 질문의 내 답 메모 저장. 빈 글자면 '답하지 않음'으로 돌아간다. */
export async function updateInterviewMemo(questionId: number, memo: string): Promise<InterviewQuestion> {
  const body = await apiRequest(
    "PATCH",
    `/api/interview-questions/${questionId}`,
    "메모를 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.",
    { memo },
  );
  const question = toInterviewQuestion(body);
  if (question === null) throw new ApiRequestError("저장한 메모를 읽지 못했어요. 새로 고침해 확인해 주세요.");
  return question;
}
