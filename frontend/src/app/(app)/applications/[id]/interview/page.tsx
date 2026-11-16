import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { InterviewWorkspace } from "@/components/interview-workspace";
import { parseDbId } from "@/lib/ids";
import { getApplicationInterview } from "@/lib/interview-data";

export const metadata: Metadata = {
  title: "면접 연습",
  description: "매칭된 경험 카드에서 나온 면접 질문을 모아 봐요.",
};

// APL_02_004 면접 연습 탭(Figma 27:1586). 매칭된 카드별 질문은 서버 컴포넌트가 받고(D-012), 메모는 InterviewWorkspace(클라이언트)가 저장한다.
// 머리(h1)는 layout에 있어 여기 제목은 h2. 데이터는 Suspense 안에서 받는다(탭끼리 옮길 때 머리는 그대로 — 자소서 탭과 같음).
export default function Apl02004Page(props: PageProps<"/applications/[id]/interview">) {
  return (
    <section data-screen-id="APL_02_004" aria-label="면접 연습">
      <Suspense
        fallback={
          <p role="status" className="px-5 py-6 text-body-2 text-text-sub lg:px-12">
            면접 질문을 불러오고 있어요…
          </p>
        }
      >
        <InterviewContent params={props.params} />
      </Suspense>
    </section>
  );
}

async function InterviewContent({ params }: { params: Promise<{ id: string }> }) {
  const { id: rawId } = await params;
  const id = parseDbId(rawId);
  if (id === null) notFound();
  const outcome = await getApplicationInterview(id);
  if (outcome.status === "not-found") notFound();
  if (outcome.status === "error") {
    return (
      <div className="px-5 py-6 lg:px-12">
        <h2 className="sr-only">면접 연습</h2>
        <p role="alert" className="text-body-2 font-medium text-error-text">
          면접 질문을 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      </div>
    );
  }
  return <InterviewWorkspace initial={outcome.interview} />;
}
