import type { BrowserContext } from "@playwright/test";

// 화면 테스트가 같이 쓰는 도우미(F-013 5차 리뷰 R1 — 파일마다 복사돼 있던 로그인 쿠키 심기를 한 곳으로).
// 가짜 백엔드(tests/mock-backend.mjs)는 이 값의 세션을 '로그인한 사용자'로 본다.
export const VALID_SESSION_TOKEN = "playwright-valid-session-token";

// 고장 난 백엔드(모든 요청 500)를 보는 두 번째 화면 서버 — 같은 빌드를 다른 포트로 띄운다(playwright.config.ts).
export const FAILING_APP_PORT = Number(process.env.PLAYWRIGHT_FAILING_PORT ?? 3101);
export const FAILING_APP_URL = `http://localhost:${FAILING_APP_PORT}`;
export const FAILING_BACKEND_PORT = Number(process.env.MOCK_BACKEND_FAILING_PORT ?? 8101);
export const FAILING_BACKEND_URL = `http://127.0.0.1:${FAILING_BACKEND_PORT}`;

/** 세션 쿠키를 심어 로그인한 상태로 만든다. 노션 테스트처럼 가짜 백엔드의 경우를 고르는 값은 token으로 넘긴다. */
export async function logIn(context: BrowserContext, token: string = VALID_SESSION_TOKEN) {
  await context.addCookies([{ name: "didim_session", value: token, domain: "localhost", path: "/", httpOnly: true }]);
}
