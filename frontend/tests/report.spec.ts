import { expect, test } from "@playwright/test";

// F-010 평가 리포트(SET_02_001, D-029): 로그인 없이 보는 공개 페이지. 가짜 백엔드 /api/report는 회차 두 개를 준다.

test("평가 리포트는 로그인 없이 열리고, 판정 대기 · 실패를 숫자 대신 글로 보여 준다", async ({ page }) => {
  const response = await page.goto("/report");
  expect(response?.status()).toBe(200);
  await expect(page.locator('[data-screen-id="SET_02_001"]')).toBeVisible();
  await expect(page.locator("h1")).toHaveCount(1);
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0); // 공개 · 검색 노출

  await expect(page.getByRole("heading", { name: "최근 회차 · 2026-11-17" })).toBeVisible();
  await expect(page.getByText("모델 ultra · 코드 abc1234 · 심은 경험 20개 · 공고 10개 · 자소서 문항 20개")).toBeVisible();

  const quiz = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "퀴즈" }) });
  await expect(quiz.getByText("2.0%")).toBeVisible();
  const drafts = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "자소서 · AI 초안" }) });
  await expect(drafts.getByText("판정 대기")).toBeVisible();
  await expect(drafts.getByText("0.58")).toBeVisible();
  await expect(drafts.getByText("사람 판정을 기다리는 항목 3개가 있어요.")).toBeVisible();
  const cards = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "경험 카드" }) });
  await expect(cards.getByText("이번 회차에는 돌리지 못했어요.")).toBeVisible();
});

test("회차 비교 표에 두 회차가 나란히 나온다", async ({ page }) => {
  await page.goto("/report");
  const table = page.getByRole("table");
  await expect(table.getByRole("columnheader", { name: /2026-11-16/ })).toBeVisible();
  const quizRow = table.getByRole("row", { name: /퀴즈 · 버려진 문제 비율/ });
  await expect(quizRow.getByRole("cell")).toHaveText(["2.0%", "10.0%"]);
  const warnRow = table.getByRole("row", { name: /지어낸 문장 경고율/ });
  await expect(warnRow.getByRole("cell")).toHaveText(["판정 대기", "80.0%"]);
});

test("옛 주소 /settings/report는 /report로 가고, 리포트는 sitemap에 있다", async ({ page, request }) => {
  await page.goto("/settings/report");
  await expect(page).toHaveURL(/\/report$/);
  const sitemap = await (await request.get("/sitemap.xml")).text();
  expect(sitemap).toContain("/report");
  expect(sitemap).not.toContain("/demo");
});
