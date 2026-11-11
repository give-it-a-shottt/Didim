// 퀴즈 · 복습(F-004) 화면에서 같이 쓰는 버튼 · 링크 모양. 값은 globals.css 토큰 이름만 쓴다(설계 원칙 7).
// 디자인은 나중에 피그마 원본 값으로 옮긴다(사용자, 2026-11-10).

export const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-default";

export const PRIMARY_BUTTON = `inline-flex h-10 items-center justify-center rounded-button bg-primary-default px-4 text-body-2 font-medium text-text-on-primary hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-bg-pressed disabled:text-text-disabled ${FOCUS_RING}`;

export const SECONDARY_BUTTON = `inline-flex h-10 items-center justify-center rounded-button border border-line-regular bg-bg-default px-4 text-body-2 font-medium text-text-main hover:bg-bg-hover disabled:cursor-not-allowed disabled:text-text-disabled ${FOCUS_RING}`;

// 근거 칩(didim-design.md: Badge Line Strong 모양 + 누를 수 있음, 누르는 영역 32, Hover bg/hover, 포커스 링)
export const EVIDENCE_CHIP = `inline-flex min-h-8 items-center gap-1 rounded-tag border border-line-black bg-bg-default px-2 text-body-3 font-medium text-text-main hover:bg-bg-hover ${FOCUS_RING}`;
