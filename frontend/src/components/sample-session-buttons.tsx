"use client";

// 샘플 체험 열기 · 끝내기 버튼(F-010, D-029). 둘 다 세션 쿠키를 바꾸는 일이라 서버 요청 뒤 화면을 새로 그린다.
// - 열기: POST /api/demo/session → 샘플 사용자 세션으로 바꿔 끼우고 지원 목록으로 간다(로그인 중이었다면 로그아웃됨).
// - 끝내기: POST /api/auth/logout → 랜딩으로 간다.
import { useState } from "react";
import { useRouter } from "next/navigation";
import { GHOST_BUTTON_S, PRIMARY_BUTTON_L } from "@/lib/ui-classes";

const SAMPLE_START_PATH = "/applications";

export function StartSampleButton() {
  const router = useRouter();
  const [isPending, setIsPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleStart() {
    if (isPending) return;
    setIsPending(true);
    setErrorMessage(null);
    try {
      const response = await fetch("/api/demo/session", { method: "POST" });
      if (!response.ok) {
        setErrorMessage(
          response.status === 503
            ? "샘플 데이터가 아직 준비되지 않았어요. 잠시 후 다시 시도해 주세요."
            : "샘플 체험을 열지 못했어요. 다시 시도해 주세요.",
        );
        setIsPending(false);
        return;
      }
      router.push(SAMPLE_START_PATH);
      router.refresh();
    } catch {
      setErrorMessage("네트워크 문제로 샘플 체험을 열지 못했어요. 다시 시도해 주세요.");
      setIsPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <button type="button" onClick={handleStart} disabled={isPending} className={PRIMARY_BUTTON_L}>
        {isPending ? "샘플을 여는 중…" : "샘플로 체험하기"}
      </button>
      {errorMessage ? (
        <p role="alert" className="text-body-3 text-error-text">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}

export function EndSampleButton() {
  const router = useRouter();
  const [isPending, setIsPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleEnd() {
    if (isPending) return;
    setIsPending(true);
    setErrorMessage(null);
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) {
        setErrorMessage("체험을 끝내지 못했어요. 다시 시도해 주세요.");
        setIsPending(false);
        return;
      }
      router.push("/");
      router.refresh();
    } catch {
      setErrorMessage("네트워크 문제로 체험을 끝내지 못했어요. 다시 시도해 주세요.");
      setIsPending(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button type="button" onClick={handleEnd} disabled={isPending} className={GHOST_BUTTON_S}>
        {isPending ? "끝내는 중…" : "체험 끝내기"}
      </button>
      {errorMessage ? (
        <p role="alert" className="text-body-4 text-error-text">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
