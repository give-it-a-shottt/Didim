import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { MemberAuthGuard } from "@/components/member-auth-guard";
import { MEMBER_ROBOTS } from "@/lib/site";

// 회원 화면이라 검색 결과에 올리지 않는다(이유는 site.ts MEMBER_ROBOTS 주석).
export const metadata: Metadata = {
  robots: MEMBER_ROBOTS,
};

// 집중 모드(퀴즈): 왼쪽 메뉴를 숨기고 나가기 링크만 둔다.
// Next.js 16 cacheComponents 규칙에 따라 세션 쿠키 확인(MemberAuthGuard)은 Suspense 안에서 수행한다.
export default function FocusLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen flex-col bg-[#FAFAFA] text-[#111111]">
      <header className="p-4">
        <Link href="/records">나가기</Link>
      </header>
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
