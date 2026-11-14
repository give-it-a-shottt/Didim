// 여러 화면에서 같이 쓰는 버튼 · 링크 모양. 값은 globals.css 토큰 이름만 쓴다(설계 원칙 7).
// 원본은 Figma 디딤 파일 '디딤 공통 컴포넌트 > 버튼'(15:200). Figma와 다르면 Figma가 원본(사용자, 2026-11-11).
// 버튼 크기: M 40(글자 15 SemiBold, 좌우 16, 아이콘 20 · 간격 6) / S 32(글자 14 Medium, 좌우 12, 아이콘 16 · 간격 4) / L 48(글자 16, 좌우 20).
// 한 영역에 주 행동(Primary)은 1개. 나머지는 Outline · Ghost.

// Focus = 2px 링(바탕과 2px 띄움). Figma: 0 0 0 2px bg/default, 0 0 0 4px primary/default
export const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-default";

const BUTTON_BASE = `inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-button disabled:cursor-not-allowed ${FOCUS_RING}`;
const SIZE_M = "h-10 min-w-18 gap-1.5 px-4 text-body-1 font-semibold";
const SIZE_S = "h-8 min-w-15 gap-1 px-3 text-body-2 font-medium";

// Primary(채움): 저장 · 시작 같은 주 행동. Disabled는 bg/regular + text/disabled
export const PRIMARY_BUTTON = `${BUTTON_BASE} ${SIZE_M} bg-primary-default text-text-on-primary hover:bg-primary-hover active:bg-primary-pressed disabled:bg-bg-regular disabled:text-text-disabled`;

// Primary S 32: 카드 안 한 줄에 숫자와 나란히 놓는 주 행동(기록 · 복습의 [복습 시작] — 사용자 화면 확인 2026-11-14)
export const PRIMARY_BUTTON_S = `${BUTTON_BASE} ${SIZE_S} bg-primary-default text-text-on-primary hover:bg-primary-hover active:bg-primary-pressed disabled:bg-bg-regular disabled:text-text-disabled`;

// Primary L 48: 집중 모드(퀴즈)의 [다음 문제]처럼 화면의 단 하나뿐인 행동
export const PRIMARY_BUTTON_L = `${BUTTON_BASE} h-12 min-w-20 gap-1.5 px-5 text-title-4 font-semibold bg-primary-default text-text-on-primary hover:bg-primary-hover active:bg-primary-pressed disabled:bg-bg-regular disabled:text-text-disabled`;

// Outline(검정 테두리): 페이지 머리의 [기록 추가] · 보조 행동
const OUTLINE_COLORS = "border border-line-black bg-bg-default text-text-main hover:bg-bg-hover disabled:border-line-regular disabled:text-text-disabled";
export const SECONDARY_BUTTON = `${BUTTON_BASE} ${SIZE_M} ${OUTLINE_COLORS}`;
export const SECONDARY_BUTTON_S = `${BUTTON_BASE} ${SIZE_S} ${OUTLINE_COLORS}`;

// Ghost(테두리 없음): 모달의 [취소], 집중 모드의 [나가기]
const GHOST_COLORS = "text-text-main hover:bg-bg-hover disabled:text-text-disabled";
export const GHOST_BUTTON = `${BUTTON_BASE} ${SIZE_M} ${GHOST_COLORS}`;
export const GHOST_BUTTON_S = `${BUTTON_BASE} ${SIZE_S} ${GHOST_COLORS}`;

// 카드(화면 bg/light 위의 흰 패널) — 1px line/regular, 그림자 없음, radius/card, 안쪽 24
export const CARD = "rounded-card border border-line-regular bg-bg-default p-6";
// 자소서 탭 칸 제목('문항' · '경험 카드' · '검사 · 근거') — 칸 안 항목(14)보다 한 단계 크게 16(사용자 화면 확인 2026-11-14)
export const SECTION_TITLE = "text-title-4 font-semibold text-text-sub";
// 카드 안 작은 제목("오늘 복습" · "해설" · "복습 상태")
export const CARD_LABEL = "text-body-2 font-semibold text-text-sub";
// 목록 한 줄(카드 안) — 위아래 16, 아래 1px line/light
export const LIST_ROW = "flex items-center gap-4 border-b border-line-light py-4";

// 배지 S 20(Figma Badge Black): Soft = 회색 바탕, Line = 흰 바탕 + 테두리. 글자 12 Medium
// 모양만(색 없음) — 지원 화면의 상태 · D-day 배지도 같이 쓴다. pt-0.75: Pretendard 한글이 글자 상자 위쪽에 그려져
// 가운데 정렬만으로는 위로 약 1.5px 치우쳐 보인다(2026-11-13 6배 확대 실측, 사용자 지적) — 위 여백으로 내려 맞춘다.
export const BADGE_SHAPE =
  "inline-flex h-5 shrink-0 items-center justify-center whitespace-nowrap rounded-tag px-1.5 pt-0.75 text-body-4 font-medium";
const BADGE_BASE = `${BADGE_SHAPE} text-badge-black-text`;
export const BADGE_SOFT = `${BADGE_BASE} bg-badge-black-soft`;
export const BADGE_LINE = `${BADGE_BASE} border border-badge-black-line bg-bg-default`;

// 글자 버튼(Figma Button Text · Main · S 13): 밑줄은 Hover에만. 주 색은 쓰지 않는다(콘텐츠 링크와 헷갈리지 않게)
export const TEXT_BUTTON = `inline-flex items-center gap-1 rounded-tag text-body-3 font-medium text-text-main hover:underline ${FOCUS_RING}`;

// 근거 칩(didim-design.md: Badge Line Strong 모양 + 누를 수 있음, 누르는 영역 32, Hover bg/hover, 포커스 링)
// Figma 근거 칩(16:142) 모양은 기록 · 복습 묶음에서 옮긴다.
export const EVIDENCE_CHIP = `inline-flex min-h-8 items-center gap-1 rounded-tag border border-line-black bg-bg-default px-2 text-body-3 font-medium text-text-main hover:bg-bg-hover ${FOCUS_RING}`;
