import type { BrowserContext } from "@playwright/test";

// 화면 테스트가 같이 쓰는 도우미(F-013 5차 리뷰 R1 — 파일마다 복사돼 있던 로그인 쿠키 심기를 한 곳으로).
// 가짜 백엔드(tests/mock-backend.mjs)는 이 값의 세션을 '로그인한 사용자'로 본다.
export const VALID_SESSION_TOKEN = "playwright-valid-session-token";

/** 세션 쿠키를 심어 로그인한 상태로 만든다. 노션 테스트처럼 가짜 백엔드의 경우를 고르는 값은 token으로 넘긴다. */
export async function logIn(context: BrowserContext, token: string = VALID_SESSION_TOKEN) {
  await context.addCookies([{ name: "didim_session", value: token, domain: "localhost", path: "/", httpOnly: true }]);
}
