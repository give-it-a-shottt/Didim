import { Suspense } from "react";
import type { Metadata } from "next";
import { AppSidebar } from "@/components/app-sidebar";
import { MemberAuthGuard } from "@/components/member-auth-guard";
import { QueryProvider } from "@/components/query-provider";
import { MEMBER_ROBOTS } from "@/lib/site";

// 회원 화면은 개인 기록이라 검색 결과에 올리지 않는다(이유는 site.ts MEMBER_ROBOTS 주석).
export const metadata: Metadata = {
  robots: MEMBER_ROBOTS,
};

// 회원 화면 공통 레이아웃: 왼쪽 메뉴 + 본문.
// Next.js 16 cacheComponents 규칙에 따라 세션 쿠키 확인(MemberAuthGuard)은 Suspense 안에서 수행한다.
// QueryProvider(TanStack Query, D-012)는 사이드바까지 감싼다 — 사이드바의 [기록 추가] 모달이 노션 페이지 목록을
// useQuery로 받기 때문(F-005). 서버 컴포넌트는 children으로 넘어가 그대로 서버에서 그려진다.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <QueryProvider>
      <div className="flex min-h-screen bg-bg-light text-text-main">
        <AppSidebar />
        {/* min-w-0: 본문의 긴 글이 사이드바를 밀어내지 않게 */}
        <main className="min-w-0 flex-1">
          <Suspense
            fallback={
              <div className="p-12 text-body-2 text-text-sub" role="status">
                계정 정보를 확인하고 있어요…
              </div>
            }
          >
            <MemberAuthGuard>{children}</MemberAuthGuard>
          </Suspense>
        </main>
      </div>
    </QueryProvider>
  );
}
