import Link from "next/link";
import { AddRecordButton } from "@/components/import-records-dialog";
import { SidebarNav, SidebarTooltip } from "@/components/sidebar-nav";
import { SidebarToggle } from "@/components/sidebar-toggle";
import { FOCUS_RING } from "@/lib/ui-classes";

// 회원 화면 공통 왼쪽 메뉴(Figma Didim/사이드바 17:324).
// 펼침 240 / 접힘 56. PC(lg 이상)는 펼침, 좁은 화면은 접힘(모바일 = PC 기준 + 안 깨지게, 사용자 2026-11-11).
// PC에서는 [사이드바 접기]로 접을 수 있다 — 상태는 <html> 속성 하나(sidebar-toggle.tsx · lib/sidebar-state.ts, 사용자 요청 2026-11-16).
// 자소서 탭(F-008)처럼 data-collapse-sidebar를 그린 화면은 넓어도 접힌다 — 그래서 lg: 대신 sidebar-open: 변형(globals.css)을 쓴다.
// 스크롤해도 왼쪽에 붙어 있다(sticky). 로고 마크만 primary/accent(큰 장식 면).
export function AppSidebar() {
  return (
    <aside className="sticky top-0 flex h-screen w-14 shrink-0 flex-col rounded-r-sheet border-r border-line-regular bg-bg-light shadow-sidebar sidebar-open:w-60">
      {/* 펼침: 로고 왼쪽 · [사이드바 접기] 오른쪽 한 줄 / 접힘: 로고 아래에 [사이드바 펼치기](버튼이 보일 때만) */}
      <div className="flex min-h-16 shrink-0 flex-col items-center justify-center gap-2 py-4 sidebar-open:flex-row sidebar-open:justify-between sidebar-open:py-0 sidebar-open:pr-3 sidebar-open:pl-5">
        <Link href="/home" className={`flex items-center gap-2 rounded-button ${FOCUS_RING}`}>
          {/* 로고 마크: 모서리가 왼쪽 위 · 오른쪽 아래 8, 나머지 6 */}
          <span aria-hidden="true" className="size-6 rounded-tl-button rounded-tr-tag rounded-br-button rounded-bl-tag bg-primary-accent" />
          <span className="sr-only text-title-1 font-semibold text-text-main sidebar-open:not-sr-only">디딤</span>
        </Link>
        <SidebarToggle />
      </div>

      <div className="flex flex-col gap-1 px-2 sidebar-open:px-4">
        {/* 기록 추가(IMP_01_001)는 URL 없이 모달로 열린다(F-002). 버튼과 모달만 클라이언트 컴포넌트다. */}
        <div className="group relative">
          <AddRecordButton />
          <SidebarTooltip label="기록 추가" />
        </div>
        <div aria-hidden="true" className="h-3" />
        <SidebarNav />
      </div>

      <div className="flex-1" />

      <div className="group relative flex justify-center py-4 sidebar-open:justify-start sidebar-open:pl-5">
        {/* 계정 정보 · 로그아웃은 설정 화면에 있다 */}
        <Link href="/settings" className={`flex items-center gap-2 rounded-button ${FOCUS_RING}`}>
          <span
            aria-hidden="true"
            className="flex size-8 items-center justify-center rounded-full bg-primary-soft text-body-3 font-semibold text-primary-text"
          >
            나
          </span>
          <span className="sr-only text-body-2 font-medium text-text-sub sidebar-open:not-sr-only">내 계정</span>
        </Link>
        <SidebarTooltip label="내 계정" />
      </div>
    </aside>
  );
}
