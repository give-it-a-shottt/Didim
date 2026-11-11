import type { Metadata } from "next";
import { LogoutButton } from "@/components/logout-button";
import { PageBody, PageHeader } from "@/components/page-parts";
import { requireCurrentUser } from "@/lib/auth";
import { CARD } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "설정",
  description: "계정, AI 사용량, 데이터 삭제를 관리해요.",
};

// SET_01_001 설정(Figma 28:1209). 지금은 '계정' 칸만 있다(Q-010 사용자 확인).
// Figma의 연결(노션, F-005) · 내 데이터 모두 지우기(F-001 7주차) · 오늘 AI 사용량(사용량 화면 7주차)은
// 기능이 생길 때 같이 옮긴다(D-019 — 기능 없는 칸은 그리지 않음).
export default async function Set01001Page() {
  const user = await requireCurrentUser();

  return (
    <section data-screen-id="SET_01_001" aria-labelledby="settings-title">
      <PageHeader titleId="settings-title" title="설정" />
      <PageBody>
        {/* Figma 왼쪽 열 너비 680 */}
        <section aria-labelledby="account-section-heading" className={`${CARD} flex max-w-170 flex-col gap-1`}>
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
      </PageBody>
    </section>
  );
}
