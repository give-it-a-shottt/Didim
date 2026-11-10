import Link from "next/link";
import { AddRecordButton } from "@/components/import-records-dialog";

// 회원 화면 공통 왼쪽 메뉴. 메뉴 구성은 IA v2(00~05)를 따른다.
const MENU = [
  { href: "/home", label: "홈" },
  { href: "/records", label: "기록 · 복습" },
  { href: "/cards", label: "경험 카드" },
  { href: "/applications", label: "지원" },
  { href: "/settings", label: "설정" },
] as const;

export function AppSidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col gap-4 border-r p-4">
      <Link href="/home" className="font-semibold">
        디딤
      </Link>
      {/* 기록 추가(IMP_01_001)는 URL 없이 모달로 열린다(F-002). 버튼과 모달만 클라이언트 컴포넌트다. */}
      <AddRecordButton />
      <nav aria-label="메인 메뉴">
        <ul className="flex flex-col gap-1">
          {MENU.map((item) => (
            <li key={item.href}>
              <Link href={item.href} className="block px-3 py-2">
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
