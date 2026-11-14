import { type BrowserContext, type Page, expect, test } from "@playwright/test";

// 근거 달린 자소서(F-008) 화면: 자소서 탭(사이드바 접힘) · 근거 칩 · 근거 없음 · 고른 문장의 근거(명조) · 고치기 · 카드 연결 ·
// 초안 쓰기(쓰는 중 · 빈 상태 · 실패) · 이 문항 완료 · 문항 고치기 · 제출 확인창.
// 가짜 백엔드(tests/mock-backend.mjs)의 공고 910~917을 쓴다(테스트마다 다른 공고 — 병렬로 돌아도 서로 안 건드림).
const VALID_SESSION_TOKEN = "playwright-valid-session-token";

async function logIn(context: BrowserContext) {
  await context.addCookies([
    { name: "didim_session", value: VALID_SESSION_TOKEN, domain: "localhost", path: "/", httpOnly: true },
  ]);
}

const editor = (page: Page) => page.getByRole("region", { name: "1번 문항" });
const sentence = (page: Page, number: number) => editor(page).getByRole("button", { name: new RegExp(`^문장 ${number}( |:)`) });

test("자소서 탭: 넓은 화면에서도 사이드바가 접히고, 문장마다 근거 칩 · 근거 없음이 보인다", async ({ context, page }) => {
  await logIn(context);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/applications/910/draft");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("초안회사 · 개발자");
  await expect(page.getByRole("navigation", { name: "지원 상세 탭" }).getByRole("link", { name: "자소서" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  const sidebar = page.locator("aside").filter({ has: page.getByRole("navigation", { name: "메인 메뉴" }) });
  expect((await sidebar.boundingBox())?.width).toBe(56); // Figma: 자소서 에디터는 접힘(56)

  await expect(editor(page)).toContainText("700자 · AI 초안에서 내가 고친 부분 0%");
  await expect(sentence(page, 1)).toContainText("useEffect로 구독 정리"); // 근거 칩 = 카드 제목
  await expect(sentence(page, 2)).toContainText("근거 없음");
  const aside = page.getByRole("complementary", { name: "검사 · 근거" });
  await expect(aside).toContainText("문장 3개 중 2개에 근거가 있어요");
  await expect(aside).toContainText("근거 없는 문장 1개는 제출 전에 확인해 주세요.");
  await expect(aside.getByRole("region", { name: /문장 2 · 근거 없음/ })).toBeVisible();

  // 문장을 누르면 오른쪽에 근거 — 카드 칸 원문(명조 인용) + 출처
  await sentence(page, 1).click();
  const evidence = aside.getByRole("region", { name: "선택한 문장 1의 근거" });
  await expect(evidence.getByRole("blockquote")).toContainText("useEffect는 그려진 뒤 부수 효과를 실행해요.");
  await expect(evidence).toContainText("노트 · React 정리 · 상황 칸 원문 인용");

  // 공고 분석 탭으로 가면 사이드바가 다시 펼쳐진다
  await page.getByRole("link", { name: "공고 분석" }).click();
  await expect(page).toHaveURL(/\/applications\/910\/analysis$/);
  await expect.poll(async () => (await sidebar.boundingBox())?.width).toBe(240);
});

test("문장 고치기 · 새 문장 · 지우기: 고친 문장은 근거를 그대로 두고 '내가 고침', 새 문장은 근거 없음", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/915/draft");

  await sentence(page, 1).click();
  const aside = page.getByRole("complementary", { name: "검사 · 근거" });
  await aside.getByRole("region", { name: "선택한 문장 1의 근거" }).getByRole("button", { name: "직접 고치기" }).click();
  const box = page.getByLabel("고칠 문장");
  await expect(box).toHaveValue("React 화면에서 구독을 정리하는 일을 맡았습니다.");
  await expect(editor(page)).toContainText("원래 문장: React 화면에서 구독을 정리하는 일을 맡았습니다.");
  await box.fill("React 화면의 구독 정리를 맡았습니다.");
  await page.getByRole("button", { name: "이 문장 적용" }).click();
  await expect(sentence(page, 1)).toContainText("내가 고침");
  await expect(sentence(page, 1)).toContainText("useEffect로 구독 정리");
  // 저장하면 문장 번호가 바뀌어도 고른 문장은 그대로(3차 리뷰 R1)
  await expect(aside.getByRole("region", { name: "선택한 문장 1의 근거" })).toBeVisible();
  await expect(page.getByText(/자동 저장됨 · \d\d:\d\d/)).toBeVisible();

  // 근거 없는 문장 뒤에 새 문장 → 근거 없음
  await aside.getByRole("region", { name: /문장 2 · 근거 없음/ }).getByRole("button", { name: "뒤에 문장 넣기" }).click();
  await page.getByLabel("새 문장").fill("내가 새로 쓴 문장입니다.");
  await page.getByRole("button", { name: "이 문장 적용" }).click();
  await expect(sentence(page, 3)).toContainText("내가 새로 쓴 문장입니다.");
  await expect(sentence(page, 3)).toContainText("근거 없음");
  await expect(aside).toContainText("문장 4개 중 2개에 근거가 있어요");

  // 지우기(확인창)
  page.once("dialog", (dialog) => void dialog.accept());
  await aside.getByRole("region", { name: /문장 2 · 근거 없음/ }).getByRole("button", { name: "지우기" }).click();
  await expect(aside).toContainText("문장 3개 중 2개에 근거가 있어요");
  await expect(editor(page)).not.toContainText("이탈률이 30%");
});

test("카드 연결: 근거 없는 문장에 내 카드 칸 글을 붙이면 근거가 생긴다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/916/draft");

  const aside = page.getByRole("complementary", { name: "검사 · 근거" });
  await aside.getByRole("region", { name: /문장 2 · 근거 없음/ }).getByRole("button", { name: "카드 연결" }).click();
  const dialog = page.getByRole("dialog", { name: "카드 연결" });
  await expect(dialog).toContainText("그 결과 페이지 이탈률이 30% 줄었습니다.");
  await expect(dialog.getByRole("button", { name: /useEffect로 구독 정리/ })).toContainText("이 공고에 매칭됨");
  await dialog.getByLabel("카드 검색").fill("고칠");
  await dialog.getByRole("button", { name: /고칠 카드/ }).click();
  await dialog.getByRole("button", { name: /행동 · 원문 인용/ }).click();

  await expect(dialog).toBeHidden();
  await expect(sentence(page, 2)).toContainText("고칠 카드");
  await expect(aside).toContainText("문장 3개 중 3개에 근거가 있어요");
  await sentence(page, 2).click();
  const evidence = aside.getByRole("region", { name: "선택한 문장 2의 근거" });
  await expect(evidence.getByRole("blockquote")).toContainText("상태를 바꾸면 다시 그려져요.");
  await expect(evidence).toContainText("행동 칸 원문 인용 · 내가 연결함");
});

