import { ApiRequestError, apiRequest } from "@/lib/api-request";
import { type CardSlot, isCardSlot } from "@/lib/cards";
import { isObject } from "@/lib/json";

// 지원(공고) · 공고 분석(F-007) 응답 모양 · 확인 함수 · 브라우저 요청. 서버 컴포넌트(lib/applications-data.ts)와 브라우저가 같이 쓴다.
// 서버: backend/app/api/applications.py. 근거는 항상 원문 인용(공고 문장 · 내 카드 칸 글)이고, 역량 이름 · 맞는 이유는 AI 글이다(D-003).

export const APPLICATION_STATUSES = ["ready", "writing", "submitted"] as const;
export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];

export const STATUS_LABELS: Record<ApplicationStatus, string> = {
  ready: "준비",
  writing: "작성 중",
  submitted: "제출",
};

// 서버(backend/app/config.py)와 같은 값 — 입력 칸 상한 · 안내 문구용. 실제 상한은 서버가 지킨다.
export const APPLICATION_COMPANY_MAX_CHARS = 100;
export const APPLICATION_ROLE_MAX_CHARS = 100;
export const APPLICATION_URL_MAX_CHARS = 500;
export const POSTING_TEXT_MAX_CHARS = 10_000;
export const APPLICATION_MAX_QUESTIONS = 10;
export const APPLICATION_QUESTION_MAX_CHARS = 500;
export const APPLICATION_QUESTION_CHAR_LIMIT_MAX = 10_000; // 문항 글자 수 제한 칸 최대값
export const MAX_REQUIREMENTS = 12;
export const MATCH_CANDIDATES_PER_REQUIREMENT = 5;
// 공고 분석 한 번에 쓰는 AI 사용량 최대치: ① 역량 뽑기 1번 + ② 매칭 1번(설계 의도 — 요청 두 번, 각각 AI 1번).
// ②는 키워드 후보 카드가 없으면 AI를 부르지 않아 1번만 쓴다.
export const ANALYSIS_MAX_AI_CALLS = 2;
// 마감 임박(D-day 배지를 코랄로) — Figma Didim/D-day 설명 "D-7 이하만"
export const D_DAY_URGENT_DAYS = 7;

export type ApplicationSummary = {
  id: number;
  company: string;
  role: string;
  deadline: string | null; // "YYYY-MM-DD"(한국 날짜)
  daysLeft: number | null; // 0 = 오늘 마감, 음수 = 지남
  status: ApplicationStatus;
  url: string | null;
  requirementCount: number;
  matchedRequirementCount: number;
  extracted: boolean;
  matched: boolean;
};

export type RequirementMatch = {
  id: number;
  cardId: number;
  cardTitle: string;
  slot: CardSlot;
  quote: string; // 카드 칸 글에 글자 그대로 있는 문장
  quoteSource: "quote" | "answer"; // 카드의 원문 인용 · 내 답
  reason: string; // AI가 쓴 맞는 이유
};

export type Requirement = {
  id: number;
  name: string; // AI가 붙인 이름표
  kind: "required" | "preferred";
  quote: string; // 공고 원문 인용
  quoteStart: number;
  quoteEnd: number;
  matches: RequirementMatch[];
};

export type ApplicationQuestion = { id: number; text: string; charLimit: number | null };

export type ApplicationDetail = {
  id: number;
  company: string;
  role: string;
  deadline: string | null;
  daysLeft: number | null;
  url: string | null;
  postingText: string;
  status: ApplicationStatus;
  extracted: boolean;
  matched: boolean;
  questions: ApplicationQuestion[];
  requirements: Requirement[];
};

export function applicationHref(id: number, tab: "analysis" | "draft" | "interview" = "analysis"): string {
  return `/applications/${id}/${tab}`;
}

/** D-day 글자: 0 → "D-day", 3 → "D-3", 지났으면 "마감", 없으면 null. */
export function dDayLabel(daysLeft: number | null): string | null {
  if (daysLeft === null) return null;
  if (daysLeft < 0) return "마감";
  return daysLeft === 0 ? "D-day" : `D-${daysLeft}`;
}

/** "2026-11-19" → "11.19". 형식이 다르면 그대로. */
export function formatDeadline(deadline: string): string {
  const match = /^\d{4}-(\d{2})-(\d{2})$/.exec(deadline);
  return match ? `${match[1]}.${match[2]}` : deadline;
}

// --- 응답 확인 ---

const isNullableString = (value: unknown): value is string | null => value === null || typeof value === "string";
const isNullableNumber = (value: unknown): value is number | null => value === null || typeof value === "number";

function isStatus(value: unknown): value is ApplicationStatus {
  return typeof value === "string" && (APPLICATION_STATUSES as readonly string[]).includes(value);
}

export function toApplicationSummary(value: unknown): ApplicationSummary | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.company !== "string" ||
    typeof value.role !== "string" ||
    !isNullableString(value.deadline) ||
    !isNullableNumber(value.days_left) ||
    !isStatus(value.status) ||
    !isNullableString(value.url) ||
    typeof value.requirement_count !== "number" ||
    typeof value.matched_requirement_count !== "number" ||
    typeof value.extracted !== "boolean" ||
    typeof value.matched !== "boolean"
  ) {
    return null;
  }
  return {
    id: value.id,
    company: value.company,
    role: value.role,
    deadline: value.deadline,
    daysLeft: value.days_left,
    status: value.status,
    url: value.url,
    requirementCount: value.requirement_count,
    matchedRequirementCount: value.matched_requirement_count,
    extracted: value.extracted,
    matched: value.matched,
  };
}

