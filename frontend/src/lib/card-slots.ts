// 경험 카드의 네 칸(상황 · 과제 · 행동 · 결과). 카드(lib/cards.ts)와 면접 질문(lib/interview.ts)이 같이 쓴다 —
// 두 모듈이 서로 가져다 쓰지 않게(순환 import) 칸 이름만 여기 둔다(F-009 1차 리뷰 R1).

export const CARD_SLOTS = ["situation", "task", "action", "result"] as const;
export type CardSlot = (typeof CARD_SLOTS)[number];

export const SLOT_LABELS: Record<CardSlot, string> = {
  situation: "상황",
  task: "과제",
  action: "행동",
  result: "결과",
};

export function isCardSlot(value: unknown): value is CardSlot {
  return typeof value === "string" && (CARD_SLOTS as readonly string[]).includes(value);
}
