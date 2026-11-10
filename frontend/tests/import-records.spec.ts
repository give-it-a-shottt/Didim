import { expect, test, type BrowserContext, type Page } from "@playwright/test";

// 기록 추가 모달(F-002): 사이드바 버튼 → 올리기(IMP_01_001) → 결과 요약(003) · 오류(900).
// 서버는 가짜 백엔드(tests/mock-backend.mjs)다. 실제 저장 · 나누기는 backend/tests/test_import_markdown.py가 확인한다.

const VALID_SESSION_TOKEN = "playwright-valid-session-token";

async function signIn(context: BrowserContext) {
  await context.addCookies([
    { name: "didim_session", value: VALID_SESSION_TOKEN, domain: "localhost", path: "/", httpOnly: true },
  ]);
}

function markdownFile(name: string, text: string) {
  return { name, mimeType: "text/markdown", buffer: Buffer.from(text, "utf8") };
}

test("기록 추가 → 마크다운 2개 올리기 → 결과 요약이 보인다", async ({ context, page }) => {
  await signIn(context);
  await page.goto("/home");

  await page.getByRole("button", { name: "+ 기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  await expect(dialog.locator('[data-screen-id="IMP_01_001"]')).toBeVisible();
  await expect(dialog.getByRole("tab", { name: "노션 (4주차)" })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: /^가져오기/ })).toBeDisabled();

  await dialog.getByLabel("프로젝트 · 경험").check();
  await dialog.getByLabel("마크다운 파일").setInputFiles([
    markdownFile("react.md", "# React\n본문"),
    markdownFile("os.md", "# 운영체제\n본문"),
  ]);
  await dialog.getByRole("button", { name: "가져오기 (2개)" }).click();

  const result = dialog.locator('[data-screen-id="IMP_01_003"]');
  await expect(result).toBeVisible();
  await expect(result.getByText("노트", { exact: true }).locator("xpath=..")).toContainText("2");
  await expect(result.getByText("조각", { exact: true }).locator("xpath=..")).toContainText("4");

  await dialog.getByRole("button", { name: "확인" }).click();
  await expect(dialog).toBeHidden();
});

