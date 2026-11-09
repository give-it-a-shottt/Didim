import type { Metadata } from "next";
import Link from "next/link";
import { MEMBER_ROBOTS } from "@/lib/site";

// 회원 화면이라 검색 결과에 올리지 않는다(이유는 site.ts MEMBER_ROBOTS 주석).
export const metadata: Metadata = {
  robots: MEMBER_ROBOTS,
};

// 집중 모드(퀴즈): 왼쪽 메뉴를 숨기고 나가기 링크만 둔다.
export default function FocusLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="p-4">
        <Link href="/records">나가기</Link>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
