import { notFound } from "next/navigation";
import { Suspense } from "react";
import {
  ApplicationStatusSelect,
  ApplicationTabs,
  DeleteApplicationButton,
} from "@/components/application-header-actions";
import { DDay } from "@/components/application-parts";
import { formatDeadline } from "@/lib/applications";
import { getApplication } from "@/lib/applications-data";
import { parseDbId } from "@/lib/ids";

// APL_02_001 지원 상세(Figma 27:1458 헤더): '회사 · 직무'(h1) + D-day + 마감일 + 상태(줄 끝), 아래 탭 3개 + 공고 지우기(줄 끝).
// 상태 · 지우기 자리는 사용자 확인(2026-11-13) — Figma 머리에는 없는 동작이라 Figma와 다르다.
// 탭마다 URL이 달라서 새로고침하거나 링크를 보내도 같은 탭이 열린다. 탭 화면의 제목은 h2(화면마다 h1 하나).
export default function ApplicationLayout({ children, params }: LayoutProps<"/applications/[id]">) {
  return (
    <div>
      {/* cacheComponents에서는 URL 값(params) · 쿠키를 Suspense 안에서만 읽을 수 있다. */}
      <Suspense fallback={<div className="h-22 border-b border-line-regular bg-bg-default" />}>
        <ApplicationHeader params={params} />
      </Suspense>
      {children}
    </div>
  );
}

async function ApplicationHeader({ params }: { params: Promise<{ id: string }> }) {
  const { id: rawId } = await params;
  const id = parseDbId(rawId);
  if (id === null) notFound();
  const outcome = await getApplication(id);
  if (outcome.status === "not-found") notFound();

  return (
    <header className="border-b border-line-regular bg-bg-default">
      <div className="flex flex-wrap items-center gap-3 px-5 pt-4 pb-2 lg:px-12">
        {outcome.status === "ok" ? (
          <>
            <h1 className="min-w-0 text-title-3 font-semibold wrap-break-word text-text-main">
              {outcome.application.company} · {outcome.application.role}
            </h1>
            <DDay daysLeft={outcome.application.daysLeft} />
            {outcome.application.deadline ? (
              <p className="text-body-3 text-text-sub">마감 {formatDeadline(outcome.application.deadline)}</p>
            ) : null}
            {outcome.application.url ? (
              <a
                href={outcome.application.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-body-3 text-text-sub underline"
              >
                공고 링크
              </a>
            ) : null}
            <div className="flex-1" />
            <ApplicationStatusSelect applicationId={id} status={outcome.application.status} />
          </>
        ) : (
          <h1 className="text-title-3 font-semibold text-text-main">지원 상세</h1>
        )}
      </div>
      <div className="flex items-center gap-3 px-5 lg:px-12">
        <ApplicationTabs applicationId={id} />
        <div className="flex-1" />
        {outcome.status === "ok" ? <DeleteApplicationButton applicationId={id} /> : null}
      </div>
    </header>
  );
}
