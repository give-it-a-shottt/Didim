import { expect, test } from "@playwright/test";
import { logIn, VALID_SESSION_TOKEN } from "./helpers";

const MEMBER_SCREENS = [
  { path: "/home", screenId: "HOM_01_001" },
  { path: "/records", screenId: "REV_01_001" },
  { path: "/records/1", screenId: "REV_01_002" }, // F-003부터 실제 노트를 불러온다(가짜 백엔드의 노트 1)
  { path: "/records/manage", screenId: "REV_01_003" },
  { path: "/records/wrong-answers", screenId: "REV_03_001" },
  { path: "/quiz/today", screenId: "REV_02_001" }, // F-004부터 주소가 세션 종류(today · wrong · note-번호)
  { path: "/quiz/today/result", screenId: "REV_02_002" },
  { path: "/cards", screenId: "CRD_01_001" },
  { path: "/cards/801", screenId: "CRD_01_002" }, // F-006부터 실제 카드를 불러온다(가짜 백엔드의 카드 801)
  { path: "/applications", screenId: "APL_01_001" },
  { path: "/applications/902/analysis", screenId: "APL_02_002" },
  { path: "/applications/902/draft", screenId: "APL_02_003" },
  { path: "/applications/902/interview", screenId: "APL_02_004" },
  { path: "/settings", screenId: "SET_01_001" },
] as const;

test("공개 페이지(/, /login)와 로그인 에러 배너가 정상 렌더링된다", async ({ page }) => {
  const landingResp = await page.goto("/");
  expect(landingResp?.status()).toBe(200);
  await expect(page.locator('[data-screen-id="LND_01_001"]')).toBeVisible();
  await expect(page.locator("h1")).toHaveCount(1);

  const loginResp = await page.goto("/login");
  expect(loginResp?.status()).toBe(200);
  await expect(page.locator('[data-screen-id="AUT_01_001"]')).toBeVisible();
  await expect(page.locator("h1")).toHaveText("디딤 시작하기");
  const googleLink = page.getByRole("link", { name: "Google로 계속하기" });
  await expect(googleLink).toHaveAttribute("href", "/api/auth/google/login");

  await page.goto("/login?error=oauth_access_denied");
  await expect(page.getByText("구글 로그인이 취소되었어요. 다시 시도해 주세요.")).toBeVisible();

  // 허용 목록 밖(F-015 · D-031): 샘플 체험 안내와 샘플 입구가 같이 보인다
  await page.goto("/login?error=not_allowed");
  await expect(page.getByRole("alert").filter({ hasText: "지금은 샘플 체험만 열려 있어요" })).toBeVisible();
  await expect(page.getByRole("link", { name: "로그인 없이 샘플로 둘러보기" })).toHaveAttribute("href", "/demo");
});

test("허용 목록에서 빠진 세션으로 회원 화면에 오면 '샘플 체험만' 안내가 있는 로그인 화면으로 간다(F-015)", async ({ context, page }) => {
  await logIn(context, `${VALID_SESSION_TOKEN}-blocked`);
  for (const path of ["/home", "/records"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login\?error=not_allowed$/);
    await expect(page.getByRole("alert").filter({ hasText: "지금은 샘플 체험만 열려 있어요" })).toBeVisible();
  }
});

test("비로그인 상태에서 회원 화면(14개 URL)에 접근하면 /login으로 이동한다", async ({
  page,
}) => {
  for (const { path } of MEMBER_SCREENS) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator('[data-screen-id="AUT_01_001"]')).toBeVisible();
  }
});

test("로그인 상태에서 회원 화면 14개가 열리고, 설정(/settings)에서 로그아웃하면 /login으로 이동한다", async ({
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
    // 빈 화면(ScreenPlaceholder)과 완성된 화면 모두 data-screen-id로 확인한다.
    await expect(page.locator(`[data-screen-id="${screenId}"]`)).toBeVisible();
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
