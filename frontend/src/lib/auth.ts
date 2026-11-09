import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export const SESSION_COOKIE_NAME = "didim_session";

export type CurrentUser = {
  id: number;
  email: string;
  name: string;
};

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

/**
 * 브라우저가 보낸 httpOnly 세션 쿠키를 FastAPI `/api/auth/me`에 전달해
 * 현재 로그인한 사용자 정보를 가져온다. 비로그인·만료 시 null을 돌려준다.
 */
export async function getCurrentUserOrNull(): Promise<CurrentUser | null> {
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!sessionToken) {
    return null;
  }

  try {
    const response = await fetch(`${BACKEND_URL}/api/auth/me`, {
      method: "GET",
      headers: {
        Cookie: `${SESSION_COOKIE_NAME}=${sessionToken}`,
      },
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

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
}

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
