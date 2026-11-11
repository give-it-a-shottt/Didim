import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CardEditor } from "@/components/card-editor";
import { PageBody, PageHeader } from "@/components/page-parts";
import { getCard } from "@/lib/cards-data";
import { parseDbId } from "@/lib/ids";

export const metadata: Metadata = {
  title: "경험 카드 상세",
  description: "경험 카드의 빈칸을 채우고 근거를 확인해요.",
};

// CRD_01_002 카드 상세 · 편집(Figma 27:892). 카드는 서버 컴포넌트가 받고(D-012), 고치는 일은 CardEditor(클라이언트)가 한다.
export default async function Crd01002Page(props: PageProps<"/cards/[cardId]">) {
  const { cardId } = await props.params;
  const id = parseDbId(cardId);
  if (id === null) {
    notFound();
  }
  const outcome = await getCard(id);
  if (outcome.status === "not-found") {
    notFound();
  }
  if (outcome.status === "error") {
    return (
      <section data-screen-id="CRD_01_002" aria-labelledby="card-title">
        <PageHeader titleId="card-title" title="경험 카드" />
        <PageBody>
          <p role="alert" className="text-body-2 font-medium text-error-text">
            카드를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
          </p>
        </PageBody>
      </section>
    );
  }
  return (
    <article data-screen-id="CRD_01_002" aria-labelledby="card-title">
      <CardEditor key={outcome.card.id} initial={outcome.card} />
    </article>
  );
}
