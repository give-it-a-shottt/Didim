import { Suspense } from "react";
import type { Metadata } from "next";
import { AppSidebar } from "@/components/app-sidebar";
import { MemberAuthGuard } from "@/components/member-auth-guard";
import { MEMBER_ROBOTS } from "@/lib/site";

// 회원 화면은 개인 기록이라 검색 결과에 올리지 않는다(이유는 site.ts MEMBER_ROBOTS 주석).
export const metadata: Metadata = {
  robots: MEMBER_ROBOTS,
};

// 회원 화면 공통 레이아웃: 왼쪽 메뉴 + 본문.
// Next.js 16 cacheComponents 규칙에 따라 세션 쿠키 확인(MemberAuthGuard)은 Suspense 안에서 수행한다.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen bg-[#FAFAFA] text-[#111111]">
      <AppSidebar />
      <main className="flex-1">
        <Suspense
          fallback={
            <div className="p-12 text-[14px] text-[#424242]" role="status">
              계정 정보를 확인하고 있어요…
            </div>
          }
        >
          <MemberAuthGuard>{children}</MemberAuthGuard>
        </Suspense>
      </main>
    </div>
  );
}
