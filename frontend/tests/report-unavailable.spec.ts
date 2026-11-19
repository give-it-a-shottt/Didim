import { expect, test, type APIRequestContext } from "@playwright/test";
import { FAILING_APP_URL, FAILING_BACKEND_URL } from "./helpers";

// 평가 리포트를 통째로 못 읽을 때(F-011 · F-010 다음에 고칠 것, D-030). 이 파일은 고장 난 백엔드(모든 요청 500)를 보는
// 두 번째 화면 서버(FAILING_APP_URL)로 연다 — 랜딩은 수치 칸만 숨고, 리포트는 '불러오지 못함'을 알린다.
// 화면을 연 뒤 고장 난 백엔드가 받은 /api/report 수가 늘었는지 본다: BACKEND_URL이 안 먹어 아무 데도 연결 못 해도
// 화면은 같아 보여서, '500을 받았을 때'를 정말 지나갔는지는 이 수로만 알 수 있다(두 테스트가 같이 돌아도 수는 늘기만 함).

async function reportRequests(request: APIRequestContext): Promise<number> {
  const response = await request.get(`${FAILING_BACKEND_URL}/__test/report-requests`);
  expect(response.ok()).toBe(true);
  return ((await response.json()) as { count: number }).count;
}

test("랜딩: 리포트를 못 읽으면 수치 칸만 숨고, 첫 화면 · [평가 리포트 전체 보기]는 남는다", async ({ page, request }) => {
  const before = await reportRequests(request);
  const response = await page.goto(`${FAILING_APP_URL}/`);
  expect(response?.status()).toBe(200);
  await expect(page.locator("h1")).toHaveCount(1);

  const hero = page.getByRole("region", { name: /문장마다/ });
  await expect(hero.getByRole("link", { name: "내 기록으로 시작하기" })).toHaveAttribute("href", "/login");
  await expect(hero.getByRole("link", { name: "샘플 보기" })).toHaveAttribute("href", "/demo");

  const metrics = page.getByRole("region", { name: "평가 수치" });
  await expect(metrics.getByText("수치를 불러오고 있어요…")).toHaveCount(0); // 기다림 글이 사라질 때까지(스트리밍 끝)
  await expect(metrics.getByRole("definition")).toHaveCount(0);
  await expect(metrics.getByText(/회차/)).toHaveCount(0);
  await expect(metrics.getByRole("link", { name: "평가 리포트 전체 보기" })).toHaveAttribute("href", "/report");
  // 첫 화면 자소서 카드는 샘플 글(lib/landing.ts)이라 백엔드와 상관없이 보인다
  await expect(page.getByRole("figure", { name: /디딤 자소서 화면 예시/ })).toBeVisible();
  expect(await reportRequests(request)).toBeGreaterThan(before);
});

test("리포트: 못 읽으면 '불러오지 못했어요'를 알리고, 샘플 체험 링크는 남는다", async ({ page, request }) => {
  const before = await reportRequests(request);
  const response = await page.goto(`${FAILING_APP_URL}/report`);
  expect(response?.status()).toBe(200);
  await expect(page.locator("h1")).toHaveCount(1);
  await expect(page.getByRole("alert").filter({ hasText: "평가 수치를 불러오지 못했어요. 잠시 후 다시 열어 주세요." })).toBeVisible();
  await expect(page.getByRole("heading", { name: /최근 회차/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "같은 가상 데이터로 디딤 둘러보기" })).toHaveAttribute("href", "/demo");
  expect(await reportRequests(request)).toBeGreaterThan(before);
});
