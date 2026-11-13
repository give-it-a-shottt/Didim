import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PostingAnalysis } from "@/components/posting-analysis";
import { getApplication } from "@/lib/applications-data";
import { parseDbId } from "@/lib/ids";

export const metadata: Metadata = {
  title: "공고 분석",
  description: "공고의 요구 역량과 내 경험 카드를 맞춰 봐요.",
};

// APL_02_002 공고 분석 탭. 공고 · 역량 · 매칭은 서버 컴포넌트가 받고(D-012), 분석 실행은 PostingAnalysis(클라이언트)가 한다.
// ?analyze=1 = 공고 추가 모달에서 막 왔음 → 역량 뽑기를 바로 시작한다. 머리(h1)는 layout에 있어 여기 제목은 h2.
export default async function Apl02002Page(props: PageProps<"/applications/[id]/analysis">) {
  const [{ id: rawId }, { analyze }] = await Promise.all([props.params, props.searchParams]);
  const id = parseDbId(rawId);
  if (id === null) notFound();
  const outcome = await getApplication(id);
  if (outcome.status === "not-found") notFound();
  if (outcome.status === "error") {
    return (
      <section data-screen-id="APL_02_002" aria-labelledby="analysis-error-title" className="px-5 py-6 lg:px-12">
        <h2 id="analysis-error-title" className="sr-only">
          공고 분석
        </h2>
        <p role="alert" className="text-body-2 font-medium text-error-text">
          공고를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      </section>
    );
  }
  return (
    <section data-screen-id="APL_02_002" aria-label="공고 분석">
      <PostingAnalysis application={outcome.application} autoStart={analyze === "1"} />
    </section>
  );
}
