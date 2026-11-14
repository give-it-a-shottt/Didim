"use client";

// APL_02_001 지원 상세 머리의 클라이언트 부품: 탭(지금 탭 표시) · 상태 바꾸기(제목 줄 끝) · 지우기(탭 줄 끝 — 사용자 확인 2026-11-13).
// 상태 · 지우기는 서버 수정이라 useMutation(D-012), 끝나면 router.refresh()로 서버 컴포넌트가 새로 그린다.
// '제출'로 바꿀 때 근거 없는 문장이 있으면 확인창(F-008 완료 기준 3). 개수는 누르는 순간 서버에서 새로 받는다(지금 카드와 다시 비교한 값).
// 자소서 탭에서만 머리에 '자동 저장됨 · 시각' + [제출로 바꾸기](Figma 18:241 · 19:375, 사용자 확인 2026-11-14).

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSelectedLayoutSegment } from "next/navigation";
import { useSyncExternalStore } from "react";
import { Icon } from "@/components/icon";
import { RequestErrorText } from "@/components/request-error";
import {
  APPLICATION_STATUSES,
  type ApplicationStatus,
  STATUS_LABELS,
  applicationHref,
  deleteApplication,
  updateApplicationStatus,
} from "@/lib/applications";
import { draftsQueryKey, fetchDrafts, fetchUnsupportedCount, formatTime } from "@/lib/drafts";
import { FOCUS_RING, SECONDARY_BUTTON_S, TEXT_BUTTON } from "@/lib/ui-classes";

const TABS = [
  { segment: "analysis", label: "공고 분석" },
  { segment: "draft", label: "자소서" },
  { segment: "interview", label: "면접 연습" },
] as const;

/** 밑줄 탭(Figma Tab Line · Black · M 40): 선택 = SemiBold + text/main + 밑줄 2. 탭마다 URL이 달라 새로 고쳐도 같은 탭이 열린다. */
export function ApplicationTabs({ applicationId }: { applicationId: number }) {
  const segment = useSelectedLayoutSegment();
  return (
    <nav aria-label="지원 상세 탭" className="flex">
      {TABS.map((tab) => {
        const selected = segment === tab.segment;
        return (
          <Link
            key={tab.segment}
            href={applicationHref(applicationId, tab.segment)}
            aria-current={selected ? "page" : undefined}
            className={`relative flex h-10 items-center px-3 text-body-2 ${
              selected
                ? "font-semibold text-text-main after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-line-black"
                : "font-medium text-text-sub-weak hover:text-text-main"
            } ${FOCUS_RING}`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function ApplicationStatusSelect({
  applicationId,
  status,
}: {
  applicationId: number;
  status: ApplicationStatus;
}) {
  const change = useStatusChange(applicationId);

  return (
    <div className="flex flex-wrap items-center gap-3">
      {change.error ? <RequestErrorText error={change.error} /> : null}
      <label className="flex items-center gap-2 text-body-3 text-text-sub">
        상태
        <select
          value={status}
          disabled={change.isPending}
          onChange={(event) => change.mutate(event.target.value as ApplicationStatus)}
          className={`h-8 rounded-input border border-line-input bg-bg-default px-2 text-body-2 text-text-main hover:border-line-input-hover ${FOCUS_RING}`}
        >
          {APPLICATION_STATUSES.map((value) => (
            <option key={value} value={value}>
              {STATUS_LABELS[value]}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

/** 상태 바꾸기. '제출'이면 근거 없는 문장 수를 새로 받아, 있으면 확인창 — 취소하면 바꾸지 않는다. */
function useStatusChange(applicationId: number) {
  const router = useRouter();
  return useMutation({
    mutationFn: async (next: ApplicationStatus) => {
      if (next === "submitted") {
        const unsupported = await fetchUnsupportedCount(applicationId);
        if (unsupported > 0 && !window.confirm(`근거 없는 문장이 ${unsupported}개 있어요. 그래도 '제출'로 바꿀까요?`)) return;
      }
      await updateApplicationStatus(applicationId, next);
    },
    onSuccess: () => router.refresh(),
  });
}

const subscribeNothing = () => () => {};

/** 자소서 탭 머리 오른쪽: '자동 저장됨 · 15:24'(가장 최근에 저장한 초안) + [제출로 바꾸기]. 다른 탭에서는 그리지 않는다. */
export function DraftHeaderActions({ applicationId, status }: { applicationId: number; status: ApplicationStatus }) {
  const segment = useSelectedLayoutSegment();
  const change = useStatusChange(applicationId);
  // 자소서 탭이 채운 캐시를 읽기만 한다(여기서 따로 부르지 않음)
  const drafts = useQuery({ queryKey: draftsQueryKey(applicationId), queryFn: () => fetchDrafts(applicationId), enabled: false });
  // 서버 렌더에서는 캐시가 그리는 순서에 따라 차 있거나 비어 있어 브라우저와 어긋난다(hydration 불일치) — 브라우저에서만 읽는다
  const hydrated = useSyncExternalStore(subscribeNothing, () => true, () => false);
  if (segment !== "draft") return null;
  const savedAt = (hydrated ? (drafts.data?.questions ?? []) : [])
    .flatMap((question) => (question.draft ? [question.draft.updatedAt] : []))
    .sort()
    .at(-1);
  return (
    <div className="flex flex-wrap items-center gap-3">
      {change.error ? <RequestErrorText error={change.error} /> : null}
      {savedAt ? (
        <p className="flex items-center gap-1 text-body-4 text-text-sub">
          <Icon name="check" size={16} className="text-icon-sub" />
          자동 저장됨 · {formatTime(savedAt)}
        </p>
      ) : null}
      {status !== "submitted" ? (
        <button type="button" onClick={() => change.mutate("submitted")} disabled={change.isPending} className={SECONDARY_BUTTON_S}>
          제출로 바꾸기
        </button>
      ) : null}
    </div>
  );
}

export function DeleteApplicationButton({ applicationId }: { applicationId: number }) {
  const router = useRouter();
  const remove = useMutation({
    mutationFn: () => deleteApplication(applicationId),
    onSuccess: () => {
      router.push("/applications");
      router.refresh();
    },
  });

  return (
    <div className="flex items-center gap-3">
      {remove.error ? <RequestErrorText error={remove.error} /> : null}
      <button
        type="button"
        disabled={remove.isPending}
        onClick={() => {
          if (window.confirm("이 공고와 분석 결과를 지울까요? 경험 카드는 그대로 남아요.")) remove.mutate();
        }}
        className={TEXT_BUTTON}
      >
        공고 지우기
      </button>
    </div>
  );
}
