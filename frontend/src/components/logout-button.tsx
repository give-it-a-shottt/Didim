"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function LogoutButton() {
  const router = useRouter();
  const [isPending, setIsPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleLogout() {
    if (isPending) return;
    setIsPending(true);
    setErrorMessage(null);

    try {
      const response = await fetch("/api/auth/logout", {
        method: "POST",
      });
      if (!response.ok) {
        setErrorMessage("로그아웃하지 못했어요. 다시 시도해 주세요.");
        setIsPending(false);
        return;
      }
      router.push("/login");
      router.refresh();
    } catch {
      setErrorMessage("네트워크 문제로 로그아웃하지 못했어요. 다시 시도해 주세요.");
      setIsPending(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={handleLogout}
        disabled={isPending}
        className="inline-flex h-8 items-center justify-center rounded-button border border-line-black bg-bg-default px-3 text-body-2 font-medium text-text-main transition-colors hover:bg-bg-regular focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-default disabled:cursor-not-allowed disabled:border-line-regular disabled:bg-bg-regular disabled:text-text-disabled"
      >
        {isPending ? "로그아웃 중…" : "로그아웃"}
      </button>
      {errorMessage ? (
        <p role="alert" className="text-body-4 text-error-text">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
