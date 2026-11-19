import { defineConfig } from "@playwright/test";
import { FAILING_APP_PORT, FAILING_APP_URL, FAILING_BACKEND_PORT, FAILING_BACKEND_URL } from "./tests/helpers";

const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 3100);
const MOCK_BACKEND_PORT = Number(process.env.MOCK_BACKEND_PORT ?? 8100);
const BASE_URL = `http://localhost:${PORT}`;
const MOCK_BACKEND_URL = `http://127.0.0.1:${MOCK_BACKEND_PORT}`;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: true,
  retries: 0,
  use: {
    baseURL: BASE_URL,
    channel: "chrome",
  },
  // 서버는 적힌 순서대로 하나씩 뜬다 — 세 번째(고장 난 백엔드용)는 두 번째의 빌드가 끝난 뒤 같은 .next로 시작한다.
  // 그래서 순서를 바꾸지 않는다(세 번째를 앞으로 옮기면 빌드 전에 next start가 실패한다).
  webServer: [
    {
      command: "node ./tests/mock-backend.mjs",
      url: `${MOCK_BACKEND_URL}/api/health`,
      reuseExistingServer: false,
      timeout: 15_000,
      env: {
        MOCK_BACKEND_PORT: String(MOCK_BACKEND_PORT),
        MOCK_BACKEND_FAILING_PORT: String(FAILING_BACKEND_PORT),
      },
    },
    {
      command: `npx next build && npx next start --port ${PORT}`,
      url: BASE_URL,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        BACKEND_URL: MOCK_BACKEND_URL,
      },
    },
    {
      command: `npx next start --port ${FAILING_APP_PORT}`,
      url: FAILING_APP_URL,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        BACKEND_URL: FAILING_BACKEND_URL,
      },
    },
  ],
});
