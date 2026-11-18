import type { ReactNode } from "react";
import { EndSampleButton } from "@/components/sample-session-buttons";
import { requireCurrentUser } from "@/lib/auth";
import { BADGE_SOFT } from "@/lib/ui-classes";

export async function MemberAuthGuard({ children }: { children: ReactNode }) {
  const user = await requireCurrentUser();
  return (
    <>
      {user.isSample ? <SampleBanner /> : null}
      {children}
    </>
  );
}

// 샘플 체험 중임을 모든 회원 화면 위에 알린다(DEM_01_001 '샘플' 배지 · [체험 끝내기], D-029).
function SampleBanner() {
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 border-b border-line-regular bg-bg-default px-5 py-3 lg:px-12"
    >
      <span className={BADGE_SOFT}>샘플</span>
      <p className="min-w-0 flex-1 text-body-3 text-text-sub">
        가상 지원자의 기록을 둘러보는 중이에요. 샘플은 고치거나 AI로 새로 만들 수 없어요.
      </p>
      <EndSampleButton />
    </div>
  );
}
