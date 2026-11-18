import { expect, test } from "@playwright/test";
import { logIn } from "./helpers";

// F-011 랜딩(LND_01_001, D-007, Figma 29:1373). 가짜 백엔드 /api/report 최근 회차: 자소서 · AI 초안은 판정 대기,
// 면접 · 심은 질문 75%, 공고 매칭은 돌리지 못함(failed — 랜딩은 그 칸을 뺀다).

test("처음 온 사람: 첫 화면에 헤드라인 · 시작하기 · 샘플 보기 · 자소서 화면 · 평가 수치가 있다", async ({ page }) => {
  const response = await page.goto("/");
  expect(response?.status()).toBe(200);
  await expect(page.locator('[data-screen-id="LND_01_001"]')).toBeVisible();
  await expect(page.locator("h1")).toHaveCount(1);
  await expect(page.locator("main")).toHaveCount(1);
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0); // 공개 · 검색 노출
  await expect(page).toHaveTitle(/문장마다 근거가 달린 자소서/);

  const nav = page.getByRole("navigation", { name: "사이트" });
  await expect(nav.getByRole("link", { name: "로그인" })).toHaveAttribute("href", "/login");
  await expect(nav.getByRole("link", { name: "기능" })).toHaveAttribute("href", "#features");
  await expect(nav.getByRole("link", { name: "평가 방법" })).toHaveAttribute("href", "#how-measured");

  const hero = page.getByRole("region", { name: /문장마다/ });
  await expect(hero.getByRole("link", { name: "내 기록으로 시작하기" })).toHaveAttribute("href", "/login");
  await expect(hero.getByRole("link", { name: "샘플 보기" })).toHaveAttribute("href", "/demo");

  const metrics = page.getByRole("region", { name: "평가 수치" });
  // 판정 대기는 숫자 대신 글로, 돌리지 못한 평가(공고 매칭)는 칸을 뺀다
  await expect(metrics.getByRole("definition")).toHaveText(["판정 대기", "75.0%"]);
  await expect(metrics.getByText("없는 근거로 만든 매칭 수")).toHaveCount(0);
  await expect(metrics.getByText(/2026-11-17 회차 · 모델 ultra — 정답을 미리 심어 둔 가상 데이터\(심은 경험 20개 · 공고 10개\)/)).toBeVisible();
  await expect(metrics.getByRole("link", { name: "평가 리포트 전체 보기" })).toHaveAttribute("href", "/report");
});

test("첫 화면 자소서 카드: 샘플 실제 초안 5문장에 근거 칩 · '확인 필요' · '근거 없음'", async ({ page }) => {
  await page.goto("/");
  const preview = page.getByRole("figure", { name: /디딤 자소서 화면 예시: 문장 5개 중 2개에 경고/ });
  await expect(preview.getByText("확인 필요 · 카드에 없는 낱말: msa")).toBeVisible();
  await expect(preview.getByText("근거 없음")).toBeVisible();
  await expect(preview.getByText("쿠폰이 중복 발급되던 문제")).toHaveCount(2);
  await expect(preview.getByText(/샘플 계정|\[가상\] 바구니마켓/)).toBeVisible();
});

test("스토리 세 장면: 같은 초안의 두 문장, 근거 없는 문장에 밑줄 → 빼고 원문 각주, 건너뛰기", async ({ page }) => {
  await page.goto("/");
  const story = page.getByRole("region", { name: "AI가 쓴 문장, 어디까지가 내 이야기일까요?" });
  const scenes = story.locator("[data-scene]");
  await expect(scenes).toHaveCount(3);
  await expect(scenes.nth(1).getByText("근거 없음")).toBeAttached();
  await expect(scenes.nth(2).getByText("근거 없는 문장 1개를 뺐어요")).toBeAttached();
  await expect(scenes.nth(2).locator("figcaption")).toHaveText("카드 · 쿠폰이 중복 발급되던 문제 · 결과 칸");
  await expect(story.getByRole("link", { name: "건너뛰기" })).toHaveAttribute("href", "#story-end");
  await expect(page.locator("#story-end")).toBeAttached();
});

