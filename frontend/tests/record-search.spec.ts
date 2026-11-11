import { type BrowserContext, expect, type Page, test } from "@playwright/test";

// 기록 검색(F-003) 화면: 기록 · 복습 홈(REV_01_001) 검색창 → 결과 줄 → 노트 상세(REV_01_002) 위치 강조.
// 가짜 백엔드(tests/mock-backend.mjs)의 노트 1을 쓴다.
const VALID_SESSION_TOKEN = "playwright-valid-session-token";

// 검색 결과 영역("‘…’ 검색 결과 N개" 제목의 section). 홈의 노트 목록 링크와 섞이지 않게 범위를 좁힌다.
function searchResults(page: Page) {
  return page.getByRole("region", { name: /검색 결과/ });
}

async function logIn(context: BrowserContext) {
  await context.addCookies([
    { name: "didim_session", value: VALID_SESSION_TOKEN, domain: "localhost", path: "/", httpOnly: true },
  ]);
}

test("검색어를 넣으면 결과 줄이 나오고, 누르면 노트 상세에서 그 조각 위치가 강조된다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records");

  // Figma 검색 입력칸에는 버튼이 없어 Enter로 보낸다
  await page.getByRole("searchbox", { name: "기록 검색어" }).fill("useState");
  await page.getByRole("searchbox", { name: "기록 검색어" }).press("Enter");

  await expect(page).toHaveURL(/\/records\?q=useState$/);
  await expect(page.getByRole("heading", { name: "‘useState’ 검색 결과 1개" })).toBeVisible();
  // 홈에 노트 목록(F-004)도 있어서 검색 결과 영역 안에서만 찾는다
  const result = searchResults(page).getByRole("link", { name: /React 정리/ });
  await expect(result).toContainText("# React 정리 > ## useState");
  await expect(result.locator("mark")).toHaveText("useState");

  await result.click();

  await expect(page).toHaveURL(/\/records\/1\?chunk=12#chunk-12$/);
  // 클라이언트 이동 뒤에는 Next가 이전 화면을 숨긴 채 DOM에 남겨 둔다(cacheComponents의 화면 상태 보존).
  // 그래서 locator("h1") 대신 숨은 요소를 빼는 역할 기준으로 찾는다.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("React 정리");
  await expect(page.getByText("고른 부분: # React 정리 > ## useState")).toBeVisible();
  // 원문은 조각 단위 마크다운으로 그려지고(## 기호 없이 제목), 고른 조각 하나만 상자로 강조된다.
  // 앞 조각 끝에 이모지가 있어도 강조가 앞 조각으로 번지지 않는다(코드 포인트 → UTF-16 위치 변환).
  const highlighted = page.locator("[data-chunk-highlight]");
  await expect(highlighted).toHaveCount(1);
  await expect(page.locator("#chunk-12")).toContainText("useState");
  await expect(page.locator("#chunk-12")).toContainText("상태를 바꾸면 다시 그려져요.");
  await expect(page.locator("#chunk-12")).not.toContainText("마지막 문장");
  await expect(page.getByRole("heading", { name: "useEffect" })).toBeVisible();
  await expect(page.getByText("## useEffect")).toHaveCount(0);
});

test("원문 속 HTML은 실행되지 않고, 위험한 링크는 비워지고, 이미지는 불러오지 않고 링크로만 보인다", async ({
  context,
  page,
}) => {
  await logIn(context);
  await page.goto("/records/1");
  const original = page.locator('[data-render-mode="markdown"]');

  await expect(original).toBeVisible();
  await expect(original.locator("script")).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __didimXss?: number }).__didimXss)).toBeUndefined();
  const badLink = original.getByRole("link", { name: "나쁜 링크" });
  expect(await badLink.getAttribute("href")).not.toContain("javascript");
  await expect(original.locator("img")).toHaveCount(0);
  await expect(original.getByRole("link", { name: "이미지: 다이어그램" })).toHaveAttribute("href", "https://example.com/a.png");
});

test("200KB가 넘는 원문은 마크다운 대신 글자 그대로 보이고 강조는 그대로 된다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records/2?chunk=21");

  // 서버 응답은 0.1초 안이지만, 22만 자를 브라우저가 그리기까지 약 5초 걸린다(알려진 한계, feature.md)
  await expect(page.locator('[data-render-mode="plain"]')).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("#chunk-21")).toContainText("# 큰 노트"); // 기호가 글자 그대로
  await expect(page.locator("[data-chunk-highlight]")).toHaveCount(1);
});

test("안전장치: 길거나 깊은 부분은 글자 그대로 보이고, 나머지는 마크다운으로 바로 열린다", async ({ context, page }) => {
  await logIn(context);
  const started = Date.now();
  await page.goto("/records/3");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("이상한 노트");
  await expect(page.getByRole("heading", { name: "본문" })).toBeVisible(); // 보통 조각은 마크다운
  await expect(page.locator('[data-segment="plain"]')).toHaveCount(2); // `*a` 5만 자 제목 줄 · `>` 3천 단
  expect(Date.now() - started).toBeLessThan(5_000);
});

