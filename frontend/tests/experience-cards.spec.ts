import { type BrowserContext, expect, test } from "@playwright/test";

// 경험 카드(F-006) 화면: 카드 목록(탭) · 노트 상세 [카드 후보 찾기] · 후보 검토 시트 · 카드 상세 고치기.
// 가짜 백엔드(tests/mock-backend.mjs)의 카드 801 · 802 · 803 · 811 · 812와 노트 4 · 6 · 7을 쓴다(테스트마다 다른 카드).
const VALID_SESSION_TOKEN = "playwright-valid-session-token";

async function logIn(context: BrowserContext) {
  await context.addCookies([
    { name: "didim_session", value: VALID_SESSION_TOKEN, domain: "localhost", path: "/", httpOnly: true },
  ]);
}

test("카드 목록: 내 카드 탭에 근거 · 빈칸 수가 보이고, 후보 탭으로 바꾸면 후보가 보인다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/cards");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("경험 카드");
  const tabs = page.getByRole("navigation", { name: "카드 종류" });
  await expect(tabs.getByRole("link", { name: /내 카드/ })).toHaveAttribute("aria-current", "page");
  const tile = page.getByRole("link", { name: /useEffect로 구독 정리/ });
  await expect(tile).toHaveAttribute("href", "/cards/801");
  await expect(tile).toContainText("근거 2 · 빈칸 2");
  await expect(tile).toContainText("React 정리");

  await tabs.getByRole("link", { name: /검토할 후보/ }).click();

  await expect(page).toHaveURL(/\/cards\?tab=candidate$/);
  await expect(page.getByRole("list", { name: "검토할 후보" }).getByRole("link", { name: /상태 바꾸기 실험/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /후보 \d+개 검토/ })).toBeVisible();
});

test("노트 상세 [카드 후보 찾기]: 보내는 범위를 먼저 알리고, 찾으면 결과와 [후보 검토]가 나온다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records/6");

  const panel = page.getByRole("region", { name: "경험 카드" });
  await expect(panel).toContainText("오늘 AI 사용량 1회를 써요");
  await panel.getByRole("button", { name: "카드 후보 찾기" }).click();

  await expect(panel.getByRole("status")).toContainText("카드 후보 1개를 찾았어요");
  await expect(panel).toContainText("빈칸으로 돌렸어요");
  await expect(panel.getByRole("button", { name: "후보 1개 검토" })).toBeVisible();
});

test("노트 상세 [카드 후보 찾기]: 하루 상한(429)이면 서버 문구를 보여 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records/7");

  const panel = page.getByRole("region", { name: "경험 카드" });
  await panel.getByRole("button", { name: "카드 후보 찾기" }).click();

  await expect(panel.getByRole("alert")).toContainText("오늘 AI 사용량(30회)을 다 썼어요");
});

test("후보 검토 시트: 원문 인용을 보고 제목을 고쳐 저장하고, 다음 후보는 버린다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records/4");

  const panel = page.getByRole("region", { name: "경험 카드" });
  await panel.getByRole("button", { name: "후보 2개 검토" }).click();

  const sheet = page.getByRole("dialog", { name: "카드 후보 2개 중 1" });
  await expect(sheet).toBeVisible();
  const title = sheet.getByRole("textbox", { name: /카드 제목/ });
  await expect(title).toHaveValue("코드 블록 정리");
  // 칸 글은 내 노트 원문 그대로(명조 인용) — 원문에 없는 칸은 안내
  await expect(sheet.getByRole("region", { name: "상황" }).locator("blockquote")).toHaveText(
    "useEffect는 그려진 뒤 부수 효과를 실행해요.",
  );
  await expect(sheet.getByRole("region", { name: "결과" })).toContainText("원문에 없어요 — 저장한 뒤 직접 채워요");

  await title.fill("useEffect 정리 경험");
  await sheet.getByRole("button", { name: "카드로 저장" }).click();

  await expect(page.getByRole("heading", { name: "카드 후보 2개 중 2" })).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "버리기" }).click();

  const done = page.getByRole("dialog", { name: "후보를 모두 봤어요" });
  await expect(done).toContainText("카드 1장을 저장했어요.");
  await expect(done.getByRole("link", { name: "빈칸 채우러 가기" })).toHaveAttribute("href", "/cards/811");

  await done.getByRole("button", { name: "닫기" }).click();
  await expect(panel).toContainText("이 노트의 후보는 모두 검토했어요.");
  await expect(panel).toContainText("저장한 카드 1장");
});

