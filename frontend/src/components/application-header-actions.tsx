"use client";

// APL_02_001 지원 상세 머리의 클라이언트 부품: 탭(지금 탭 표시) · 상태 바꾸기(제목 줄 끝) · 지우기(탭 줄 끝 — 사용자 확인 2026-11-13).
// 상태 · 지우기는 서버 수정이라 useMutation(D-012), 끝나면 router.refresh()로 서버 컴포넌트가 새로 그린다.

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSelectedLayoutSegment } from "next/navigation";
import { RequestErrorText } from "@/components/request-error";
import {
  APPLICATION_STATUSES,
  type ApplicationStatus,
  STATUS_LABELS,
  applicationHref,
  deleteApplication,
  updateApplicationStatus,
} from "@/lib/applications";
import { FOCUS_RING, TEXT_BUTTON } from "@/lib/ui-classes";

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
  const router = useRouter();
  const change = useMutation({
    mutationFn: (next: ApplicationStatus) => updateApplicationStatus(applicationId, next),
    onSuccess: () => router.refresh(),
  });

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