test("파일을 끌어다 놓아도 고른 것과 같이 올라가고, 끄는 동안 파일 칸이 강조된다", async ({ context, page }) => {
  await signIn(context);
  await page.goto("/home");
  await page.getByRole("button", { name: "+ 기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  const selectStep = dialog.locator('[data-screen-id="IMP_01_001"]');
  const fileInput = dialog.getByLabel("마크다운 파일");

  // 브라우저 안에서 파일 2개를 담은 DataTransfer를 만들어 드래그 이벤트로 넘긴다
  const dataTransfer = await page.evaluateHandle(() => {
    const transfer = new DataTransfer();
    transfer.items.add(new File(["# React\n본문"], "react.md", { type: "text/markdown" }));
    transfer.items.add(new File(["# 운영체제\n본문"], "os.md", { type: "text/markdown" }));
    return transfer;
  });

  await selectStep.dispatchEvent("dragenter", { dataTransfer });
  await expect(fileInput).toHaveAttribute("data-dragging", "");
  await selectStep.dispatchEvent("drop", { dataTransfer });
  await expect(fileInput).not.toHaveAttribute("data-dragging", "");
  expect(await fileInput.evaluate((input: HTMLInputElement) => input.files?.length)).toBe(2);

  await dialog.getByRole("button", { name: "가져오기 (2개)" }).click();
  const result = dialog.locator('[data-screen-id="IMP_01_003"]');
  await expect(result.getByText("노트", { exact: true }).locator("xpath=..")).toContainText("2");
});

test("드래그 예외: 파일이 아닌 것은 무시, 안쪽 요소를 지나도 강조 유지, 21개를 놓으면 보내기 전에 막는다", async ({
  context,
  page,
}) => {
  await signIn(context);
  await page.goto("/home");
  await page.getByRole("button", { name: "+ 기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  const selectStep = dialog.locator('[data-screen-id="IMP_01_001"]');
  const fileInput = dialog.getByLabel("마크다운 파일");

  // 글자를 끌어오면(파일 아님) 강조도 드롭도 없다
  const textOnly = await page.evaluateHandle(() => {
    const transfer = new DataTransfer();
    transfer.setData("text/plain", "그냥 글자");
    return transfer;
  });
  await selectStep.dispatchEvent("dragenter", { dataTransfer: textOnly });
  await expect(fileInput).not.toHaveAttribute("data-dragging", "");

  // 파일 21개: 안쪽 요소를 지날 때 enter가 두 번, leave가 한 번 와도 강조가 유지된다
  const many = await page.evaluateHandle(() => {
    const transfer = new DataTransfer();
    for (let index = 0; index < 21; index += 1) {
      transfer.items.add(new File([`# 노트 ${index}`], `n${index}.md`, { type: "text/markdown" }));
    }
    return transfer;
  });
  await selectStep.dispatchEvent("dragenter", { dataTransfer: many });
  await fileInput.dispatchEvent("dragenter", { dataTransfer: many });
  await selectStep.dispatchEvent("dragleave", { dataTransfer: many });
  await expect(fileInput).toHaveAttribute("data-dragging", "");
  await selectStep.dispatchEvent("dragleave", { dataTransfer: many });
  await expect(fileInput).not.toHaveAttribute("data-dragging", "");

  await selectStep.dispatchEvent("drop", { dataTransfer: many });
  await expect(dialog.getByText("한 번에 20개까지 올릴 수 있어요.")).toBeVisible();
  await expect(dialog.getByRole("button", { name: /^가져오기/ })).toBeDisabled();
});

test("21개를 고르거나 합계가 20MB를 넘으면 보내기 전에 막고 이유를 보여 준다", async ({ context, page }) => {
  await signIn(context);
  await page.goto("/home");
  await page.getByRole("button", { name: "+ 기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  const input = dialog.getByLabel("마크다운 파일");

  await input.setInputFiles(Array.from({ length: 21 }, (_, index) => markdownFile(`${index}.md`, "본문")));
  await expect(dialog.getByRole("alert")).toHaveText("한 번에 20개까지 올릴 수 있어요.");
  await expect(dialog.getByRole("button", { name: /^가져오기/ })).toBeDisabled();

  const big = Buffer.alloc(11 * 1024 * 1024, "a");
  await input.setInputFiles([
    { name: "a.md", mimeType: "text/markdown", buffer: big },
    { name: "b.md", mimeType: "text/markdown", buffer: big },
  ]);
  await expect(dialog.getByRole("alert")).toHaveText("한 번에 올릴 수 있는 용량(20MB)을 넘었어요.");
  await expect(dialog.getByRole("button", { name: /^가져오기/ })).toBeDisabled();
});

// 서버 응답 갈래별 화면(F-002 1차 R3-7): 가짜 백엔드 대신 page.route로 응답을 바꿔 끼운다.
async function openAndSubmit(page: Page) {
  await page.goto("/home");
  await page.getByRole("button", { name: "+ 기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  await dialog.getByLabel("마크다운 파일").setInputFiles([markdownFile("a.md", "# A\n본문")]);
  await dialog.getByRole("button", { name: "가져오기 (1개)" }).click();
  return dialog;
}

test("서버 응답별로 맞는 화면이 나온다: 401 · 413 · 네트워크 끊김 · 200인데 JSON 아님", async ({ context, page }) => {
  await signIn(context);

  await page.route("**/api/notes/import", (route) =>
    route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "로그인이 필요해요." }) }),
  );
  let dialog = await openAndSubmit(page);
  await expect(dialog.getByRole("alert")).toHaveText("로그인이 만료되었어요. 다시 로그인해 주세요.");
  await expect(dialog.getByRole("link", { name: "다시 로그인" })).toHaveAttribute("href", "/login");
  await page.unrouteAll();

  await page.route("**/api/notes/import", (route) =>
    route.fulfill({
      status: 413,
      contentType: "application/json",
      body: JSON.stringify({ detail: "한 번에 올릴 수 있는 용량(20MB)을 넘었어요." }),
    }),
  );
  dialog = await openAndSubmit(page);
  await expect(dialog.getByRole("alert")).toHaveText("한 번에 올릴 수 있는 용량(20MB)을 넘었어요.");
  await page.unrouteAll();

  await page.route("**/api/notes/import", (route) => route.abort("connectionreset"));
  dialog = await openAndSubmit(page);
  await expect(dialog.getByRole("alert")).toContainText("네트워크 문제로 올리지 못했어요");
  await page.unrouteAll();

  await page.route("**/api/notes/import", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<html>proxy error</html>" }),
  );
  dialog = await openAndSubmit(page);
  await expect(dialog.locator('[data-screen-id="IMP_01_900"]')).toBeVisible(); // '처리 중'에 멈추지 않는다
  await expect(dialog.getByRole("button", { name: "닫기" })).toBeVisible();
});

test("처리 중에는 Esc를 눌러도 모달이 닫히지 않고, 다시 열면 올리기 단계부터 시작한다", async ({ context, page }) => {
  await signIn(context);
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/notes/import", async (route) => {
    await gate; // 응답을 붙잡아 '처리 중'을 유지한다
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        summary: { notes: 1, chunks: 1, duplicates: 0, failed: 0 },
        imported: [{ filename: "a.md", note_id: 1, title: "A", chunk_count: 1 }],
        duplicates: [],
        failed: [],
      }),
    });
  });

  const dialog = await openAndSubmit(page);
  await expect(dialog.locator('[data-screen-id="IMP_01_002"]')).toBeVisible();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await expect(dialog.locator('[data-screen-id="IMP_01_002"]')).toBeVisible();
  // 브라우저가 Esc 막기를 무시하고 강제로 닫는 경우를 직접 만든다 → 다시 열려야 한다(3차 R3: 다시 열기 코드를 실제로 타는지)
  await page.evaluate(() => document.querySelector("dialog")?.close());
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[data-screen-id="IMP_01_002"]')).toBeVisible();

  release();
  await expect(dialog.locator('[data-screen-id="IMP_01_003"]')).toBeVisible();
  await dialog.getByRole("button", { name: "확인" }).click();
  await expect(dialog).toBeHidden();

  await page.getByRole("button", { name: "+ 기록 추가" }).click();
  await expect(dialog.locator('[data-screen-id="IMP_01_001"]')).toBeVisible();
  await expect(dialog.getByRole("button", { name: /^가져오기/ })).toBeDisabled(); // 이전 파일 선택이 지워짐
});

