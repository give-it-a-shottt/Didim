import type { Metadata } from "next";
import { LogoutButton } from "@/components/logout-button";
import { NotionConnectionRow } from "@/components/notion-connection-row";
import { PageBody, PageHeader } from "@/components/page-parts";
import { requireCurrentUser } from "@/lib/auth";
import { connectNotice } from "@/lib/notion-status";
import { getNotionStatus } from "@/lib/notion-data";
import { CARD } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "설정",
  description: "계정, 노션 연결, AI 사용량, 데이터 삭제를 관리해요.",
};

// SET_01_001 설정(Figma 28:1209). '계정' 칸(Q-010)과 '연결' 칸(노션, F-005 — Figma 28:1273)이 있다.
// Figma의 내 데이터 모두 지우기(F-001 7주차) · 오늘 AI 사용량(사용량 화면 7주차)은
// 기능이 생길 때 같이 옮긴다(D-019 — 기능 없는 칸은 그리지 않음).
// 노션 연결을 마치거나 실패하면 서버가 ?notion=connected · ?notion_error=… 로 이 화면에 돌려보낸다(backend/app/api/notion.py).
export default async function Set01001Page(props: PageProps<"/settings">) {
  const [user, query, notionStatus] = await Promise.all([
    requireCurrentUser(),
    props.searchParams,
    getNotionStatus(),
  ]);
  const notion = typeof query.notion === "string" ? query.notion : undefined;
  const notionError = typeof query.notion_error === "string" ? query.notion_error : undefined;
  const notice = connectNotice(notion, notionError);

  return (
    <section data-screen-id="SET_01_001" aria-labelledby="settings-title">
      <PageHeader titleId="settings-title" title="설정" />
      <PageBody>
        <div className="flex max-w-170 flex-col gap-6">
          {/* Figma 왼쪽 열 너비 680 */}
          <section aria-labelledby="account-section-heading" className={`${CARD} flex flex-col gap-1`}>
            <h2 id="account-section-heading" className="text-title-3 font-semibold text-text-main">
              계정
            </h2>

            <div className="flex items-center gap-4 border-b border-line-light py-4">
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <p className="text-body-1 font-medium text-text-main">구글 계정으로 로그인 중</p>
                <p className="truncate text-body-4 text-text-sub">
                  {user.name} · {user.email}
                </p>
              </div>
              <LogoutButton />
            </div>
          </section>

          <section aria-labelledby="connection-section-heading" className={`${CARD} flex flex-col gap-1`}>
            <h2 id="connection-section-heading" className="text-title-3 font-semibold text-text-main">
              연결
            </h2>
            {notice ? (
              <p
                role={notice.ok ? "status" : "alert"}
                className={`text-body-3 font-medium ${notice.ok ? "text-success-text" : "text-error-text"}`}
              >
                {notice.message}
              </p>
            ) : null}
            <NotionConnectionRow status={notionStatus} />
          </section>
        </div>
      </PageBody>
    </section>
  );
}
