import "server-only";

import { cache } from "react";
import { redirect } from "next/navigation";
import { fetchBackendAsUser } from "@/lib/backend";

export type CurrentUser = {
  id: number;
  email: string;
  name: string;
};

/**
 * 브라우저가 보낸 httpOnly 세션 쿠키를 FastAPI `/api/auth/me`에 전달해
 * 현재 로그인한 사용자 정보를 가져온다. 비로그인·만료 시 null을 돌려준다.
 *
 * React cache()로 감싸서, 한 번의 화면 요청 안에서는 레이아웃(MemberAuthGuard)과
 * 페이지(예: 설정)가 둘 다 불러도 백엔드 /api/auth/me는 한 번만 호출된다(F-001 R2 제안).
 * 요청이 끝나면 캐시도 사라져서 다른 사용자 · 다음 요청과 섞이지 않는다.
 */
export const getCurrentUserOrNull = cache(async (): Promise<CurrentUser | null> => {
  // 쿠키가 없거나 연결이 안 되면 null → 비로그인으로 본다
  const response = await fetchBackendAsUser("/api/auth/me");
  if (!response?.ok) {
    return null;
  }

  try {
    const data: unknown = await response.json();
    if (
      typeof data === "object" &&
      data !== null &&
      "id" in data &&
      "email" in data &&
      "name" in data &&
      typeof (data as CurrentUser).id === "number" &&
      typeof (data as CurrentUser).email === "string" &&
      typeof (data as CurrentUser).name === "string"
    ) {
      return {
        id: (data as CurrentUser).id,
        email: (data as CurrentUser).email,
        name: (data as CurrentUser).name,
      };
    }
    return null;
  } catch {
    return null;
  }
});

/**
 * 회원 전용 화면에서 로그인 여부를 확인하고, 로그인하지 않았으면 `/login`으로 보낸다.
 */
export async function requireCurrentUser(): Promise<CurrentUser> {
  const user = await getCurrentUserOrNull();
  if (!user) {
    redirect("/login");
  }
  return user;
}
