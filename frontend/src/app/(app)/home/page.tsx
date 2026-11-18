import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { DDay } from "@/components/application-parts";
import { Icon } from "@/components/icon";
import { AddRecordButton } from "@/components/import-records-dialog";
import { PageBody, PageHeader } from "@/components/page-parts";
import { applicationHref } from "@/lib/applications";
import { SLOT_LABELS, cardHref } from "@/lib/cards";
import { type Home, type HomeSteps, checklist } from "@/lib/home";
import { getHome } from "@/lib/home-data";
import { CARD, CARD_LABEL, FOCUS_RING, PRIMARY_BUTTON_S, SECONDARY_BUTTON_S, TEXT_BUTTON } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "홈",
  description: "오늘 복습할 문제, 마감이 다가오는 지원, 빈칸이 남은 경험 카드를 한눈에 봐요.",
};

// HOM_01_001 대시보드 · HOM_01_900 첫 방문(F-012, 설계 의도 사용자 확인 2026-11-18). 수치는 GET /api/home 한 번.
// 맨 위 단계 띠(기록 → 복습 → 카드 → 공고 → 자소서 · 면접), 세 단계를 다 끝내기 전까지는 첫 방문 체크리스트 +
// [샘플로 체험하기]를 대시보드 위에 함께 보이고, 아래는 대시보드 세 칸. 체크 여부는 개수로만 판단(저장하는 것 없음).
export default function Hom01001Page() {
  return (
    <section data-screen-id="HOM_01_001" aria-labelledby="home-title">
      <PageHeader titleId="home-title" title="홈" description="오늘 할 일과 지금까지의 흐름을 한눈에 봐요." />
      <PageBody>
        <Suspense
          fallback={
            <p role="status" className="text-body-2 text-text-sub">
              홈을 불러오고 있어요…
            </p>
          }
        >
          <HomeBody />
        </Suspense>
      </PageBody>
    </section>
  );
}

async function HomeBody() {
  const outcome = await getHome();
  if (outcome.status === "error") {
    return (
      <p role="alert" className="text-body-2 font-medium text-error-text">
        홈을 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
      </p>
    );
  }
  const { home } = outcome;
  const progress = checklist(home.steps);
  return (
    <>
      <StepBand steps={home.steps} />
      {progress.allDone ? null : <FirstVisit progress={progress} />}
      <Dashboard home={home} />
    </>
  );
}

const STEPS: { key: keyof HomeSteps; label: string; unit: string; href: string }[] = [
  { key: "notes", label: "기록", unit: "개", href: "/records" },
  { key: "reviewsToday", label: "오늘 복습", unit: "문제", href: "/records" },
  { key: "cards", label: "경험 카드", unit: "장", href: "/cards" },
  { key: "applications", label: "공고", unit: "개", href: "/applications" },
  { key: "draftedApplications", label: "자소서 · 면접", unit: "곳", href: "/applications" },
];

