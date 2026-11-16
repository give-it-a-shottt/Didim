import { type Page, expect, test } from "@playwright/test";
import { logIn } from "./helpers";

// 사이드바 접기 · 펴기(사용자 요청 2026-11-16): 넓은 화면에서 버튼으로 접고 펴며, 새로 고침해도 기억한다(localStorage).
// 자소서 탭은 늘 접혀 있고 버튼이 없다. 좁은 화면은 늘 접힘 + 버튼 없음. 가짜 백엔드의 공고 910(자소서)을 읽기만 한다.

const sidebar = (page: Page) => page.locator("aside").filter({ has: page.getByRole("navigation", { name: "메인 메뉴" }) });
const sidebarWidth = async (page: Page) => (await sidebar(page).boundingBox())?.width;

test("넓은 화면: [사이드바 접기]로 접고 펴며, 새로 고침해도 접힌 채로 그려진다", async ({ context, page }) => {
  await logIn(context);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/home");
  expect(await sidebarWidth(page)).toBe(240);

  await page.getByRole("button", { name: "사이드바 접기" }).click();
  await expect.poll(() => sidebarWidth(page)).toBe(56);
  await expect(page.getByRole("button", { name: "사이드바 펼치기" })).toHaveAttribute("aria-expanded", "false");

  await page.reload(); // 첫 화면부터 접힘(인라인 스크립트)
  expect(await sidebarWidth(page)).toBe(56);
  await page.getByRole("link", { name: "기록 · 복습" }).click(); // 화면을 옮겨도 그대로
  await expect(page).toHaveURL(/\/records$/);
  expect(await sidebarWidth(page)).toBe(56);

  await page.getByRole("button", { name: "사이드바 펼치기" }).click();
  await expect.poll(() => sidebarWidth(page)).toBe(240);
  await page.reload();
  expect(await sidebarWidth(page)).toBe(240);
});

test("자소서 탭 · 좁은 화면: 늘 접혀 있고 접기 버튼이 없다", async ({ context, page }) => {
  await logIn(context);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/applications/910/draft");
  expect(await sidebarWidth(page)).toBe(56);
  await expect(page.getByRole("button", { name: /사이드바 (접기|펼치기)/ })).toHaveCount(0);

  await page.setViewportSize({ width: 800, height: 900 });
  await page.goto("/home");
  expect(await sidebarWidth(page)).toBe(56);
  await expect(page.getByRole("button", { name: /사이드바 (접기|펼치기)/ })).toHaveCount(0);
});

test("자소서 탭 ↔ 다른 탭: 탭을 옮기면 내가 고른 상태로 돌아온다(F-013 5차 리뷰 R3)", async ({ context, page }) => {
  await logIn(context);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/applications/910/analysis");
  const tabs = page.getByRole("navigation", { name: "지원 상세 탭" });
  expect(await sidebarWidth(page)).toBe(240);

  // 펼쳐 둔 상태: 자소서 탭에서만 접혔다가 다시 펼침
  await tabs.getByRole("link", { name: "자소서" }).click();
  await expect(page).toHaveURL(/\/draft$/);
  await expect.poll(() => sidebarWidth(page)).toBe(56);
  await tabs.getByRole("link", { name: "공고 분석" }).click();
  await expect(page).toHaveURL(/\/analysis$/);
  await expect.poll(() => sidebarWidth(page)).toBe(240);

  // 접어 둔 상태: 자소서 탭을 다녀와도 접힌 채
  await page.getByRole("button", { name: "사이드바 접기" }).click();
  await expect.poll(() => sidebarWidth(page)).toBe(56);
  await tabs.getByRole("link", { name: "자소서" }).click();
  await expect(page).toHaveURL(/\/draft$/);
  await tabs.getByRole("link", { name: "공고 분석" }).click();
  await expect(page).toHaveURL(/\/analysis$/);
  await expect(page.getByRole("button", { name: "사이드바 펼치기" })).toBeVisible();
  expect(await sidebarWidth(page)).toBe(56);
});

test("저장소를 못 쓰는 브라우저: 접기 · 펴기는 되고, 사이드바 없는 화면을 다녀와도 이번에 접은 상태는 그대로(5차 리뷰 R3)", async ({
  context,
  page,
}) => {
  await context.addInitScript(() => {
    const blocked = () => {
      throw new DOMException("저장소 막힘", "SecurityError");
    };
    Storage.prototype.getItem = blocked;
    Storage.prototype.setItem = blocked;
    Storage.prototype.removeItem = blocked;
  });
  await logIn(context);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/records");
  expect(await sidebarWidth(page)).toBe(240);

  await page.getByRole("button", { name: "사이드바 접기" }).click();
  await expect.poll(() => sidebarWidth(page)).toBe(56);

  await page.getByRole("region", { name: "오늘 복습" }).getByRole("link", { name: "복습 시작" }).click(); // 사이드바 없는 집중 모드
  await expect(page).toHaveURL(/\/quiz\/today$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/records$/);
  await expect(page.getByRole("button", { name: "사이드바 펼치기" })).toBeVisible();
  expect(await sidebarWidth(page)).toBe(56);

  await page.getByRole("button", { name: "사이드바 펼치기" }).click();
  await expect.poll(() => sidebarWidth(page)).toBe(240);
});
