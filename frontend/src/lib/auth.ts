import "server-only";

import { cache } from "react";
import { redirect } from "next/navigation";
import { fetchBackendAsUser } from "@/lib/backend";

export type CurrentUser = {
  id: number;
  email: string;
  name: string;
  // 샘플 체험 세션(D-029) — 회원 화면 위에 '샘플' 배지와 [체험 끝내기]를 보인다
  isSample: boolean;
};

// 서버가 401과 함께 이 머리말로 '허용 목록 밖'을 알린다(backend/app/api/deps.py LOGIN_ERROR_HEADER, F-015 · D-031)
const LOGIN_ERROR_HEADER = "x-didim-login-error";

type CurrentUserCheck = { user: CurrentUser | null; notAllowed: boolean };

/**
 * 브라우저가 보낸 httpOnly 세션 쿠키를 FastAPI `/api/auth/me`에 전달해
 * 현재 로그인한 사용자 정보를 가져온다. 비로그인·만료 시 user는 null, 허용 목록 밖이면 notAllowed도 true.
 *
 * React cache()로 감싸서, 한 번의 화면 요청 안에서는 레이아웃(MemberAuthGuard)과
 * 페이지(예: 설정)가 둘 다 불러도 백엔드 /api/auth/me는 한 번만 호출된다(F-001 R2 제안).
 * 요청이 끝나면 캐시도 사라져서 다른 사용자 · 다음 요청과 섞이지 않는다.
 */
const checkCurrentUser = cache(async (): Promise<CurrentUserCheck> => {
  const response = await fetchBackendAsUser("/api/auth/me");
  if (!response?.ok) {
    return { user: null, notAllowed: response?.status === 401 && response.headers.get(LOGIN_ERROR_HEADER) === "not_allowed" };
  }
  return { user: await readCurrentUser(response), notAllowed: false };
});

export const getCurrentUserOrNull = cache(async (): Promise<CurrentUser | null> => {
  // 쿠키가 없거나 연결이 안 되면 null → 비로그인으로 본다
  return (await checkCurrentUser()).user;
});

async function readCurrentUser(response: Response): Promise<CurrentUser | null> {
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
        isSample: (data as { is_sample?: unknown }).is_sample === true,
      };
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 회원 전용 화면에서 로그인 여부를 확인하고, 로그인하지 않았으면 `/login`으로 보낸다.
 */
export async function requireCurrentUser(): Promise<CurrentUser> {
  const { user, notAllowed } = await checkCurrentUser();
  if (!user) {
    // 허용 목록에서 빠진 사람은 이유('샘플 체험만 열려 있어요')를 보여 주는 로그인 화면으로(F-015 1차 리뷰 R3)
    redirect(notAllowed ? "/login?error=not_allowed" : "/login");
  }
  return user;
}