/** 단계 띠: 기록 → 복습 → 카드 → 공고 → 자소서 · 면접이 이어진다는 것을 내 개수와 함께(완료 기준 4). */
function StepBand({ steps }: { steps: HomeSteps }) {
  return (
    <nav aria-label="디딤 흐름">
      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {STEPS.map((step, index) => (
          <li key={step.key} className="flex min-w-0 items-center gap-2">
            <Link
              href={step.href}
              className={`flex min-w-0 flex-1 flex-col gap-1 rounded-card border border-line-regular bg-bg-default px-4 py-3 hover:bg-bg-hover ${FOCUS_RING}`}
            >
              <span className="text-body-3 text-text-sub">
                {index + 1}. {step.label}
              </span>
              <span className="text-title-3 font-semibold text-text-main">
                {steps[step.key]}
                <span className="text-body-3 font-normal text-text-sub"> {step.unit}</span>
              </span>
            </Link>
            {index < STEPS.length - 1 ? (
              <span aria-hidden="true" className="hidden text-text-sub-weak sm:inline">
                →
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** HOM_01_900 첫 방문 체크리스트 + [샘플로 체험하기](체크리스트가 보이는 동안만 — D-029: 누르면 내 로그인이 풀림). */
function FirstVisit({ progress }: { progress: ReturnType<typeof checklist> }) {
  const items = [
    {
      done: progress.record,
      title: "첫 기록 올리기",
      hint: "공부한 마크다운 노트나 노션 페이지를 가져와요.",
      action: <AddRecordButton variant="outline" />,
    },
    {
      done: progress.card,
      title: "경험 카드 1장 만들기",
      hint: "노트에서 카드 후보를 찾아 저장해요.",
      action: (
        <Link href="/records" className={SECONDARY_BUTTON_S}>
          노트 보러 가기
        </Link>
      ),
    },
    {
      done: progress.application,
      title: "공고 1개 추가하기",
      hint: "공고 본문을 붙여 넣으면 맞는 카드를 근거와 함께 찾아 드려요.",
      action: (
        <Link href="/applications" className={SECONDARY_BUTTON_S}>
          공고 추가하러 가기
        </Link>
      ),
    },
  ];
  return (
    <section data-screen-id="HOM_01_900" aria-labelledby="first-visit-title" className={`flex flex-col gap-4 ${CARD}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-1 basis-64 flex-col gap-1">
          <h2 id="first-visit-title" className="text-title-3 font-semibold text-text-main">
            처음이라면 이렇게 시작해요
          </h2>
          <p className="text-body-2 text-text-sub">세 단계를 마치면 이 안내는 사라져요.</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Link href="/demo" className={TEXT_BUTTON}>
            샘플로 체험하기
          </Link>
          <p className="text-body-4 text-text-sub">가상 지원자 기록으로 둘러봐요. 체험을 시작하면 지금 로그인은 풀려요.</p>
        </div>
      </div>
      <ol className="flex flex-col">
        {items.map((item, index) => (
          <li key={item.title} className="flex flex-wrap items-center gap-4 border-b border-line-light py-4 last:border-b-0">
            <span
              aria-hidden="true"
              className={`flex size-7 shrink-0 items-center justify-center rounded-full text-body-3 font-semibold ${
                item.done ? "bg-primary-soft text-primary-text" : "border border-line-regular text-text-sub"
              }`}
            >
              {item.done ? <Icon name="check" size={16} /> : index + 1}
            </span>
            <div className="flex min-w-0 flex-1 basis-48 flex-col gap-1">
              <p className="text-body-1 font-medium text-text-main">
                {item.title}
                <span className="sr-only">{item.done ? " — 끝냄" : " — 아직"}</span>
              </p>
              <p className="text-body-3 text-text-sub">{item.hint}</p>
            </div>
            {item.done ? <span className="text-body-3 text-text-sub">끝냈어요</span> : item.action}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** HOM_01_001 대시보드 세 칸: 오늘 복습 · 마감이 다가온 지원(deadlineDays일 안 · 제출 전) · 빈칸 있는 카드(각 최대 4). */
function Dashboard({ home }: { home: Home }) {
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <section aria-labelledby="today-review-title" className={`flex flex-col gap-3 ${CARD}`}>
        <h2 id="today-review-title" className={CARD_LABEL}>
          오늘 복습
        </h2>
        {home.steps.reviewsToday > 0 ? (
          <>
            <p className="text-title-2 font-semibold text-text-main">
              {home.steps.reviewsToday}
              <span className="text-body-2 font-normal text-text-sub"> 문제</span>
            </p>
            <Link href="/quiz/today" className={`self-start ${PRIMARY_BUTTON_S}`}>
              복습 시작
            </Link>
          </>
        ) : (
          <p className="text-body-2 text-text-sub">오늘은 복습할 문제가 없어요.</p>
        )}
      </section>

      <section aria-labelledby="deadline-title" className={`flex flex-col gap-3 ${CARD}`}>
        <h2 id="deadline-title" className={CARD_LABEL}>
          마감이 다가온 지원
        </h2>
        {home.deadlines.length > 0 ? (
          <ul className="flex flex-col">
            {home.deadlines.map((item) => (
              <li key={item.id} className="border-b border-line-light last:border-b-0">
                <Link href={applicationHref(item.id)} className={`flex items-center gap-3 py-2 hover:underline ${FOCUS_RING}`}>
                  <DDay daysLeft={item.daysLeft} />
                  <span className="min-w-0 flex-1 truncate text-body-2 text-text-main">
                    {item.company} · {item.role}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-body-2 text-text-sub">{home.deadlineDays}일 안에 마감인 지원이 없어요.</p>
        )}
      </section>

      <section aria-labelledby="blank-card-title" className={`flex flex-col gap-3 ${CARD}`}>
        <h2 id="blank-card-title" className={CARD_LABEL}>
          빈칸 있는 카드
        </h2>
        {home.blankCards.length > 0 ? (
          <ul className="flex flex-col">
            {home.blankCards.map((card) => (
              <li key={card.id} className="border-b border-line-light last:border-b-0">
                <Link href={cardHref(card.id)} className={`flex flex-col gap-0.5 py-2 hover:underline ${FOCUS_RING}`}>
                  <span className="truncate text-body-2 text-text-main">{card.title}</span>
                  <span className="text-body-4 text-text-sub">
                    빈칸: {card.blankSlots.map((slot) => SLOT_LABELS[slot]).join(" · ")}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-body-2 text-text-sub">빈칸이 남은 카드가 없어요.</p>
        )}
      </section>
    </div>
  );
}
