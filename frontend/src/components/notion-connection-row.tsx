"use client";

// 설정(SET_01_001) '연결' 칸의 노션 줄(Figma 28:1275): 아이콘 · 이름 · 상태 한 줄 · 오른쪽 버튼 S.
// 상태는 서버 컴포넌트가 넘기고(D-012), [연결] · [다시 연결]은 주소 이동(노션 동의 화면), [연결 끊기]만 여기서 요청한다.
// 끊은 뒤 router.refresh()로 서버가 그린 상태를 새로 받는다. 상태는 이 줄 안에서만 쓰여 useState(D-012).

import { type ReactNode, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "@/components/icon";
import { ApiRequestError } from "@/lib/api-request";
import { disconnectNotion } from "@/lib/notion";
import { NOTION_CONNECT_PATH, type NotionStatus } from "@/lib/notion-status";
import { GHOST_BUTTON_S, SECONDARY_BUTTON_S } from "@/lib/ui-classes";

export function NotionConnectionRow({ status }: { status: NotionStatus | null }) {
  const router = useRouter();
  const [isPending, setIsPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function disconnect() {
    if (isPending) return;
    setIsPending(true);
    setErrorMessage(null);
    try {
      await disconnectNotion();
      router.refresh();
    } catch (error) {
      setErrorMessage(error instanceof ApiRequestError ? error.message : "연결을 끊지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setIsPending(false);
    }
  }

  let detail: ReactNode;
  let action: ReactNode = null;
  if (status === null) {
    detail = <p className="text-body-4 text-text-sub">연결 상태를 확인하지 못했어요. 잠시 뒤 새로 고쳐 주세요.</p>;
  } else if (!status.configured) {
    detail = <p className="text-body-4 text-text-sub">서버에 노션 연결 설정이 아직 없어요.</p>;
  } else if (status.status === "connected") {
    detail = (
      <p className="truncate text-body-4 text-text-sub">
        {status.workspaceName ?? "노션"} 연결됨 · 노션에서 공유한 페이지만 가져와요
      </p>
    );
    action = (
      <button type="button" onClick={disconnect} disabled={isPending} className={GHOST_BUTTON_S}>
        {isPending ? "끊는 중…" : "연결 끊기"}
      </button>
    );
  } else if (status.status === "broken") {
    // Figma 28:1280 — 경고 아이콘 16 + status/warning 글자
    detail = (
      <p className="flex items-center gap-1 text-body-4 text-warning-text">
        <Icon name="warning" size={16} />
        연결이 끊겼어요 · 권한이 만료됐어요
      </p>
    );
    action = (
      // 노션 동의 화면으로 가는 주소 이동이라 <a>(next/link는 화면 안 이동용)
      <a href={NOTION_CONNECT_PATH} className={SECONDARY_BUTTON_S}>
        다시 연결
      </a>
    );
  } else {
    detail = <p className="text-body-4 text-text-sub">연결하면 노션 페이지를 내보내기 없이 바로 가져올 수 있어요.</p>;
    action = (
      <a href={NOTION_CONNECT_PATH} className={SECONDARY_BUTTON_S}>
        연결
      </a>
    );
  }

  return (
    <div className="flex items-center gap-4 border-b border-line-light py-4">
      <Icon name="notebook" size={20} className="text-icon-sub" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-body-1 font-medium text-text-main">노션</p>
        {detail}
        {errorMessage ? (
          <p role="alert" className="text-body-4 text-error-text">
            {errorMessage}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