test("넓은 화면: 스토리 · 기능 두 고정 구간(250vh)에서 스크롤로 한 칸씩 들어오고, 움직임 줄이기면 다 보인다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const story = page.locator("#story");
  await expect(story).toHaveAttribute("data-motion", "");
  expect(await story.evaluate((element) => element.getBoundingClientRect().height)).toBe(2250); // 250vh × 900

  // 고정 구간 시작: 1장면만, 끝 무렵: 3장면까지
  const top = await story.evaluate((element) => element.getBoundingClientRect().top + window.scrollY);
  await page.evaluate((y) => window.scrollTo({ top: y + 10, behavior: "instant" }), top);
  await expect(story).toHaveAttribute("data-step", "1");
  await expect(story.locator('[data-scene="3"]')).toHaveCSS("opacity", "0");
  await page.evaluate((y) => window.scrollTo({ top: y + 1200, behavior: "instant" }), top);
  await expect(story).toHaveAttribute("data-step", "3");
  await expect(story.locator('[data-scene="3"]')).toHaveCSS("opacity", "1");

  // 기능 카드도 같은 고정 구간: 처음엔 1장만, 끝 무렵 3장까지(사용자 요청 2026-11-18)
  const features = page.locator("#features");
  await expect(features).toHaveAttribute("data-motion", "");
  expect(await features.evaluate((element) => element.getBoundingClientRect().height)).toBe(2250); // 250vh × 900
  const featuresTop = await features.evaluate((element) => element.getBoundingClientRect().top + window.scrollY);
  await page.evaluate((y) => window.scrollTo({ top: y + 10, behavior: "instant" }), featuresTop);
  await expect(features).toHaveAttribute("data-step", "1");
  await expect(features.locator('[data-scene="2"]')).toHaveCSS("opacity", "0");
  await page.evaluate((y) => window.scrollTo({ top: y + 1200, behavior: "instant" }), featuresTop);
  await expect(features).toHaveAttribute("data-step", "3");
  await expect(features.locator('[data-scene="3"]')).toHaveCSS("opacity", "1");
  await expect(features.getByRole("link", { name: "건너뛰기" })).toHaveAttribute("href", "#features-end");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.evaluate(() => window.dispatchEvent(new Event("resize")));
  expect(await story.evaluate((element) => element.getBoundingClientRect().height)).toBeLessThan(900);
  await expect(story).toHaveAttribute("data-step", "3");
  await expect(story.locator('[data-scene="2"]')).toHaveCSS("opacity", "1");
  expect(await features.evaluate((element) => element.getBoundingClientRect().height)).toBeLessThan(900);
  await expect(features.locator('[data-scene="2"]')).toHaveCSS("opacity", "1");
});

test("아래 구역: 기능 세 칸 · 평가 방법 · 마지막 시작하기 · 바닥글", async ({ page }) => {
  await page.goto("/");
  const features = page.getByRole("region", { name: "기록 하나가 세 번 쓰여요" });
  await expect(features.getByRole("heading", { level: 3 })).toHaveText(["복습", "경험 카드", "근거 달린 자소서"]);
  await expect(features.getByText("해설의 근거 · 노트 · 프로세스와 스레드")).toBeVisible();
  await expect(page.getByRole("region", { name: "수치는 어떻게 쟀나요" }).getByRole("listitem")).toHaveCount(3);
  const finalCta = page.getByRole("region", { name: "내 기록으로 시작해 보세요" });
  await expect(finalCta.getByRole("link", { name: "내 기록으로 시작하기" })).toHaveAttribute("href", "/login");
  await expect(page.getByRole("contentinfo")).toContainText("혼자 2주 동안 만든 포트폴리오 프로젝트");
});

test("로그인한 사람: 랜딩은 그대로, [로그인] · [내 기록으로 시작하기] 대신 [홈으로]", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "내 기록으로 시작하기" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "로그인" })).toHaveCount(0);
  const homeLinks = page.getByRole("link", { name: "홈으로" });
  await expect(homeLinks).toHaveCount(3); // 위 메뉴 · 첫 화면 · 마지막 시작하기
  for (const link of await homeLinks.all()) {
    await expect(link).toHaveAttribute("href", "/home");
  }
});
