"use client";

// APL_02_002 오른쪽 칸: 요약([매칭 다시]) · 선택한 역량의 근거 · 공고 원문(고른 역량의 인용 자리 표시).

import Link from "next/link";
import { useState } from "react";
import { AddRecordButton } from "@/components/import-records-dialog";
import { SourceQuote } from "@/components/page-parts";
import {
  type ApplicationDetail,
  MATCH_CANDIDATES_PER_REQUIREMENT,
  type Requirement,
  applicationHref,
} from "@/lib/applications";
import { SLOT_LABELS, cardHref } from "@/lib/cards";
import { CARD_LABEL, PRIMARY_BUTTON, PRIMARY_BUTTON_L, SECONDARY_BUTTON_S, TEXT_BUTTON } from "@/lib/ui-classes";

const PANEL = "flex flex-col gap-3 rounded-card border border-line-regular bg-bg-default p-5";

export function Summary({
  application,
  busy,
  onRematch,
}: {
  application: ApplicationDetail;
  busy: boolean;
  onRematch: () => void;
}) {
  return (
    <section aria-labelledby="summary-title" className={PANEL}>
      <h3 id="summary-title" className={CARD_LABEL}>
        요약
      </h3>
      <SummaryBody application={application} busy={busy} onRematch={onRematch} />
    </section>
  );
}

function SummaryBody({
  application,
  busy,
  onRematch,
}: {
  application: ApplicationDetail;
  busy: boolean;
  onRematch: () => void;
}) {
  const total = application.requirements.length;
  if (!application.extracted) {
    return <p className="text-body-2 text-text-sub">공고를 분석하면 요구 역량과 내 카드가 얼마나 맞는지 보여 드려요.</p>;
  }
  if (!application.matched) {
    return (
      <>
        <p className="text-body-2 text-text-sub">요구 역량 {total}개를 뽑았어요. 내 카드와 맞춰 보면 요약을 보여 드려요.</p>
        <button type="button" onClick={onRematch} disabled={busy} className={`${PRIMARY_BUTTON} self-start`}>
          내 카드와 맞춰 보기
        </button>
      </>
    );
  }
  const covered = application.requirements.filter((item) => item.matches.length > 0).length;
  const missing = application.requirements.filter((item) => item.matches.length === 0).map((item) => `'${item.name}'`);
  return (
    <>
      <p className="text-title-4 font-semibold text-text-main">
        요구 역량 {total}개 중 {covered}개에 내 카드가 있어요
      </p>
      <p className="text-body-3 text-text-sub">
        {missing.length > 0
          ? `${missing.join(" · ")}은(는) 내 카드에 근거가 없어요. 관련 노트가 있으면 [기록에서 찾기]로 카드를 만들고, 없으면 자소서에서 다루지 않는 걸 권해요.`
          : "모든 요구 역량에 근거 카드가 있어요."}
      </p>
      <Link href={applicationHref(application.id, "draft")} className={`${PRIMARY_BUTTON_L} w-full`}>
        자소서 쓰기
      </Link>
      {/* 설계 원칙 6: 무엇을 보내는지 알린다 */}
      <p className="text-body-4 text-text-sub">
        새 카드를 저장했다면 다시 맞춰 봐요. 역량마다 키워드가 맞는 내 저장 카드 최대 {MATCH_CANDIDATES_PER_REQUIREMENT}장의
        제목 · 칸 글만 AI에 보내요(AI 사용량 1회, 맞는 카드가 없으면 쓰지 않아요).
      </p>
      <button type="button" onClick={onRematch} disabled={busy} className={`${SECONDARY_BUTTON_S} self-start`}>
        매칭 다시
      </button>
    </>
  );
}

export function SelectedEvidence({ requirement, matched }: { requirement: Requirement; matched: boolean }) {
  return (
    <section aria-labelledby="evidence-title" className={PANEL}>
      <h3 id="evidence-title" className={CARD_LABEL}>
        선택한 역량의 근거 · {requirement.name}
      </h3>
      {requirement.matches.length > 0 ? (
        requirement.matches.map((item) => (
          <div key={item.id} className="flex flex-col gap-2">
            {/* 근거 = 내 카드 칸 글(명조, 설계 원칙 7). 이유는 AI 글(고딕)이라 따로 표시한다 */}
            <SourceQuote
              quote={item.quote}
              source={
                <Link href={cardHref(item.cardId)} className="underline">
                  카드 · {item.cardTitle} · {SLOT_LABELS[item.slot]}
                  {item.quoteSource === "answer" ? "(내 답)" : ""}
                </Link>
              }
            />
            <p className="text-body-3 text-text-sub">
              <span className="font-semibold">AI가 본 이유</span> {item.reason}
            </p>
          </div>
        ))
      ) : matched ? (
        <div className="flex flex-col gap-3">
          <p className="text-body-3 text-text-sub">
            이 역량을 보여 줄 카드가 아직 없어요. 내 기록에서 찾아보고, 맞는 노트가 있으면 노트 상세의 [카드 후보 찾기]로 카드를 만들어요.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Link href={`/records?q=${encodeURIComponent(requirement.name)}`} className={SECONDARY_BUTTON_S}>
              내 기록에서 찾기
            </Link>
            <AddRecordButton variant="page" />
          </div>
        </div>
      ) : (
        <p className="text-body-3 text-text-sub">내 카드와 맞춰 보면 근거가 여기에 나와요.</p>
      )}
    </section>
  );
}

/** 공고 원문 — 고른 역량의 공고 인용 자리를 표시한다(근거 우선, 원칙 1). 공고는 내 기록이 아니라 고딕. */
export function PostingText({ text, highlight }: { text: string; highlight: Requirement | null }) {
  const [expanded, setExpanded] = useState(false);
  const canMark =
    highlight !== null && text.slice(highlight.quoteStart, highlight.quoteEnd) === highlight.quote;
  const body = canMark ? (
    <>
      {text.slice(0, highlight.quoteStart)}
      <mark className="rounded-tag bg-primary-soft text-text-main">{highlight.quote}</mark>
      {text.slice(highlight.quoteEnd)}
    </>
  ) : (
    text
  );
  return (
    <section aria-labelledby="posting-title" className="flex flex-col gap-2 rounded-card border border-line-regular bg-bg-default p-5">
      <h3 id="posting-title" className={CARD_LABEL}>
        공고 원문
      </h3>
      <p
        id="posting-body"
        className={`text-body-3 whitespace-pre-wrap text-text-main ${expanded ? "max-h-120 overflow-y-auto" : "line-clamp-4"}`}
      >
        {expanded ? body : canMark ? highlight.quote : text}
      </p>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls="posting-body"
        onClick={() => setExpanded((value) => !value)}
        className={`${TEXT_BUTTON} self-start`}
      >
        {expanded ? "원문 접기" : "원문 전체 보기"}
      </button>
    </section>
  );
}
