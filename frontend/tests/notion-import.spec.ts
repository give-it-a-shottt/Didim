import { expect, test, type BrowserContext } from "@playwright/test";

// 노션 연결(F-005): 설정 '연결' 칸(SET_01_001) · 기록 추가 모달의 노션 탭.
// 서버는 가짜 백엔드(tests/mock-backend.mjs)다. 상황은 세션 토큰 뒤 이름으로 고른다(목록은 mock-backend.mjs 노션 구간 주석).
// 토큰 교환 · 갱신 · 블록 변환 · 저장은 backend/tests/test_notion.py가 확인한다.

const VALID_SESSION_TOKEN = "playwright-valid-session-token";

type NotionCase = "none" | "broken" | "midbreak" | "empty" | "many" | "flaky" | "disconnectfail" | "importfail";

async function signIn(context: BrowserContext, notionCase?: NotionCase) {
  const value = notionCase ? `${VALID_SESSION_TOKEN}-notion-${notionCase}` : VALID_SESSION_TOKEN;
  await context.addCookies([{ name: "didim_session", value, domain: "localhost", path: "/", httpOnly: true }]);
}

test("설정: 연결됨이면 워크스페이스와 [연결 끊기], 연결 뒤 돌아오면 안내가 보인다", async ({ context, page }) => {
  await signIn(context);
  await page.goto("/settings?notion=connected");
  const section = page.getByRole("region", { name: "연결" });
  await expect(section.getByText("디딤 워크스페이스 연결됨", { exact: false })).toBeVisible();
  await expect(section.getByRole("status").filter({ hasText: "노션을 연결했어요" })).toBeVisible();
  await expect(section.getByRole("button", { name: "연결 끊기" })).toBeVisible();
});

test("설정: 끊김이면 경고 문구와 [다시 연결](노션 동의 화면 주소)", async ({ context, page }) => {
  await signIn(context, "broken");
  await page.goto("/settings?notion_error=access_denied");
  const section = page.getByRole("region", { name: "연결" });
  await expect(section.getByText("연결이 끊겼어요 · 권한이 만료됐어요")).toBeVisible();
  await expect(section.getByRole("link", { name: "다시 연결" })).toHaveAttribute("href", "/api/notion/connect");
  await expect(section.getByRole("alert").filter({ hasText: "노션 연결을 취소했어요." })).toBeVisible();
});

test("설정: 연결 전이면 [연결]", async ({ context, page }) => {
  await signIn(context, "none");
  await page.goto("/settings");
  const section = page.getByRole("region", { name: "연결" });
  await expect(section.getByRole("link", { name: "연결", exact: true })).toHaveAttribute("href", "/api/notion/connect");
});

test("기록 추가 → 노션 탭 → 페이지 고르기 → 결과 요약(건너뛴 블록 안내)", async ({ context, page }) => {
  await signIn(context);
  await page.goto("/home");
  await page.getByRole("complementary").getByRole("button", { name: "기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  await dialog.getByRole("tab", { name: "노션 연결" }).click();
  await expect(dialog.getByRole("tab", { name: "노션 연결" })).toHaveAttribute("aria-selected", "true");

  const list = dialog.getByRole("list", { name: "가져올 노션 페이지" });
  await expect(list.getByText("트랜잭션 공부")).toBeVisible();
  // 이미 가져온 페이지는 고를 수 없다
  await expect(list.getByRole("checkbox", { name: /이미 가져온 페이지/ })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: /가져오기$/ })).toBeDisabled();

  await list.getByRole("checkbox", { name: /트랜잭션 공부/ }).check();
  await dialog.getByRole("button", { name: "1개 가져오기" }).click();

  const result = dialog.locator('[data-screen-id="IMP_01_003"]');
  await expect(result).toBeVisible();
  await expect(result.getByText("노트", { exact: true }).locator("xpath=..")).toContainText("1");
  await expect(result.getByText("블록 2개는 글로 옮길 수 없어 건너뛰었어요", { exact: false })).toBeVisible();
});

