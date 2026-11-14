import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { DraftWorkspace } from "@/components/draft-workspace";
import { getCardList } from "@/lib/cards-data";
import { getDrafts } from "@/lib/drafts-data";
import { parseDbId } from "@/lib/ids";

export const metadata: Metadata = {
  title: "자소서",
  description: "문장마다 근거가 달린 자소서 초안을 고쳐 써요.",
};

// APL_02_003 자소서 탭(Figma 18:202, 사이드바 접힘). 문항 · 초안 · 근거와 내 저장 카드 목록은 서버 컴포넌트가 받고(D-012),
// 쓰기 · 고치기는 DraftWorkspace(클라이언트)가 한다. 머리(h1)는 layout에 있어 여기 제목은 h2.
// data-collapse-sidebar: 이 화면이 있으면 사이드바가 화면 너비와 상관없이 접힌다(globals.css의 sidebar-open 변형 — 상태 없음).
// 데이터는 Suspense 안에서 받는다 — 탭끼리 옮길 때 머리(layout)는 그대로 두고 이 부분만 기다리게(Next 16 instant navigation).
export default function Apl02003Page(props: PageProps<"/applications/[id]/draft">) {
  return (
    <section data-screen-id="APL_02_003" data-collapse-sidebar aria-label="자소서">
      <Suspense
        fallback={
          <p role="status" className="px-5 py-6 text-body-2 text-text-sub lg:px-12">
            자소서를 불러오고 있어요…
          </p>
        }
      >
        <DraftContent params={props.params} />
      </Suspense>
    </section>
  );
}

async function DraftContent({ params }: { params: Promise<{ id: string }> }) {
  const { id: rawId } = await params;
  const id = parseDbId(rawId);
  if (id === null) notFound();
  const [outcome, cards] = await Promise.all([getDrafts(id), getCardList("saved")]);
  if (outcome.status === "not-found") notFound();
  if (outcome.status === "error") {
    return (
      <div className="px-5 py-6 lg:px-12">
        <h2 className="sr-only">자소서</h2>
        <p role="alert" className="text-body-2 font-medium text-error-text">
          자소서를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      </div>
    );
  }
  return <DraftWorkspace initialDrafts={outcome.drafts} cards={cards.status === "ok" ? cards.cards : null} />;
}
