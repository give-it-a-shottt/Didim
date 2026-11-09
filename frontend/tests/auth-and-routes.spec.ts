import { expect, test } from "@playwright/test";

const VALID_SESSION_TOKEN = "playwright-valid-session-token";

const MEMBER_SCREENS = [
  { path: "/home", screenId: "HOM_01_001" },
  { path: "/demo", screenId: "DEM_01_001" },
  { path: "/records", screenId: "REV_01_001" },
  { path: "/records/n1", screenId: "REV_01_002" },
  { path: "/records/manage", screenId: "REV_01_003" },
  { path: "/records/wrong-answers", screenId: "REV_03_001" },
  { path: "/quiz/s1", screenId: "REV_02_001" },
  { path: "/quiz/s1/result", screenId: "REV_02_002" },
  { path: "/cards", screenId: "CRD_01_001" },
  { path: "/cards/c1", screenId: "CRD_01_002" },
  { path: "/applications", screenId: "APL_01_001" },
  { path: "/applications/a1/analysis", screenId: "APL_02_002" },
  { path: "/applications/a1/draft", screenId: "APL_02_003" },
  { path: "/applications/a1/interview", screenId: "APL_02_004" },
  { path: "/settings", screenId: "SET_01_001" },
  { path: "/settings/report", screenId: "SET_02_001" },
] as const;

test("공개 페이지(/, /login)와 로그인 에러 배너가 정상 렌더링된다", async ({ page }) => {
  const landingResp = await page.goto("/");
  expect(landingResp?.status()).toBe(200);
  await expect(page.getByText("LND_01_001")).toBeVisible();
  await expect(page.locator("h1")).toHaveCount(1);

  const loginResp = await page.goto("/login");
  expect(loginResp?.status()).toBe(200);
  await expect(page.locator('[data-screen-id="AUT_01_001"]')).toBeVisible();
  await expect(page.locator("h1")).toHaveText("디딤 시작하기");
  const googleLink = page.getByRole("link", { name: "Google로 계속하기" });
  await expect(googleLink).toHaveAttribute("href", "/api/auth/google/login");

  await page.goto("/login?error=oauth_access_denied");
  await expect(page.getByText("구글 로그인이 취소되었어요. 다시 시도해 주세요.")).toBeVisible();
});

test("비로그인 상태에서 회원 화면(16개 URL)에 접근하면 /login으로 이동한다", async ({
  page,
}) => {
  for (const { path } of MEMBER_SCREENS) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator('[data-screen-id="AUT_01_001"]')).toBeVisible();
  }
});

test("로그인 상태에서 회원 화면 16개가 열리고, 설정(/settings)에서 로그아웃하면 /login으로 이동한다", async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      name: "didim_session",
      value: VALID_SESSION_TOKEN,
      domain: "localhost",
      path: "/",
      httpOnly: true,
    },
  ]);

  for (const { path, screenId } of MEMBER_SCREENS) {
    const resp = await page.goto(path);
    expect(resp?.status()).toBe(200);
    await expect(page.locator("h1")).toHaveCount(1);
    if (screenId === "SET_01_001") {
      await expect(page.locator('[data-screen-id="SET_01_001"]')).toBeVisible();
    } else {
      await expect(page.getByText(screenId)).toBeVisible();
    }
  }

  // 설정 화면 계정 표시 및 로그아웃 동작 확인
  await page.goto("/settings");
  await expect(page.getByText("구글 계정으로 로그인 중")).toBeVisible();
  await expect(page.getByText("이디딤 · didim@example.com")).toBeVisible();

  await page.getByRole("button", { name: "로그아웃" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.locator('[data-screen-id="AUT_01_001"]')).toBeVisible();
});

test("/applications/:id는 /analysis로 307 이동하고, robots.txt·sitemap.xml·404가 동작한다", async ({
  request,
}) => {
  const redirectResp = await request.get("/applications/a1", { maxRedirects: 0 });
  expect(redirectResp.status()).toBe(307);
  expect(redirectResp.headers()["location"]).toContain("/applications/a1/analysis");

  const robotsResp = await request.get("/robots.txt");
  expect(robotsResp.status()).toBe(200);
  const robotsText = await robotsResp.text();
  expect(robotsText).toContain("Disallow: /api/");

  const sitemapResp = await request.get("/sitemap.xml");
  expect(sitemapResp.status()).toBe(200);
  const sitemapText = await sitemapResp.text();
  expect(sitemapText).toContain("/login");

  const notFoundResp = await request.get("/non-existent-route-xyz");
  expect(notFoundResp.status()).toBe(404);
});
