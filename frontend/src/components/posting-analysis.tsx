"use client";

// APL_02_002 공고 분석(Figma 27:1476) + APL_02_900 AI 실패 · 한도(27:1724).
// 분석은 요청 두 번(설계 의도 F-007): ① 요구 역량 뽑기 → 끝나면 자동으로 ② 매칭. ②만 실패하면 ① 결과는 남고 [매칭 다시].
// 공고 · 역량 · 매칭은 서버 컴포넌트가 넘기고(D-012), ① · ②는 서버 수정이라 useMutation, 끝나면 router.refresh()로 새로 받는다.
// 고른 역량(오른쪽 '선택한 역량의 근거')은 이 화면만 쓰는 상태라 useState.
// 파일 나눔(F-007 2차 R1): 왼쪽 표 posting-requirements.tsx, 오른쪽 칸 posting-aside.tsx.

import { type UseMutationResult, useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { PostingText, SelectedEvidence, Summary } from "@/components/posting-aside";
import { RequirementTable } from "@/components/posting-requirements";
import { ApiRequestError } from "@/lib/api-request";
import {
  ANALYSIS_MAX_AI_CALLS,
  type ApplicationDetail,
  MAX_REQUIREMENTS,
  extractRequirements,
  matchRequirements,
} from "@/lib/applications";
import { CARD, PRIMARY_BUTTON, SECONDARY_BUTTON_S } from "@/lib/ui-classes";

const CONFLICT = 409;

export function PostingAnalysis({ application, autoStart }: { application: ApplicationDetail; autoStart: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const match = useMutation({
    mutationFn: () => matchRequirements(application.id),
    onSuccess: () => router.refresh(),
    onError: (error) => {
      if (error instanceof ApiRequestError && error.status === CONFLICT) router.refresh();
    },
  });
  const extract = useMutation({
    mutationFn: () => extractRequirements(application.id),
    onSuccess: (result) => {
      router.refresh();
      if (result.requirementCount > 0) match.mutate(); // ① 다음에 ②를 이어서
    },
    onError: (error) => {
      // 409 "이미 뽑았어요"(다른 탭에서 먼저) — 새로 받아 결과를 보여 준다
      if (error instanceof ApiRequestError && error.status === CONFLICT) router.refresh();
    },
  });

  // 공고 추가 모달에서 왔으면(?analyze=1) 한 번만 시작하고, 새로 고쳐도 다시 시작하지 않게 주소에서 지운다
  const started = useRef(false);
  useEffect(() => {
    if (!autoStart || started.current) return;
    started.current = true;
    router.replace(pathname);
    if (!application.extracted) extract.mutate();
  }, [autoStart, application.extracted, extract, pathname, router]);

  const requirements = application.requirements;
  const selected = requirements.find((item) => item.id === selectedId) ?? requirements[0] ?? null;
  const busy = extract.isPending || match.isPending;
  // ①이 막 성공했지만 router.refresh()로 새 서버 데이터가 아직 안 왔을 때도 '뽑음'으로 본다(1차 리뷰 R3 —
  // 이 사이에 '찾지 못했어요'가 잘못 뜨고, 이어서 도는 ② 진행 표시가 안 보였다)
  const foundCount = extract.data?.requirementCount ?? null;
  const showExtracted = application.extracted || (foundCount !== null && foundCount > 0);

  return (
    <div className="flex flex-col gap-6 px-5 py-6 lg:flex-row lg:items-start lg:px-12">
      <section aria-labelledby="analysis-title" className={`${CARD} flex min-w-0 flex-1 flex-col gap-4`}>
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="analysis-title" className="text-title-3 font-semibold text-text-main">
            공고가 원하는 것 · 내 근거
          </h2>
          <div className="flex-1" />
          {application.extracted ? (
            <p className="text-body-3 text-text-sub">공고에서 {requirements.length}개를 찾았어요</p>
          ) : null}
        </div>

        {showExtracted ? (
          <>
            {match.isPending ? <Progress text="내 저장 카드와 맞춰 보고 있어요. 최대 3분쯤 걸려요." /> : null}
            {match.error ? (
              <AnalysisFailure
                title="매칭하지 못했어요 · 뽑은 요구 역량은 남겨 뒀어요"
                error={match.error}
                retryLabel="매칭 다시"
                onRetry={() => match.mutate()}
              />
            ) : null}
            {requirements.length === 0 ? (
              <Progress
                text={
                  foundCount
                    ? `요구 역량 ${foundCount}개를 찾았어요. 목록을 불러오고 있어요.`
                    : "요구 역량 목록을 불러오고 있어요."
                }
              />
            ) : (
              <RequirementTable
                requirements={requirements}
                matched={application.matched}
                selectedId={selected?.id ?? null}
                onSelect={setSelectedId}
              />
            )}
          </>
        ) : (
          <ExtractPanel extract={extract} foundCount={foundCount} />
        )}
      </section>

      <aside aria-label="요약 · 근거" className="flex w-full flex-col gap-4 lg:w-104 lg:shrink-0">
        <Summary application={application} busy={busy} onRematch={() => match.mutate()} />
        {selected && application.extracted ? <SelectedEvidence requirement={selected} matched={application.matched} /> : null}
        <PostingText text={application.postingText} highlight={application.extracted ? selected : null} />
      </aside>
    </div>
  );
}

/** ① 뽑기 전: 진행 중 · 실패 · 시작 안내(0개를 찾았으면 다시 뽑기 안내) */
function ExtractPanel({
  extract,
  foundCount,
}: {
  extract: UseMutationResult<unknown, Error, void>;
  foundCount: number | null;
}) {
  if (extract.isPending) return <Progress text="공고에서 요구 역량을 찾고 있어요. 최대 3분쯤 걸려요." />;
  if (extract.error) {
    return (
      <AnalysisFailure
        title="요구 역량을 뽑지 못했어요"
        error={extract.error}
        retryLabel="다시 뽑기"
        onRetry={() => extract.mutate()}
      />
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {/* 설계 원칙 6: AI에 무엇을 보내는지 누르기 전에 알린다 */}
      <p className="text-body-2 text-text-sub">
        {foundCount === 0
          ? "공고에서 요구 역량을 찾지 못했어요. 자격 요건 · 우대 사항이 들어간 본문인지 확인하고 다시 뽑아 주세요."
          : `붙여 넣은 공고 본문을 AI에 보내 요구 역량을 최대 ${MAX_REQUIREMENTS}개 뽑아요. 역량마다 공고 문장을 그대로 골라 오고, 공고에 없는 문장이면 버려요. 이어서 내 저장 카드와 맞춰 봐요. 오늘 AI 사용량을 최대 ${ANALYSIS_MAX_AI_CALLS}회 써요.`}
      </p>
      <button type="button" onClick={() => extract.mutate()} className={`${PRIMARY_BUTTON} self-start`}>
        요구 역량 뽑기
      </button>
    </div>
  );
}

function Progress({ text }: { text: string }) {
  return (
    <p role="status" className="rounded-button bg-bg-light p-4 text-body-2 text-text-sub">
      {text}
    </p>
  );
}

/** APL_02_900: 실패 이유 + 다시 시도. 로그인이 풀렸으면 로그인 링크. 뽑아 둔 결과는 그대로 둔다(부분 결과 보존). */
function AnalysisFailure({
  title,
  error,
  retryLabel,
  onRetry,
}: {
  title: string;
  error: Error;
  retryLabel: string;
  onRetry: () => void;
}) {
  const needsLogin = error instanceof ApiRequestError && error.needsLogin;
  return (
    <div role="alert" className="flex gap-3 rounded-button border border-warning-text bg-bg-light p-4">
      <Icon name="warning" size={20} className="text-warning-text" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-body-1 font-medium text-text-main">{title}</p>
        <p className="text-body-3 text-text-sub">{error.message}</p>
        <div className="mt-1 flex gap-2">
          {needsLogin ? (
            <Link href="/login" className={SECONDARY_BUTTON_S}>
              로그인하러 가기
            </Link>
          ) : (
            <button type="button" onClick={onRetry} className={SECONDARY_BUTTON_S}>
              {retryLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
