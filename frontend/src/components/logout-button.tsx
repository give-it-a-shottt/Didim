"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { GHOST_BUTTON_S } from "@/lib/ui-classes";

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
        // Figma SET_01_001 [로그아웃] = Ghost S(28:1265)
        className={GHOST_BUTTON_S}
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