test("초안 쓰기: 보내는 범위를 알리고, 쓰는 중 단계를 보여 준 뒤 초안이 나온다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/911/draft");

  await expect(editor(page)).toContainText("이 공고에 매칭된 내 카드 1장의 제목 · 칸 글과 문항을 AI에 보내 700자 안의 초안을 써요");
  await expect(page.getByRole("button", { name: "지원 동기" })).toContainText("시작 전");
  await page.getByRole("button", { name: "초안 쓰기" }).click();
  const progress = editor(page).getByRole("status");
  await expect(progress).toContainText("카드 1장에서 초안을 만들고 있어요");
  await expect(progress).toContainText("useEffect로 구독 정리");
  await expect(sentence(page, 1)).toContainText("useEffect로 구독 정리");
  await expect(sentence(page, 2)).toContainText("근거 없음");
  await expect(page.getByRole("button", { name: /지원 동기/ })).toContainText("작성 중");

  // 이 문항 완료 → 완료 배지, 완료 풀기
  await page.getByRole("button", { name: "이 문항 완료" }).click();
  await expect(page.getByRole("button", { name: /지원 동기/ })).toContainText("완료");
  await page.getByRole("button", { name: "완료 풀기" }).click();
  await expect(page.getByRole("button", { name: /지원 동기/ })).toContainText("작성 중");
});

test("매칭 카드가 없으면 초안 쓰기를 막고 카드 만들기로 안내한다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/912/draft");
  await expect(editor(page)).toContainText("이 공고에 맞는 경험 카드가 아직 없어요");
  await expect(page.getByRole("button", { name: "초안 쓰기" })).toHaveCount(0);
  await expect(editor(page).getByRole("link", { name: "카드 만들기" })).toHaveAttribute("href", "/cards");
  await expect(editor(page).getByRole("link", { name: "공고 분석으로" })).toHaveAttribute("href", "/applications/912/analysis");
});

test("초안 쓰기가 실패하면 이유와 [다시 시도]를 보여 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/913/draft");
  await page.getByRole("button", { name: "초안 쓰기" }).click();
  await expect(editor(page).getByRole("alert")).toContainText("지금은 AI에 연결할 수 없어요.");
  await expect(editor(page).getByRole("button", { name: "다시 시도" })).toBeVisible();
});

test("제출로 바꾸기: 근거 없는 문장이 있으면 확인창을 띄우고, 취소하면 상태를 바꾸지 않는다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/914/draft");
  const status = page.getByLabel("상태");
  await expect(status).toHaveValue("ready");

  const messages: string[] = [];
  page.once("dialog", (dialog) => {
    messages.push(dialog.message());
    void dialog.dismiss();
  });
  await page.getByRole("button", { name: "제출로 바꾸기" }).click();
  await expect.poll(() => messages).toEqual(["근거 없는 문장이 1개 있어요. 그래도 '제출'로 바꿀까요?"]);
  await expect(status).toHaveValue("ready");

  page.once("dialog", (dialog) => void dialog.accept());
  await status.selectOption("submitted"); // 상태 선택에서 골라도 같은 확인창
  await expect(status).toHaveValue("submitted");
  await expect(page.getByRole("button", { name: "제출로 바꾸기" })).toHaveCount(0);
});

