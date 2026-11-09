import type { Metadata } from "next";
import { AppSidebar } from "@/components/app-sidebar";
import { MEMBER_ROBOTS } from "@/lib/site";

// 회원 화면은 개인 기록이라 검색 결과에 올리지 않는다(이유는 site.ts MEMBER_ROBOTS 주석).
export const metadata: Metadata = {
  robots: MEMBER_ROBOTS,
};

// 회원 화면 공통 레이아웃: 왼쪽 메뉴 + 본문. 로그인 확인은 F-001에서 붙인다.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex-1">{children}</main>
    </div>
  );
}
