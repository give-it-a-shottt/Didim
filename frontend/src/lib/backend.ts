import "server-only";

import { cookies } from "next/headers";

// 서버 컴포넌트 → FastAPI 호출을 한 곳에 모은다(F-003 1차 리뷰 B). 로그인 확인(auth.ts) · 기록(records.ts) 모두 이걸 쓴다.
// 브라우저가 아니라 Next 서버가 BACKEND_URL로 직접 부르므로, 브라우저가 보낸 httpOnly 세션 쿠키를 그대로 붙여 준다(D-010).
const SESSION_COOKIE_NAME = "didim_session";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

/** 세션 쿠키를 붙여 FastAPI를 부른다. 쿠키가 없거나 연결이 안 되면 null(호출부는 null을 "확인 못 함"으로 다룬다). */
export async function fetchBackendAsUser(path: string): Promise<Response | null> {
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!sessionToken) {
    return null;
  }
  try {
    return await fetch(`${BACKEND_URL}${path}`, {
      headers: { Cookie: `${SESSION_COOKIE_NAME}=${sessionToken}` },
      cache: "no-store",
    });
  } catch {
    return null;
  }
}