function toMatch(value: unknown): RequirementMatch | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.card_id !== "number" ||
    typeof value.card_title !== "string" ||
    !isCardSlot(value.slot) ||
    typeof value.quote !== "string" ||
    (value.quote_source !== "quote" && value.quote_source !== "answer") ||
    typeof value.reason !== "string"
  ) {
    return null;
  }
  return {
    id: value.id,
    cardId: value.card_id,
    cardTitle: value.card_title,
    slot: value.slot,
    quote: value.quote,
    quoteSource: value.quote_source,
    reason: value.reason,
  };
}

function toRequirement(value: unknown): Requirement | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.name !== "string" ||
    (value.kind !== "required" && value.kind !== "preferred") ||
    typeof value.quote !== "string" ||
    typeof value.quote_start !== "number" ||
    typeof value.quote_end !== "number" ||
    !Array.isArray(value.matches)
  ) {
    return null;
  }
  const matches = value.matches.map(toMatch);
  if (matches.some((item) => item === null)) return null;
  return {
    id: value.id,
    name: value.name,
    kind: value.kind,
    quote: value.quote,
    quoteStart: value.quote_start,
    quoteEnd: value.quote_end,
    matches: matches as RequirementMatch[],
  };
}

function toQuestion(value: unknown): ApplicationQuestion | null {
  if (!isObject(value) || typeof value.id !== "number" || typeof value.text !== "string" || !isNullableNumber(value.char_limit)) {
    return null;
  }
  return { id: value.id, text: value.text, charLimit: value.char_limit };
}

export function toApplicationDetail(value: unknown): ApplicationDetail | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.company !== "string" ||
    typeof value.role !== "string" ||
    !isNullableString(value.deadline) ||
    !isNullableNumber(value.days_left) ||
    !isNullableString(value.url) ||
    typeof value.posting_text !== "string" ||
    !isStatus(value.status) ||
    !isNullableString(value.extracted_at) ||
    !isNullableString(value.matched_at) ||
    !Array.isArray(value.questions) ||
    !Array.isArray(value.requirements)
  ) {
    return null;
  }
  const questions = value.questions.map(toQuestion);
  const requirements = value.requirements.map(toRequirement);
  if (questions.some((item) => item === null) || requirements.some((item) => item === null)) return null;
  return {
    id: value.id,
    company: value.company,
    role: value.role,
    deadline: value.deadline,
    daysLeft: value.days_left,
    url: value.url,
    postingText: value.posting_text,
    status: value.status,
    extracted: value.extracted_at !== null,
    matched: value.matched_at !== null,
    questions: questions as ApplicationQuestion[],
    requirements: requirements as Requirement[],
  };
}

// --- 브라우저 요청 (TanStack Query mutationFn, D-012) ---

export type NewApplication = {
  company: string;
  role: string;
  deadline: string | null;
  url: string | null;
  postingText: string;
  questions: { text: string; charLimit: number | null }[];
};

const BAD_RESPONSE = "서버 응답을 읽지 못했어요. 잠시 뒤 다시 시도해 주세요.";

export async function createApplication(input: NewApplication): Promise<ApplicationDetail> {
  const body = await apiRequest("POST", "/api/applications", "공고를 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.", {
    company: input.company,
    role: input.role,
    deadline: input.deadline,
    url: input.url,
    posting_text: input.postingText,
    questions: input.questions.map((item) => ({ text: item.text, char_limit: item.charLimit })),
  });
  const detail = toApplicationDetail(body);
  if (detail === null) throw new ApiRequestError(BAD_RESPONSE);
  return detail;
}

export async function updateApplicationStatus(id: number, status: ApplicationStatus): Promise<void> {
  await apiRequest("PATCH", `/api/applications/${id}`, "상태를 바꾸지 못했어요. 잠시 뒤 다시 시도해 주세요.", { status });
}

export async function deleteApplication(id: number): Promise<void> {
  await apiRequest("DELETE", `/api/applications/${id}`, "공고를 지우지 못했어요. 잠시 뒤 다시 시도해 주세요.");
}

export type ExtractResult = { requirementCount: number; remainingToday: number };
export type MatchResult = { matches: number; matchedRequirements: number; requirementsSent: number; remainingToday: number };

export async function extractRequirements(id: number): Promise<ExtractResult> {
  const body = await apiRequest(
    "POST",
    `/api/applications/${id}/requirements`,
    "요구 역량을 뽑지 못했어요. 잠시 뒤 다시 시도해 주세요.",
  );
  if (!isObject(body) || typeof body.requirement_count !== "number" || typeof body.remaining_today !== "number") {
    throw new ApiRequestError(BAD_RESPONSE);
  }
  return { requirementCount: body.requirement_count, remainingToday: body.remaining_today };
}

export async function matchRequirements(id: number): Promise<MatchResult> {
  const body = await apiRequest("POST", `/api/applications/${id}/matches`, "매칭하지 못했어요. 잠시 뒤 [매칭 다시]를 눌러 주세요.");
  if (
    !isObject(body) ||
    typeof body.matches !== "number" ||
    typeof body.matched_requirements !== "number" ||
    typeof body.requirements_sent !== "number" ||
    typeof body.remaining_today !== "number"
  ) {
    throw new ApiRequestError(BAD_RESPONSE);
  }
  return {
    matches: body.matches,
    matchedRequirements: body.matched_requirements,
    requirementsSent: body.requirements_sent,
    remainingToday: body.remaining_today,
  };
}
