import type { ReactNode } from "react";

// 회원 화면(사이드바 레이아웃) 공통 틀 — Figma REV_01_001 등 '페이지 머리' · '본문'.
// 좌우 마진 PC 48 · 좁은 화면 20(didim-design.md 4장). 페이지 머리는 위 40 · 아래 24.

/** 페이지 머리: 제목(h1, 화면마다 하나) + 한 줄 설명 + 오른쪽 행동 버튼. */
export function PageHeader({
  titleId,
  title,
  description,
  actions,
}: {
  titleId: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end gap-4 px-5 pt-10 pb-6 lg:px-12">
      {/* basis-64: 좁은 화면에서 제목이 버튼에 밀려 한두 글자씩 꺾이지 않게, 이보다 좁아지면 버튼이 아랫줄로 간다 */}
      <div className="flex min-w-0 flex-1 basis-64 flex-col gap-1">
        <h1 id={titleId} className="text-title-1 font-semibold wrap-break-word text-text-main">
          {title}
        </h1>
        {description ? <p className="text-body-2 text-text-sub">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** 본문: 카드들 사이 24, 아래 40. */
export function PageBody({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-6 px-5 pb-10 lg:px-12">{children}</div>;
}

/**
 * 빈 화면(Figma Empty State): 제목 18 SemiBold + 설명 14 + 다음 행동 버튼.
 * "없음"만 말하지 말고 다음 행동을 함께 둔다(Figma 컴포넌트 설명).
 */
export function EmptyState({
  title,
  description,
  action,
  screenId,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  screenId?: string;
}) {
  return (
    <div
      data-screen-id={screenId}
      className="flex min-h-130 flex-col items-center justify-center rounded-card border border-line-regular bg-bg-default px-6 py-12 text-center"
    >
      <p role="status" className="text-title-3 font-semibold text-text-main">
        {title}
      </p>
      {description ? <p className="text-body-2 text-text-sub">{description}</p> : null}
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  );
}

/**
 * 내 기록 원문 인용(Figma Didim/원문 인용 16:186). 이 블록만 명조(설계 원칙 7 — 명조 = 내 기록).
 * 왼쪽 2px line/strong은 장식. 아래 줄에 출처(근거 우선, 원칙 1) — source는 링크여도 된다.
 */
export function SourceQuote({ quote, source }: { quote: string; source: ReactNode }) {
  return (
    <figure className="flex flex-col gap-2 border-l-2 border-line-strong px-3 text-text-sub">
      <blockquote className="font-serif text-quote whitespace-pre-wrap before:content-['「'] after:content-['」']">
        {quote}
      </blockquote>
      <figcaption className="text-body-4">{source}</figcaption>
    </figure>
  );
}
