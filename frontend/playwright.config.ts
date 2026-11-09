import { defineConfig } from "@playwright/test";

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
  webServer: [
    {
      command: "node ./tests/mock-backend.mjs",
      url: `${MOCK_BACKEND_URL}/api/health`,
      reuseExistingServer: false,
      timeout: 15_000,
      env: {
        MOCK_BACKEND_PORT: String(MOCK_BACKEND_PORT),
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
  ],
});
