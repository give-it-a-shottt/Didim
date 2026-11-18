import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { dataSizeItems, formatMetric, runDate, type ReportEval, type ReportRun } from "@/lib/report";
import { getReportRuns } from "@/lib/report-data";
import { CARD, CARD_LABEL, TEXT_BUTTON } from "@/lib/ui-classes";

// SET_02_001 평가 리포트(F-010 완료 기준 3, D-029). 로그인 없이 보는 공개 페이지라 검색에 올린다(sitemap 포함).
// 수치는 backend/eval/summary의 회차 요약(scripts/eval_all.py)을 GET /api/report로 읽는다 — README 표와 같은 파일.
// 요청할 때 읽어서 Suspense로 흘려보낸다(빌드가 백엔드에 기대지 않게, cacheComponents).
export const metadata: Metadata = {
  title: "평가 리포트",
  description:
    "정답을 미리 심어 둔 가상 데이터로, 디딤이 AI가 지어낸 문장 · 질문을 얼마나 잡아내는지 잰 수치예요.",
};

export default function Set02001Page() {
  return (
    <section
      data-screen-id="SET_02_001"
      aria-labelledby="report-title"
      className="min-h-screen bg-bg-light px-5 py-12 text-text-main lg:px-12"
    >
      <div className="mx-auto flex max-w-240 flex-col gap-6">
        <header className="flex flex-col gap-2">
          <h1 id="report-title" className="text-title-1 font-semibold">
            평가 리포트
          </h1>
          <p className="text-body-2 text-text-sub">
            AI가 만든 퀴즈 · 카드 · 매칭 · 자소서 · 면접 질문을 정답을 미리 심어 둔 가상 데이터로 쟀어요. 정답을
            먼저 정하고 글을 썼기 때문에, 채점하는 사람의 판단이 끼어들지 않아요.
          </p>
        </header>
        <Suspense
          fallback={
            <p role="status" className="text-body-2 text-text-sub">
              수치를 불러오고 있어요…
            </p>
          }
        >
          <ReportBody />
        </Suspense>
        <footer className="flex flex-col gap-2 text-body-3 text-text-sub">
          <p>검색 평가는 개발자의 실제 공부 기록으로 재서 여기에는 넣지 않았어요.</p>
          <Link href="/demo" className={`self-start ${TEXT_BUTTON}`}>
            같은 가상 데이터로 디딤 둘러보기
          </Link>
        </footer>
      </div>
    </section>
  );
}

async function ReportBody() {
  const runs = await getReportRuns();
  if (runs === null) {
    return (
      <p role="alert" className="text-body-2 font-medium text-error-text">
        평가 수치를 불러오지 못했어요. 잠시 후 다시 열어 주세요.
      </p>
    );
  }
  const latest = runs[0];
  if (!latest) {
    return (
      <p role="status" className="text-body-2 text-text-sub">
        아직 잰 회차가 없어요.
      </p>
    );
  }
  return (
    <>
      <LatestRun run={latest} />
      {runs.length > 1 ? <RunComparison runs={runs} /> : null}
    </>
  );
}

function LatestRun({ run }: { run: ReportRun }) {
  const sizes = dataSizeItems(run.data);
  return (
    <section aria-labelledby="latest-title" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="latest-title" className="text-title-3 font-semibold">
          최근 회차 · {runDate(run)}
        </h2>
        <p className="text-body-3 text-text-sub">
          모델 {run.model ?? "—"}
          {run.commit ? ` · 코드 ${run.commit}` : ""}
          {sizes.length ? ` · ${sizes.join(" · ")}` : ""}
        </p>
      </div>
      <ul className="grid gap-4 md:grid-cols-2">
        {run.evals.map((item) => (
          <li key={item.key}>
            <EvalCard item={item} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function EvalCard({ item }: { item: ReportEval }) {
  return (
    <article className={`flex h-full flex-col gap-3 ${CARD}`} aria-labelledby={`eval-${item.key}`}>
      <h3 id={`eval-${item.key}`} className={CARD_LABEL}>
        {item.title}
      </h3>
      {item.status === "failed" ? (
        <p className="text-body-3 text-text-sub">이번 회차에는 돌리지 못했어요.</p>
      ) : (
        <dl className="flex flex-col gap-2">
          {item.metrics.map((metric) => (
            <div key={metric.key} className="flex items-baseline justify-between gap-4">
              <dt className="text-body-3 text-text-sub">{metric.label}</dt>
              <dd className="shrink-0 text-body-1 font-semibold text-text-main">
                {formatMetric(metric, item.labels_pending)}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {item.labels_pending > 0 ? (
        <p className="text-body-4 text-text-sub">사람 판정을 기다리는 항목 {item.labels_pending}개가 있어요.</p>
      ) : null}
      {item.status === "partial" ? <p className="text-body-4 text-text-sub">중간에 멈춘 회차라 일부만 쟀어요.</p> : null}
    </article>
  );
}

function RunComparison({ runs }: { runs: ReportRun[] }) {
  const latest = runs[0];
  return (
    <section aria-labelledby="compare-title" className="flex flex-col gap-4">
      <h2 id="compare-title" className="text-title-3 font-semibold">
        회차 비교
      </h2>
      <div className={`overflow-x-auto ${CARD}`}>
        <table className="w-full text-left text-body-3">
          <thead>
            <tr className="border-b border-line-regular text-text-sub">
              <th scope="col" className="py-2 pr-4 font-medium">
                수치
              </th>
              {runs.map((run) => (
                <th key={run.run_id} scope="col" className="py-2 pr-4 font-medium whitespace-nowrap">
                  {runDate(run)}
                  <span className="block text-body-4">{run.model ?? "—"}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {latest.evals.flatMap((item) =>
              item.metrics.map((metric) => (
                <tr key={`${item.key}-${metric.key}`} className="border-b border-line-light">
                  <th scope="row" className="py-2 pr-4 font-normal text-text-sub">
                    {item.title} · {metric.label}
                  </th>
                  {runs.map((run) => {
                    const sameEval = run.evals.find((other) => other.key === item.key);
                    const sameMetric = sameEval?.metrics.find((other) => other.key === metric.key);
                    return (
                      <td key={run.run_id} className="py-2 pr-4 whitespace-nowrap text-text-main">
                        {sameEval && sameMetric ? formatMetric(sameMetric, sameEval.labels_pending) : "—"}
                      </td>
                    );
                  })}
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
