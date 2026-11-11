import type { Metadata } from "next";
import Link from "next/link";
import { CardReviewButton } from "@/components/card-review-sheet";
import { CardTile } from "@/components/card-tile";
import { AddRecordButton } from "@/components/import-records-dialog";
import { EmptyState, PageBody, PageHeader } from "@/components/page-parts";
import { getCardList } from "@/lib/cards-data";
import { FOCUS_RING, PRIMARY_BUTTON } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "경험 카드",
  description: "노트에서 뽑은 경험을 상황 · 과제 · 행동 · 결과 카드로 모아 봐요.",
};

// CRD_01_001 경험 카드 목록(Figma 27:692) + CRD_01_900 빈 상태(27:1121).
// 탭: 내 카드(저장한 카드) · 후보(검토 전). ?tab=candidate 이면 후보 탭 — 주소로 둬서 새로 고쳐도 그대로다.
// Figma와 다르게 둔 것(데이터 · 기능 없음): [카드 만들기](카드는 후보에서만 생김 — 사용자 확인), '근거 1개 이하' · '노트에서' 필터.
// 머리 설명의 완성 · 빈칸 수는 목록에 실린 카드(서버 상한 MAX_CARD_LIST)로 센다.
type Tab = "saved" | "candidate";

const TAB_CLASS = `inline-flex h-8 items-center rounded-tag border px-3 text-body-3 font-medium ${FOCUS_RING}`;
const TAB_ON = "border-primary-default bg-primary-soft text-primary-text";
const TAB_OFF = "border-line-regular bg-bg-default text-text-main hover:bg-bg-hover";

export default async function Crd01001Page(props: PageProps<"/cards">) {
  const { tab: tabParam } = await props.searchParams;
  const tab: Tab = tabParam === "candidate" ? "candidate" : "saved";
  const [saved, candidates] = await Promise.all([getCardList("saved"), getCardList("candidate")]);

  if (saved.status === "error" || candidates.status === "error") {
    return (
      <section data-screen-id="CRD_01_001" aria-labelledby="cards-title">
        <PageHeader titleId="cards-title" title="경험 카드" />
        <PageBody>
          <p role="alert" className="text-body-2 font-medium text-error-text">
            경험 카드를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
          </p>
        </PageBody>
      </section>
    );
  }

  const isEmpty = saved.total === 0 && candidates.total === 0;
  const complete = saved.cards.filter((card) => card.blankCount === 0).length;
  const withBlanks = saved.cards.length - complete;
  const shown = tab === "saved" ? saved : candidates;

  return (
    <section data-screen-id={isEmpty ? "CRD_01_900" : "CRD_01_001"} aria-labelledby="cards-title">
      <PageHeader
        titleId="cards-title"
        title="경험 카드"
        description={
          isEmpty
            ? "카드는 내 기록에서만 만들어요."
            : `완성 ${complete}장 · 빈칸 있음 ${withBlanks}장 · 카드는 내 기록에서만 만들어요.`
        }
      />
      <PageBody>
        {isEmpty ? (
          <EmptyState
            screenId="CRD_01_900"
            title="노트를 올리면 카드 후보를 뽑아 드려요"
            description="노트 상세에서 [카드 후보 찾기]를 누르면 상황 · 과제 · 행동 · 결과를 원문에서 찾아 후보로 보여 드려요."
            action={<AddRecordButton variant="primary" />}
          />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <nav aria-label="카드 종류" className="flex flex-wrap gap-2">
                <Link
                  href="/cards"
                  aria-current={tab === "saved" ? "page" : undefined}
                  className={`${TAB_CLASS} ${tab === "saved" ? TAB_ON : TAB_OFF}`}
                >
                  내 카드 {saved.total}
                </Link>
                <Link
                  href="/cards?tab=candidate"
                  aria-current={tab === "candidate" ? "page" : undefined}
                  className={`${TAB_CLASS} ${tab === "candidate" ? TAB_ON : TAB_OFF}`}
                >
                  검토할 후보 {candidates.total}
                </Link>
              </nav>
              <div className="flex-1" />
              {tab === "candidate" && candidates.cards.length > 0 ? (
                <CardReviewButton
                  cardIds={candidates.cards.map((card) => card.id)}
                  label={`후보 ${candidates.cards.length}개 검토`}
                  className={PRIMARY_BUTTON}
                />
              ) : null}
            </div>

            {shown.cards.length === 0 ? (
              <p role="status" className="text-body-2 text-text-sub">
                {tab === "saved"
                  ? "저장한 카드가 아직 없어요. 검토할 후보 탭에서 후보를 카드로 저장해요."
                  : "검토할 후보가 없어요. 노트 상세에서 [카드 후보 찾기]를 누르면 생겨요."}
              </p>
            ) : (
              <ul
                aria-label={tab === "saved" ? "내 카드" : "검토할 후보"}
                className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4"
              >
                {shown.cards.map((card) => (
                  <CardTile key={card.id} card={card} />
                ))}
              </ul>
            )}
          </>
        )}
      </PageBody>
    </section>
  );
}
