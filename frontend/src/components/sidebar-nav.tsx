"use client";

// 사이드바 메뉴 목록(Figma Didim/사이드바 메뉴 17:240). 지금 주소에 맞는 메뉴를 고르려고 usePathname을 쓰는 부분만 클라이언트다.
// 펼침(lg 이상) = 아이콘 + 글자, 접힘(lg 미만) = 아이콘만 + 마우스를 올리면 툴팁. 글자는 접혀도 화면 읽기 프로그램에는 남는다(sr-only).

import { Suspense } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "@/components/icon";
import { FOCUS_RING } from "@/lib/ui-classes";

// 메뉴 구성은 IA v2(00~05). match = 이 메뉴가 선택된 것으로 볼 주소 앞부분
const MENU: { href: string; label: string; icon: IconName; match: string[] }[] = [
  { href: "/home", label: "홈", icon: "home", match: ["/home"] },
  // 복습 결과(/quiz/…/result)도 기록 · 복습 흐름이라 같이 표시한다
  { href: "/records", label: "기록 · 복습", icon: "notebook", match: ["/records", "/quiz"] },
  { href: "/cards", label: "경험 카드", icon: "cards", match: ["/cards"] },
  { href: "/applications", label: "지원", icon: "briefcase", match: ["/applications"] },
  { href: "/settings", label: "설정", icon: "settings", match: ["/settings"] },
];

function isCurrent(pathname: string | null, prefixes: string[]) {
  if (pathname === null) return false;
  return prefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

// cacheComponents에서는 주소에 미리 모르는 값이 있는 화면(/applications/[id] 등)이면 usePathname이 미리 그리기를 멈춘다.
// → Suspense로 감싸 미리 그릴 때는 선택 표시 없는 같은 메뉴를 보여 주고, 주소를 알면 선택 표시가 붙는다
//   (node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-pathname.md).
export function SidebarNav() {
  return (
    <Suspense fallback={<SidebarMenu pathname={null} />}>
      <CurrentSidebarMenu />
    </Suspense>
  );
}

function CurrentSidebarMenu() {
  return <SidebarMenu pathname={usePathname()} />;
}

function SidebarMenu({ pathname }: { pathname: string | null }) {
  return (
    <nav aria-label="메인 메뉴">
      <ul className="flex flex-col gap-1">
        {MENU.map((item) => {
          const current = isCurrent(pathname, item.match);
          return (
            <li key={item.href} className="group relative">
              <Link
                href={item.href}
                aria-current={current ? "page" : undefined}
                className={`flex h-10 w-full items-center justify-center gap-3 rounded-button text-body-1 sidebar-open:justify-start sidebar-open:px-3 ${
                  current
                    ? "border-l-2 border-line-black bg-bg-regular font-semibold text-text-main"
                    : "font-medium text-text-sub hover:bg-bg-hover"
                } ${FOCUS_RING}`}
              >
                <Icon name={item.icon} className={current ? "text-text-main" : "text-icon-sub"} />
                <span className="sr-only sidebar-open:not-sr-only sidebar-open:whitespace-nowrap">{item.label}</span>
              </Link>
              <SidebarTooltip label={item.label} />
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

// 접힘(lg 미만)일 때만 보이는 툴팁. 글자는 위 링크에 이미 있어 화면 읽기 프로그램에는 숨긴다.
export function SidebarTooltip({ label }: { label: string }) {
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute top-1/2 left-full z-10 ml-2 hidden -translate-y-1/2 whitespace-nowrap rounded-tag bg-bg-inverse px-2 py-1 text-body-3 text-text-inverse group-hover:block group-has-focus-visible:block sidebar-open:group-hover:hidden sidebar-open:group-has-focus-visible:hidden"
    >
      {label}
    </span>
  );
}