test("카드 상세: 빈칸에 내 답을 쓰고 저장하면 빈칸이 줄고, 인용을 빼면 근거가 줄어든다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/cards/803");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("고칠 카드");
  await expect(page.getByRole("heading", { name: "근거 2" })).toBeVisible();
  const task = page.getByRole("region", { name: "과제" });
  await expect(task).toContainText("빈칸 질문");
  await expect(task).toContainText("AI는 질문만 하고, 답은 직접 쓴 내용만 저장해요.");

  await task.getByRole("textbox", { name: "과제 — 내 답" }).fill("구독을 정리하는 일을 맡았다");
  await page.getByRole("button", { name: "저장", exact: true }).click();

  await expect(page.getByRole("status").filter({ hasText: "저장했어요" })).toBeVisible();
  await expect(page.getByText(/빈칸 1 · React 정리/)).toBeVisible();

  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("region", { name: "행동" }).getByRole("button", { name: "인용 빼기" }).click();

  await expect(page.getByRole("heading", { name: "근거 1" })).toBeVisible();
  await expect(page.getByRole("region", { name: "행동" }).locator("blockquote")).toHaveCount(0);
});

test("없는 카드 · 이상한 카드 주소는 찾을 수 없다고 나온다", async ({ context, page }) => {
  await logIn(context);
  // 스트리밍 렌더링이라 상태 코드 대신 화면 문구로 확인한다(노트 상세 테스트와 같은 방식)
  await page.goto("/cards/99999");
  await expect(page.getByText("This page could not be found.")).toBeVisible();
  await page.goto("/cards/abc");
  await expect(page.getByText("This page could not be found.")).toBeVisible();
});

// --- 예외 경로 (F-006 1차 리뷰 R3) — 노트 8 · 9 · 10, 카드 804 · 1001 · 1002 ---

test("노트 상세 [카드 후보 찾기]: 경험을 찾지 못하면(0개) 다시 시도할 수 있다고 알린다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records/8");

  const panel = page.getByRole("region", { name: "경험 카드" });
  await panel.getByRole("button", { name: "카드 후보 찾기" }).click();

  await expect(panel.getByRole("status")).toContainText("경험을 찾지 못했어요. 다시 시도할 수 있어요.");
  await expect(panel.getByRole("button", { name: /후보 \d+개 검토/ })).toHaveCount(0);
});

test("노트 상세 [카드 후보 찾기]: 다른 탭이 먼저 찾았으면(409) 문구를 보여 주고 새로 고쳐 후보 검토로 이어진다", async ({
  context,
  page,
}) => {
  await logIn(context);
  await page.goto("/records/9");

  const panel = page.getByRole("region", { name: "경험 카드" });
  await panel.getByRole("button", { name: "카드 후보 찾기" }).click();

  await expect(panel.getByRole("alert")).toContainText("이미 카드 후보를 찾았어요");
  await expect(panel.getByRole("button", { name: "후보 1개 검토" })).toBeVisible();
});

test("후보 검토 시트: 후보 하나를 불러오지 못하면 문구와 [다음 후보 보기]로 넘어갈 수 있다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records/10");

  await page.getByRole("region", { name: "경험 카드" }).getByRole("button", { name: "후보 2개 검토" }).click();

  const sheet = page.getByRole("dialog", { name: "카드 후보 2개 중 1" });
  await expect(sheet.getByRole("alert")).toContainText("카드를 불러오지 못했어요");
  await sheet.getByRole("button", { name: "다음 후보 보기" }).click();

  const next = page.getByRole("dialog", { name: "카드 후보 2개 중 2" });
  await expect(next.getByRole("textbox", { name: /카드 제목/ })).toHaveValue("멀쩡한 후보");
});

// 주의: 이 테스트는 가짜 서버(mock-backend.mjs)의 카드 804 상태를 바꾼다(과제 답이 저장됨). 같은 서버로 두 번 돌리면
// 첫 단언 '빈칸 3'이 깨진다 — 재시도(retries)나 서버 재사용(reuseExistingServer)을 켜려면 804를 초기화하는 길을 먼저 둔다.
test("카드 상세: 여러 칸을 저장하다 중간에 실패하면 앞 칸은 반영되고, 서버 문구와 함께 실패한 칸의 입력은 남는다", async ({
  context,
  page,
}) => {
  await logIn(context);
  await page.goto("/cards/804");

  await expect(page.getByText(/빈칸 3 · React 정리/)).toBeVisible();
  await page.getByRole("region", { name: "과제" }).getByRole("textbox", { name: "과제 — 내 답" }).fill("저장되는 답");
  const result = page.getByRole("region", { name: "결과" }).getByRole("textbox", { name: "결과 — 내 답" });
  await result.fill("실패해도 남아야 하는 답");
  await page.getByRole("button", { name: "저장", exact: true }).click();

  await expect(page.getByRole("alert").filter({ hasText: "칸을 저장하지 못했어요" })).toBeVisible();
  await expect(result).toHaveValue("실패해도 남아야 하는 답");

  // 새로 고치면 서버 상태: 과제 칸만 저장됐다(빈칸 3 → 2)
  await page.reload();
  await expect(page.getByText(/빈칸 2 · React 정리/)).toBeVisible();
  await expect(page.getByRole("region", { name: "과제" }).getByRole("textbox", { name: "과제 — 내 답" })).toHaveValue("저장되는 답");
});