test("노션 탭: 연결 전이면 이유와 설정 링크", async ({ context, page }) => {
  await signIn(context, "none");
  await page.goto("/home");
  await page.getByRole("complementary").getByRole("button", { name: "기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  await dialog.getByRole("tab", { name: "노션 연결" }).click();
  await expect(dialog.getByRole("alert").filter({ hasText: "노션이 연결되어 있지 않아요" })).toBeVisible();
  await expect(dialog.getByRole("link", { name: "설정에서 노션 연결" })).toHaveAttribute("href", "/settings");
});

test("노션 탭: 가져오는 중에 연결이 끊기면 저장된 것은 요약, 남은 것은 실패 이유", async ({ context, page }) => {
  await signIn(context, "midbreak");
  await page.goto("/home");
  await page.getByRole("complementary").getByRole("button", { name: "기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  await dialog.getByRole("tab", { name: "노션 연결" }).click();
  const list = dialog.getByRole("list", { name: "가져올 노션 페이지" });
  await list.getByRole("checkbox", { name: /트랜잭션 공부/ }).check();
  await list.getByRole("checkbox", { name: /네트워크 정리/ }).check();
  await dialog.getByRole("button", { name: "2개 가져오기" }).click();

  const result = dialog.locator('[data-screen-id="IMP_01_003"]');
  await expect(result.getByRole("alert").filter({ hasText: "노션 연결이 끊겼어요" })).toBeVisible();
  await expect(result.getByRole("list", { name: "읽지 못한 페이지" })).toContainText("다시 연결");
});

async function openNotionTab(page: import("@playwright/test").Page) {
  await page.goto("/home");
  await page.getByRole("complementary").getByRole("button", { name: "기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  await dialog.getByRole("tab", { name: "노션 연결" }).click();
  return dialog;
}

// --- 1차 리뷰 R3 · F 반영 (2026-11-12) ---

test("노션 탭: 공유된 페이지가 없으면 빈 안내", async ({ context, page }) => {
  await signIn(context, "empty");
  const dialog = await openNotionTab(page);
  await expect(dialog.getByText("가져올 수 있는 페이지가 없어요", { exact: false })).toBeVisible();
  await expect(dialog.getByRole("button", { name: /가져오기$/ })).toBeDisabled();
});

test("노션 탭: 20개까지만 고를 수 있고, 100개가 넘으면 '최근 100개만' 안내", async ({ context, page }) => {
  await signIn(context, "many");
  const dialog = await openNotionTab(page);
  await expect(dialog.getByText("최근 수정한 100개만 보여요", { exact: false })).toBeVisible();
  const boxes = dialog.getByRole("list", { name: "가져올 노션 페이지" }).getByRole("checkbox");
  for (let index = 0; index < 20; index += 1) await boxes.nth(index).check();
  await expect(dialog.getByText("20 / 20개 고름", { exact: false })).toBeVisible();
  await expect(boxes.nth(20)).toBeDisabled(); // 21번째는 못 고름
  await boxes.nth(0).uncheck();
  await expect(boxes.nth(20)).toBeEnabled();
  await expect(dialog.getByRole("button", { name: "19개 가져오기" })).toBeEnabled();
});

test("노션 탭: 목록을 못 받으면 이유와 [다시 불러오기], 누르면 목록이 나온다", async ({ context, page }) => {
  await signIn(context, "flaky");
  const dialog = await openNotionTab(page);
  await expect(dialog.getByRole("alert").filter({ hasText: "노션이 잠시 응답하지 않아요" })).toBeVisible();
  await dialog.getByRole("button", { name: "다시 불러오기" }).click();
  await expect(dialog.getByRole("list", { name: "가져올 노션 페이지" }).getByText("트랜잭션 공부")).toBeVisible();
});

test("노션 탭: 가져오기 요청이 실패하면 오류 화면(IMP_01_900)과 이유", async ({ context, page }) => {
  await signIn(context, "importfail");
  const dialog = await openNotionTab(page);
  await dialog.getByRole("list", { name: "가져올 노션 페이지" }).getByRole("checkbox", { name: /트랜잭션 공부/ }).check();
  await dialog.getByRole("button", { name: "1개 가져오기" }).click();
  const error = dialog.locator('[data-screen-id="IMP_01_900"]');
  await expect(error).toBeVisible();
  await expect(error.getByRole("alert")).toContainText("노션이 잠시 응답하지 않아요");
});

test("설정: [연결 끊기]가 실패하면 이유가 보이고 버튼이 다시 눌린다", async ({ context, page }) => {
  await signIn(context, "disconnectfail");
  await page.goto("/settings");
  const section = page.getByRole("region", { name: "연결" });
  await section.getByRole("button", { name: "연결 끊기" }).click();
  await expect(section.getByRole("alert").filter({ hasText: "연결을 끊지 못했어요" })).toBeVisible();
  await expect(section.getByRole("button", { name: "연결 끊기" })).toBeEnabled();
});
