import { expect, test } from "@playwright/test";

// F-010 샘플 체험(DEM_01_001, D-029): 로그인 없이 입구 → [샘플로 체험하기] → 회원 화면 + '샘플' 배지 → [체험 끝내기].
// 쓰기 막기는 서버(app/api/sample_guard.py)가 하고 backend/tests/test_sample_guard.py가 확인한다.

test("샘플 입구는 로그인 없이 열리고 검색에는 올리지 않는다", async ({ page }) => {
  const response = await page.goto("/demo");
  expect(response?.status()).toBe(200);
  await expect(page.locator('[data-screen-id="DEM_01_001"]')).toBeVisible();
  await expect(page.locator("h1")).toHaveCount(1);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  await expect(page.getByText("로그인한 상태라면 체험을 시작할 때 로그아웃돼요.")).toBeVisible();
});

test("로그인 화면에서 샘플 입구로 갈 수 있다", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("link", { name: "로그인 없이 샘플로 둘러보기" }).click();
  await expect(page).toHaveURL(/\/demo$/);
});

test("샘플로 체험하면 회원 화면 위에 '샘플' 배지가 보이고, 체험을 끝내면 랜딩으로 간다", async ({ page }) => {
  await page.goto("/demo");
  await page.getByRole("button", { name: "샘플로 체험하기" }).click();
  await expect(page).toHaveURL(/\/applications$/);
  const banner = page.getByRole("status").filter({ hasText: "가상 지원자의 기록을 둘러보는 중이에요" });
  await expect(banner).toBeVisible();
  await expect(banner.getByText("샘플", { exact: true })).toBeVisible();

  // 다른 회원 화면에도 같은 알림이 보인다
  await page.goto("/cards");
  await expect(page.getByText("가상 지원자의 기록을 둘러보는 중이에요", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "체험 끝내기" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/applications");
  await expect(page).toHaveURL(/\/login$/);
});

test("일반 로그인 세션에는 샘플 알림이 없다", async ({ context, page }) => {
  await context.addCookies([
    { name: "didim_session", value: "playwright-valid-session-token", domain: "localhost", path: "/", httpOnly: true },
  ]);
  await page.goto("/applications");
  await expect(page.locator('[data-screen-id="APL_01_001"]')).toBeVisible();
  await expect(page.getByText("가상 지원자의 기록을 둘러보는 중이에요", { exact: false })).toHaveCount(0);
});

test("샘플 데이터가 아직 없으면(503) 체험 대신 안내 문구를 보여 준다", async ({ page }) => {
  // F-010 1차 리뷰 R3: 시드 전 · 시드 실패 뒤에는 샘플 사용자가 없어 서버가 503을 준다
  await page.route("**/api/demo/session", (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "준비 안 됨" }) }),
  );
  await page.goto("/demo");
  await page.getByRole("button", { name: "샘플로 체험하기" }).click();
  // Next의 화면 이동 알림(__next-route-announcer__)도 role="alert"라 문구로 좁힌다
  await expect(
    page.getByRole("alert").filter({ hasText: "샘플 데이터가 아직 준비되지 않았어요. 잠시 후 다시 시도해 주세요." }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/demo$/);
});
