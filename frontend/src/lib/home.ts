// 홈(F-012 — HOM_01_900 첫 방문 · HOM_01_001 대시보드) 응답 모양과 표시 규칙. 서버 응답은 backend/app/api/home.py.
import { APPLICATION_STATUSES, type ApplicationStatus } from "@/lib/applications";
import { type CardSlot, isCardSlot } from "@/lib/card-slots";
import { isObject } from "@/lib/json";

export type HomeSteps = {
  notes: number; // 기록 = 노트 수
  reviewsToday: number; // 복습 = 오늘 복습할 문제 수
  cards: number; // 카드 = 저장한 카드 수
  applications: number; // 공고 = 지원 수
  draftedApplications: number; // 자소서 · 면접 = 초안을 쓴 지원 수
};

export type HomeDeadline = {
  id: number;
  company: string;
  role: string;
  deadline: string;
  daysLeft: number;
  status: ApplicationStatus;
};

export type HomeBlankCard = { id: number; title: string; blankSlots: CardSlot[] };

export type Home = {
  steps: HomeSteps;
  deadlineDays: number; // 마감 칸 기준 일수(오늘 포함) — 서버 config.HOME_DEADLINE_DAYS를 그대로 받아 문구에 쓴다
  deadlines: HomeDeadline[];
  blankCards: HomeBlankCard[];
};

/** 첫 방문 체크리스트(사용자 확인 2026-11-18): 노트 · 저장 카드 · 지원이 1개 이상이면 그 단계가 끝. */
export function checklist(steps: HomeSteps): { record: boolean; card: boolean; application: boolean; allDone: boolean } {
  const record = steps.notes > 0;
  const card = steps.cards > 0;
  const application = steps.applications > 0;
  return { record, card, application, allDone: record && card && application };
}

const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0;
const isDate = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);

function toSteps(value: unknown): HomeSteps | null {
  if (
    !isObject(value) ||
    !isCount(value.notes) ||
    !isCount(value.reviews_today) ||
    !isCount(value.cards) ||
    !isCount(value.applications) ||
    !isCount(value.drafted_applications)
  ) {
    return null;
  }
  return {
    notes: value.notes,
    reviewsToday: value.reviews_today,
    cards: value.cards,
    applications: value.applications,
    draftedApplications: value.drafted_applications,
  };
}

function toDeadline(value: unknown): HomeDeadline | null {
  if (
    !isObject(value) ||
    typeof value.id !== "number" ||
    typeof value.company !== "string" ||
    typeof value.role !== "string" ||
    !isDate(value.deadline) ||
    !isCount(value.days_left) || // 지난 마감은 서버가 뺀다 — 0 = 오늘 마감
    typeof value.status !== "string" ||
    !(APPLICATION_STATUSES as readonly string[]).includes(value.status)
  ) {
    return null;
  }
  return {
    id: value.id,
    company: value.company,
    role: value.role,
    deadline: value.deadline,
    daysLeft: value.days_left,
    status: value.status as ApplicationStatus,
  };
}

function toBlankCard(value: unknown): HomeBlankCard | null {
  if (!isObject(value) || typeof value.id !== "number" || typeof value.title !== "string" || !Array.isArray(value.blank_slots)) {
    return null;
  }
  const slots = value.blank_slots.filter(isCardSlot);
  if (slots.length === 0) return null; // 빈칸 이름을 하나도 모르면 "빈칸: "만 남으니 형식 오류로 본다
  return { id: value.id, title: value.title, blankSlots: slots };
}

export function toHome(value: unknown): Home | null {
  if (
    !isObject(value) ||
    !isCount(value.deadline_days) ||
    !Array.isArray(value.deadlines) ||
    !Array.isArray(value.blank_cards)
  ) {
    return null;
  }
  const steps = toSteps(value.steps);
  const deadlines = value.deadlines.map(toDeadline);
  const blankCards = value.blank_cards.map(toBlankCard);
  if (steps === null || deadlines.some((item) => item === null) || blankCards.some((item) => item === null)) return null;
  return {
    steps,
    deadlineDays: value.deadline_days,
    deadlines: deadlines as HomeDeadline[],
    blankCards: blankCards as HomeBlankCard[],
  };
}