test("중복 · 실패가 섞인 결과는 요약과 함께 목록으로 보인다", async ({ context, page }) => {
  await signIn(context);
  await page.route("**/api/notes/import", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        summary: { notes: 1, chunks: 3, duplicates: 1, failed: 1 },
        imported: [{ filename: "a.md", note_id: 1, title: "A", chunk_count: 3 }],
        duplicates: [{ filename: "copy.md", existing_note_id: 1, existing_title: "A" }],
        failed: [{ filename: "memo.txt", reason: "마크다운(.md) 파일만 올릴 수 있어요." }],
      }),
    }),
  );
  const dialog = await openAndSubmit(page);
  const result = dialog.locator('[data-screen-id="IMP_01_003"]');
  await expect(result).toBeVisible();
  await expect(result.getByRole("list", { name: "중복이라 저장하지 않은 파일" })).toContainText("copy.md");
  await expect(result.getByRole("list", { name: "읽지 못한 파일" })).toContainText("memo.txt");
});

test("하나도 읽지 못하면 오류(IMP_01_900)와 이유가 보이고, 다시 시도하면 올리기로 돌아간다", async ({
  context,
  page,
}) => {
  await signIn(context);
  await page.goto("/home");

  await page.getByRole("button", { name: "+ 기록 추가" }).click();
  const dialog = page.getByRole("dialog", { name: "기록 추가" });
  await dialog.getByLabel("마크다운 파일").setInputFiles([
    { name: "memo.txt", mimeType: "text/plain", buffer: Buffer.from("메모", "utf8") },
  ]);
  await dialog.getByRole("button", { name: "가져오기 (1개)" }).click();

  const error = dialog.locator('[data-screen-id="IMP_01_900"]');
  await expect(error).toBeVisible();
  await expect(error.getByRole("alert")).toHaveText("노트를 읽지 못했어요.");
  await expect(error.getByText("memo.txt")).toBeVisible();
  await expect(error.getByText(/마크다운\(\.md\) 파일만/)).toBeVisible();

  await dialog.getByRole("button", { name: "다시 시도" }).click();
  await expect(dialog.locator('[data-screen-id="IMP_01_001"]')).toBeVisible();
});
