import type { Metadata } from "next";
import { LogoutButton } from "@/components/logout-button";
import { requireCurrentUser } from "@/lib/auth";

export const metadata: Metadata = {
  title: "설정",
  description: "계정, AI 사용량, 데이터 삭제를 관리해요.",
};

export default async function Set01001Page() {
  const user = await requireCurrentUser();

  return (
    <section
      data-screen-id="SET_01_001"
      className="flex flex-col bg-bg-light text-text-main"
    >
      {/* 페이지 머리 (피그마 SET_01_001 '페이지 머리' 프레임) */}
      <header className="px-6 pt-10 pb-6 md:px-12">
        <h1 className="text-headline-3 font-semibold text-text-main">
          설정
        </h1>
      </header>

      {/* 본문 — 1주차에는 '계정' 칸만 먼저 만든다 (Q-010 사용자 확인) */}
      <div className="px-6 pb-10 md:px-12">
        <section
          aria-labelledby="account-section-heading"
          className="flex max-w-[640px] flex-col gap-1 rounded-card border border-line-regular bg-bg-default p-6"
        >
          <h2
            id="account-section-heading"
            className="text-title-3 font-semibold text-text-main"
          >
            계정
          </h2>

          <div className="flex items-center justify-between gap-4 border-b border-line-light py-4">
            <div className="flex flex-col gap-1">
              <p className="text-body-1 font-medium text-text-main">
                구글 계정으로 로그인 중
              </p>
              <p className="text-body-4 text-text-sub">
                {user.name} · {user.email}
              </p>
            </div>

            <LogoutButton />
          </div>
        </section>
      </div>
    </section>
  );
}
