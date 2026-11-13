import type { Metadata } from "next";
import Link from "next/link";
import { AddApplicationButton } from "@/components/add-application-dialog";
import { DDay, StatusBadge } from "@/components/application-parts";
import { EmptyState, PageBody, PageHeader } from "@/components/page-parts";
import { type ApplicationSummary, applicationHref, formatDeadline } from "@/lib/applications";
import { getApplicationList } from "@/lib/applications-data";
import { CARD, FOCUS_RING } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "지원",
  description: "지원한 공고를 마감일 순으로 봐요.",
};

// APL_01_001 지원 목록(Figma 27:1190). 서버가 D-day 순(마감 남음 → 지남 → 마감일 없음)으로 준다.
// 한 줄 아래 설명은 진행 상황(분석 · 근거 수) + 마감일. Figma의 '문항 · 근거 7/9'는 F-008(자소서) 때 바꾼다.
export default async function Apl01001Page() {
  const outcome = await getApplicationList();

  if (outcome.status === "error") {
    return (
      <section data-screen-id="APL_01_001" aria-labelledby="applications-title">
        <PageHeader titleId="applications-title" title="지원" />
        <PageBody>
          <p role="alert" className="text-body-2 font-medium text-error-text">
            지원 목록을 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
          </p>
        </PageBody>
      </section>
    );
  }

  return (
    <section data-screen-id="APL_01_001" aria-labelledby="applications-title">
      <PageHeader
        titleId="applications-title"
        title="지원"
        description={outcome.total > 0 ? `마감이 가까운 순서 · ${outcome.total}건` : "공고를 붙여 넣으면 맞는 카드를 근거와 함께 찾아 드려요."}
        actions={outcome.total > 0 ? <AddApplicationButton /> : null}
      />
      <PageBody>
        {outcome.total === 0 ? (
          <EmptyState
            title="아직 추가한 공고가 없어요"
            description="공고 본문을 붙여 넣으면 요구 역량을 뽑고, 역량마다 맞는 내 경험 카드를 근거와 함께 이어 드려요."
            action={<AddApplicationButton variant="empty" />}
          />
        ) : (
          <div className={`${CARD} py-2`}>
            <ul aria-label="지원 목록">
              {outcome.applications.map((item) => (
                <ApplicationRow key={item.id} item={item} />
              ))}
            </ul>
          </div>
        )}
      </PageBody>
    </section>
  );
}

function progressText(item: ApplicationSummary): string {
  if (!item.extracted) return "공고 분석 전";
  if (!item.matched) return `요구 역량 ${item.requirementCount}개 · 매칭 전`;
  return `요구 역량 ${item.requirementCount}개 중 ${item.matchedRequirementCount}개에 근거`;
}

function ApplicationRow({ item }: { item: ApplicationSummary }) {
  const deadline = item.deadline ? ` · 마감 ${formatDeadline(item.deadline)}` : "";
  return (
    <li className="border-b border-line-light last:border-b-0">
      <Link
        href={applicationHref(item.id)}
        className={`flex items-center gap-4 rounded-button py-4 hover:bg-bg-hover ${FOCUS_RING}`}
      >
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="truncate text-body-1 font-medium text-text-main">
            {item.company} · {item.role}
          </span>
          <span className="text-body-4 text-text-sub">
            {progressText(item)}
            {deadline}
          </span>
        </span>
        <StatusBadge status={item.status} />
        <DDay daysLeft={item.daysLeft} />
      </Link>
    </li>
  );
}
