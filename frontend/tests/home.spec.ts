import { expect, test } from "@playwright/test";
import { VALID_SESSION_TOKEN, logIn } from "./helpers";

// F-012 홈(HOM_01_001 대시보드 · HOM_01_900 첫 방문). 가짜 백엔드 /api/home은 토큰 꼬리표로 경우를 나눈다.

test("처음 온 사람: 단계 띠는 0, 첫 방문 체크리스트 세 단계와 샘플 체험 입구가 보인다", async ({ context, page }) => {
  await logIn(context, `${VALID_SESSION_TOKEN}-home-empty`);
  await page.goto("/home");
  await expect(page.locator("h1")).toHaveCount(1);
  const band = page.getByRole("navigation", { name: "디딤 흐름" });
  await expect(band.getByRole("link")).toHaveCount(5);
  await expect(band.getByRole("link", { name: /1\. 기록\s*0/ })).toHaveAttribute("href", "/records");

  const firstVisit = page.locator('[data-screen-id="HOM_01_900"]');
  await expect(firstVisit).toBeVisible();
  await expect(firstVisit.getByText("첫 기록 올리기 — 아직")).toBeAttached();
  await expect(firstVisit.getByRole("button", { name: "기록 추가" })).toBeVisible();
  await expect(firstVisit.getByRole("link", { name: "공고 추가하러 가기" })).toHaveAttribute("href", "/applications");
  await expect(firstVisit.getByRole("link", { name: "샘플로 체험하기" })).toHaveAttribute("href", "/demo");
  await expect(firstVisit.getByText("체험을 시작하면 지금 로그인은 풀려요.")).toBeVisible();

  await expect(page.getByText("오늘은 복습할 문제가 없어요.")).toBeVisible();
  await expect(page.getByText("7일 안에 마감인 지원이 없어요.")).toBeVisible();
  await expect(page.getByText("빈칸이 남은 카드가 없어요.")).toBeVisible();
});

test("기록만 있는 사람: 첫 단계는 끝났다고 보이고 체크리스트는 남아 있다", async ({ context, page }) => {
  await logIn(context, `${VALID_SESSION_TOKEN}-home-partial`);
  await page.goto("/home");
  const firstVisit = page.locator('[data-screen-id="HOM_01_900"]');
  await expect(firstVisit.getByText("첫 기록 올리기 — 끝냄")).toBeAttached();
  await expect(firstVisit.getByText("경험 카드 1장 만들기 — 아직")).toBeAttached();
  await expect(firstVisit.getByRole("button", { name: "기록 추가" })).toHaveCount(0);
});

test("다시 온 사람: 체크리스트 없이 단계 띠 개수와 대시보드 세 칸으로 간다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/home");
  await expect(page.locator('[data-screen-id="HOM_01_900"]')).toHaveCount(0);
  await expect(page.getByRole("link", { name: "샘플로 체험하기" })).toHaveCount(0);

  const band = page.getByRole("navigation", { name: "디딤 흐름" });
  await expect(band.getByRole("link", { name: /5\. 자소서 · 면접\s*2/ })).toHaveAttribute("href", "/applications");
  await expect(band.getByRole("link", { name: /2\. 오늘 복습\s*4/ })).toBeVisible();

  await expect(page.getByRole("link", { name: "복습 시작" })).toHaveAttribute("href", "/quiz/today");
  await expect(page.getByRole("link", { name: /스텝랩 · 백엔드/ })).toHaveAttribute("href", "/applications/902/analysis");
  const card = page.getByRole("link", { name: /로그인이 30분마다 풀리던 버그/ });
  await expect(card).toHaveAttribute("href", "/cards/801");
  await expect(card).toContainText("빈칸: 과제 · 결과");
});

for (const [tag, why] of [
  ["-home-error", "서버 오류(500)"],
  ["-home-bad", "200인데 모양이 틀림(남은 날 음수)"],
]) {
  test(`홈 정보를 못 받으면 알림을 보여 준다 — ${why}`, async ({ context, page }) => {
    await logIn(context, `${VALID_SESSION_TOKEN}${tag}`);
    await page.goto("/home");
    await expect(page.getByRole("alert").filter({ hasText: "홈을 불러오지 못했어요" })).toBeVisible();
    await expect(page.getByText("지난마감")).toHaveCount(0);
  });
}
