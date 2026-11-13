import { type ApplicationStatus, D_DAY_URGENT_DAYS, STATUS_LABELS, dDayLabel } from "@/lib/applications";
import { BADGE_LINE, BADGE_SHAPE, BADGE_SOFT } from "@/lib/ui-classes";

// 지원 화면(APL_01_001 목록 · APL_02_001 머리)이 같이 쓰는 배지.

// 상태 배지(Figma APL_01_001): 준비 = Soft, 작성 중 = Line, 제출 = Solid(강조는 Solid 하나만 — Badge 설명).
// Solid 바탕은 Figma badge/black/solid(#212121) — 같은 값인 badge-black-text 토큰을 쓴다.
const STATUS_BADGE: Record<ApplicationStatus, string> = {
  ready: BADGE_SOFT,
  writing: BADGE_LINE,
  submitted: `${BADGE_SHAPE} bg-badge-black-text text-text-on-primary`,
};

export function StatusBadge({ status }: { status: ApplicationStatus }) {
  return <span className={STATUS_BADGE[status]}>{STATUS_LABELS[status]}</span>;
}

/** D-day(Figma Didim/D-day 15:397): 마감 임박(D-7 이하)만 코랄 배지, 나머지는 글자만. 마감일이 없으면 그리지 않는다. */
export function DDay({ daysLeft }: { daysLeft: number | null }) {
  const label = dDayLabel(daysLeft);
  if (label === null || daysLeft === null) return null;
  if (daysLeft >= 0 && daysLeft <= D_DAY_URGENT_DAYS) {
    return (
      <span className={`${BADGE_SHAPE} bg-sub1-soft text-sub1-text`}>
        {label}
      </span>
    );
  }
  return <span className="shrink-0 whitespace-nowrap text-body-3 text-text-sub">{label}</span>;
}
