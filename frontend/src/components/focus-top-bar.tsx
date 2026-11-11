import type { ReactNode } from "react";
import Link from "next/link";
import { Icon } from "@/components/icon";
import { GHOST_BUTTON_S } from "@/lib/ui-classes";

// 집중 모드 위쪽 띠(Figma REV_02_001 상단 26:805 + 진행 막대 26:816): 왼쪽 [‹ 나가기] · 오른쪽 "4 / 12", 아래 진행 막대.
// 제목은 띠가 아니라 본문 맨 위에 둔다(Figma 59:1478, 사용자 수정 2026-11-11) → FocusTitle.
// 진행은 문제를 아는 화면이 넘긴다(퀴즈는 QuizRunner, 오류 · 빈 상태는 page.tsx). 훅이 없어 서버 · 클라이언트 어디서나 쓴다.
export function FocusTopBar({
  counter,
  progress,
}: {
  counter?: ReactNode;
  progress?: { current: number; total: number };
}) {
  return (
    <header className="bg-bg-default">
      <div className="flex items-center gap-4 px-5 py-4 lg:px-12">
        <Link href="/records" className={GHOST_BUTTON_S}>
          <Icon name="caret-left" size={16} className="text-icon-main" />
          나가기
        </Link>
        <div className="flex-1" />
        {counter ? <span className="shrink-0 text-body-2 font-semibold text-text-main">{counter}</span> : null}
      </div>
      {/* 진행 막대(Figma Progress Bar): 높이 4, 바탕 line/light, 채움 primary/default. role="progressbar" + aria-valuenow */}
      <div
        role={progress ? "progressbar" : undefined}
        aria-label={progress ? "퀴즈 진행" : undefined}
        aria-valuemin={progress ? 1 : undefined}
        aria-valuemax={progress?.total}
        aria-valuenow={progress?.current}
        aria-valuetext={progress ? `${progress.total}문제 중 ${progress.current}번째` : undefined}
        className="h-1 overflow-hidden bg-line-light"
      >
        {progress ? (
          <div
            className="h-full rounded-xs bg-primary-default"
            style={{ width: `${(progress.current / progress.total) * 100}%` }}
          />
        ) : null}
      </div>
    </header>
  );
}

/** 집중 모드 본문 맨 위 제목(h1, Figma 26:813 — 18 SemiBold, 왼쪽 4 들여씀). */
export function FocusTitle({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h1 id={id} className="pl-1 text-title-3 font-semibold wrap-break-word text-text-main">
      {children}
    </h1>
  );
}
