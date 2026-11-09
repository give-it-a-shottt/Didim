import Link from "next/link";
import { Suspense } from "react";

// APL_02_001 지원 상세: 탭 3개(공고 분석 · 자소서 · 면접 연습)를 담는 틀.
// 탭마다 URL이 달라서 새로고침하거나 링크를 보내도 같은 탭이 열린다.
export default function ApplicationLayout({
  children,
  params,
}: LayoutProps<"/applications/[id]">) {
  return (
    <div>
      <header className="p-8 pb-0">
        <p className="text-sm">APL_02_001</p>
        <h1 className="text-2xl font-semibold">지원 상세</h1>
        {/* cacheComponents에서는 URL 값(params)을 Suspense 안에서만 읽을 수 있다. */}
        <Suspense fallback={null}>
          <ApplicationTabs params={params} />
        </Suspense>
      </header>
      {children}
    </div>
  );
}

const TABS = [
  { segment: "analysis", label: "공고 분석" },
  { segment: "draft", label: "자소서" },
  { segment: "interview", label: "면접 연습" },
] as const;

async function ApplicationTabs({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <nav aria-label="지원 상세 탭" className="mt-4 flex gap-4">
      {TABS.map((tab) => (
        <Link key={tab.segment} href={`/applications/${encodeURIComponent(id)}/${tab.segment}`}>
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
