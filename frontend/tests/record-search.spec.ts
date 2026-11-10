import { type BrowserContext, expect, test } from "@playwright/test";

// 기록 검색(F-003) 화면: 기록 · 복습 홈(REV_01_001) 검색창 → 결과 줄 → 노트 상세(REV_01_002) 위치 강조.
// 가짜 백엔드(tests/mock-backend.mjs)의 노트 1을 쓴다.
const VALID_SESSION_TOKEN = "playwright-valid-session-token";

async function logIn(context: BrowserContext) {
  await context.addCookies([
    { name: "didim_session", value: VALID_SESSION_TOKEN, domain: "localhost", path: "/", httpOnly: true },
  ]);
}

test("검색어를 넣으면 결과 줄이 나오고, 누르면 노트 상세에서 그 조각 위치가 강조된다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records");

  await page.getByRole("searchbox", { name: "기록 검색어" }).fill("useState");
  await page.getByRole("button", { name: "검색" }).click();

  await expect(page).toHaveURL(/\/records\?q=useState$/);
  await expect(page.getByRole("heading", { name: "‘useState’ 검색 결과 1개" })).toBeVisible();
  const result = page.getByRole("link", { name: /React 정리/ });
  await expect(result).toContainText("# React 정리 > ## useState");
  await expect(result.locator("mark")).toHaveText("useState");

  await result.click();

  await expect(page).toHaveURL(/\/records\/1\?chunk=12#chunk-12$/);
  // 클라이언트 이동 뒤에는 Next가 이전 화면을 숨긴 채 DOM에 남겨 둔다(cacheComponents의 화면 상태 보존).
  // 그래서 locator("h1") 대신 숨은 요소를 빼는 역할 기준으로 찾는다.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("React 정리");
  await expect(page.getByText("고른 부분: # React 정리 > ## useState")).toBeVisible();
  // 앞 조각에 이모지가 있어도 강조 구간이 정확히 두 번째 조각이다(코드 포인트 단위로 자름).
  await expect(page.locator("#chunk-12")).toHaveText("## useState\n상태를 바꾸면 다시 그려져요.\n");
});

test("주소의 검색어로 바로 열면 입력칸에 검색어가 채워져 있다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records?q=useState");

  await expect(page.getByRole("searchbox", { name: "기록 검색어" })).toHaveValue("useState");
  await expect(page.getByRole("link", { name: /React 정리/ })).toBeVisible();
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
    await expect(page.getByRole("link", { name: /React 정리/ })).toHaveCount(0);
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
    await expect(page.locator("mark")).toHaveCount(0);
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
  await expect(page.locator("mark")).toHaveCount(0);

  await page.goto("/records/999");
  await expect(page.getByText("This page could not be found.")).toBeVisible();
});
