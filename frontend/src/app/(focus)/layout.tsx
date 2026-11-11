import { Suspense } from "react";
import type { Metadata } from "next";
import { MemberAuthGuard } from "@/components/member-auth-guard";
import { QueryProvider } from "@/components/query-provider";
import { MEMBER_ROBOTS } from "@/lib/site";

// 회원 화면이라 검색 결과에 올리지 않는다(이유는 site.ts MEMBER_ROBOTS 주석).
export const metadata: Metadata = {
  robots: MEMBER_ROBOTS,
};

// 집중 모드(퀴즈): 왼쪽 메뉴를 숨긴다. 위쪽 띠([나가기] · 제목 · 진행)는 문제를 아는 화면이 FocusTopBar로 그린다.
// Next.js 16 cacheComponents 규칙에 따라 세션 쿠키 확인(MemberAuthGuard)은 Suspense 안에서 수행한다.
export default function FocusLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen flex-col bg-bg-light text-text-main">
      <main className="flex-1">
        <Suspense
          fallback={
            <div className="p-12 text-body-2 text-text-sub" role="status">
              계정 정보를 확인하고 있어요…
            </div>
          }
        >
          <MemberAuthGuard>
            {/* 답 제출 · 문제 만들기(TanStack Query, D-012)를 쓰는 화면이 이 아래에 있다 */}
            <QueryProvider>{children}</QueryProvider>
          </MemberAuthGuard>
        </Suspense>
      </main>
    </div>
  );
}