test("문항 고치기: 문항을 더하고, 초안 있는 문항을 지우면 확인창 뒤 초안도 같이 지운다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/917/draft");

  await page.getByRole("button", { name: "문항 고치기" }).click();
  await page.getByRole("button", { name: "문항 추가" }).click();
  await page.getByLabel("2번 문항", { exact: true }).fill("협업 경험을 적어 주세요.");
  await page.getByRole("button", { name: "저장" }).click();
  await expect(page.getByRole("button", { name: /2\. 협업 경험을 적어 주세요\./ })).toContainText("시작 전");

  await page.getByRole("button", { name: "문항 고치기" }).click();
  await page.getByRole("group", { name: "1번 문항" }).getByRole("button", { name: "지우기" }).click();
  const messages: string[] = [];
  page.once("dialog", (dialog) => {
    messages.push(dialog.message());
    void dialog.accept();
  });
  await page.getByRole("button", { name: "저장" }).click();
  await expect.poll(() => messages).toEqual(["초안이 있는 문항 1개를 지우면 초안도 같이 지워져요. 지울까요?"]);
  await expect(page.getByRole("button", { name: /1\. 협업 경험을 적어 주세요\./ })).toBeVisible();
  await expect(page.getByRole("button", { name: /지원 동기/ })).toHaveCount(0);
});

test("문장 저장이 막히면 서버 문구를 보여 주고, 다른 곳에서 먼저 바뀌었으면(409) 새로 받아 보여 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/918/draft");

  await sentence(page, 1).click();
  const aside = page.getByRole("complementary", { name: "검사 · 근거" });
  await aside.getByRole("region", { name: "선택한 문장 1의 근거" }).getByRole("button", { name: "직접 고치기" }).click();
  await page.getByLabel("고칠 문장").fill("[422] 너무 긴 문장");
  await page.getByRole("button", { name: "이 문장 적용" }).click();
  await expect(editor(page).getByRole("alert")).toHaveText("문장 하나는 500자까지 쓸 수 있어요.");
  await expect(page.getByLabel("고칠 문장")).toHaveValue("[422] 너무 긴 문장"); // 고치던 글은 그대로

  await page.getByLabel("고칠 문장").fill("[409] 내 탭에서 고친 문장");
  await page.getByRole("button", { name: "이 문장 적용" }).click();
  await expect(editor(page).getByRole("alert")).toContainText("다른 곳에서 이 초안이 먼저 바뀌었어요");
  await expect(sentence(page, 1)).toContainText("다른 탭에서 고친 문장입니다."); // 새로 받은 초안
});

test("자소서를 불러오지 못하면 알림을 보여 주고, 없는 공고는 찾을 수 없다고 나온다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/919/draft");
  await expect(page.getByRole("alert").filter({ hasText: "자소서를 불러오지 못했어요" })).toBeVisible();
  await page.goto("/applications/999999/draft");
  await expect(page.getByText("404")).toBeVisible();
});

test("완료 표시가 실패하면 문구를 보여 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/920/draft");
  await page.getByRole("button", { name: "이 문항 완료" }).click();
  await expect(editor(page).getByRole("alert")).toHaveText("완료 표시를 바꾸지 못했어요. 잠시 뒤 다시 시도해 주세요.");
  await expect(page.getByRole("button", { name: /지원 동기/ })).toContainText("작성 중");
});

test("초안 쓰기가 404로 실패하면 다시 받고, 다시 받기도 실패하면 알림과 [다시 불러오기]를 보여 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/921/draft");
  await page.getByRole("button", { name: "초안 쓰기" }).click();
  await expect(editor(page).getByRole("alert")).toContainText("자소서 문항을 찾을 수 없어요.");
  const banner = page.getByRole("alert").filter({ hasText: "최신 자소서를 불러오지 못했어요" });
  await expect(banner).toBeVisible();
  await expect(banner.getByRole("button", { name: "다시 불러오기" })).toBeVisible();
});

test("문항 저장: 서버가 거부하면 문구를 보여 주고, 다른 곳에서 먼저 바뀌었으면(409) 새 목록을 받아 보여 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/922/draft");

  await page.getByRole("button", { name: "문항 고치기" }).click();
  const firstQuestion = page.getByRole("textbox", { name: "1번 문항", exact: true });
  await firstQuestion.fill("[422] 너무 긴 문항");
  await page.getByRole("button", { name: "저장" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "자소서 문항은 500자까지 쓸 수 있어요." })).toBeVisible();

  await firstQuestion.fill("[409] 옛 목록으로 저장");
  await page.getByRole("button", { name: "저장" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "다른 곳에서 문항이 먼저 바뀌었어요" })).toBeVisible();
  await page.getByRole("button", { name: "취소" }).click();
  await expect(page.getByRole("button", { name: /다른 탭에서 넣은 문항/ })).toBeVisible();
});