test("그리는 시간이 예산(300ms)을 넘으면 남은 부분은 글자 그대로 보인다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records/5");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("느린 노트");
  await expect(page.getByRole("heading", { name: "느린 절 0" })).toBeVisible(); // 처음은 마크다운
  const plainCount = await page.locator('[data-segment="plain"]').count();
  expect(plainCount).toBeGreaterThan(0); // 예산을 넘긴 뒤는 글자 그대로
  expect(plainCount).toBeLessThan(60);
});

test("코드 울타리가 조각 경계에 걸리면 합쳐 그리고, 위치가 틀린 조각은 강조하지 않는다", async ({ context, page }) => {
  await logIn(context);

  await page.goto("/records/4?chunk=42");
  const box = page.locator("#chunk-42");
  await expect(box.locator("pre")).toHaveCount(1); // 두 조각에 걸친 코드 블록이 하나로
  await expect(box.locator("pre")).toContainText("const a = 1;");
  await expect(box.locator("pre")).toContainText("const b = 2;");

  await page.goto("/records/4?chunk=49");
  await expect(page.getByText("고른 부분: # 코드")).toBeVisible();
  await expect(page.locator("[data-chunk-highlight]")).toHaveCount(0);
});

test("주소의 검색어로 바로 열면 입력칸에 검색어가 채워져 있다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records?q=useState");

  await expect(page.getByRole("searchbox", { name: "기록 검색어" })).toHaveValue("useState");
  await expect(searchResults(page).getByRole("link", { name: /React 정리/ })).toBeVisible();
});

test("맞는 기록이 없거나 검색을 쓸 수 없으면 이유가 보인다", async ({ context, page }) => {
  await logIn(context);

  await page.goto("/records?q=없는말");
  await expect(page.getByText("‘없는말’와 맞는 기록이 없어요. 다른 낱말로 찾아보세요.")).toBeVisible();

  // 503은 서버가 준 이유를 그대로 보여 준다(검색 불가 · 시간 상한).
  // getByRole("alert")는 Next의 경로 알림 요소(__next-route-announcer__)도 잡아서 글로 찾는다.
  await page.goto("/records?q=검색불가");
  await expect(page.getByText("지금은 기록 검색을 쓸 수 없어요.")).toBeVisible();

  await page.goto("/records?q=시간초과");
  await expect(page.getByText("검색이 오래 걸려 멈췄어요. 낱말을 줄이거나 더 구체적인 낱말로 찾아보세요.")).toBeVisible();
});

test("서버 오류나 모양이 틀린 응답이면 검색 · 노트 상세 모두 오류 문구가 보인다", async ({ context, page }) => {
  await logIn(context);

  for (const q of ["검색오류", "모양틀림"]) {
    await page.goto(`/records?q=${q}`);
    await expect(page.getByText("검색하지 못했어요. 잠시 뒤 다시 해 주세요.")).toBeVisible();
    await expect(searchResults(page).getByRole("link", { name: /React 정리/ })).toHaveCount(0);
  }

  await page.goto("/records/500");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("노트 상세");
  await expect(page.getByText("노트를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.")).toBeVisible();
});

test("이상한 주소는 찾을 수 없다고 나오고, 없는 조각 번호는 강조 없이 원문만 보인다", async ({ context, page }) => {
  await logIn(context);

  // 2147483648: 10자리라 정규식은 통과하지만 DB integer 상한을 넘어 화면이 먼저 거른다(서버를 부르지 않음).
  for (const path of ["/records/abc", "/records/0", "/records/99999999999", "/records/2147483648"]) {
    await page.goto(path);
    await expect(page.getByText("This page could not be found.")).toBeVisible();
  }

  for (const query of ["chunk=999", "chunk=abc"]) {
    await page.goto(`/records/1?${query}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("React 정리");
    await expect(page.locator("[data-chunk-highlight]")).toHaveCount(0);
    await expect(page.getByText(/고른 부분/)).toHaveCount(0);
  }
});

test("조각을 고르지 않고 노트를 열면 강조 없이 원문만 보이고, 없는 노트는 찾을 수 없다고 나온다", async ({
  context,
  page,
}) => {
  await logIn(context);

  await page.goto("/records/1");
  await expect(page.locator("h1")).toHaveText("React 정리");
  await expect(page.getByText("학습 노트 · 조각 2개")).toBeVisible();
  await expect(page.locator("[data-chunk-highlight]")).toHaveCount(0);

  await page.goto("/records/999");
  await expect(page.getByText("This page could not be found.")).toBeVisible();
});
