import { type BrowserContext, expect, test } from "@playwright/test";

// 면접 연습(F-009) 화면: 카드 상세의 [면접 질문 만들기] · '이 카드의 면접 질문', 지원 상세 [면접 연습] 탭(질문 목록 · 카드 태그 ·
// 메모 · 선택한 질문의 근거 · 맞는 역량 · 질문 없는 카드 · 분석 전 안내).
// 가짜 백엔드(tests/mock-backend.mjs)의 카드 831~834 · 공고 930 · 931을 쓴다(테스트마다 다른 카드 · 공고 — 병렬로 돌아도 안 건드림).

const VALID_SESSION_TOKEN = "playwright-valid-session-token";

async function logIn(context: BrowserContext) {
  await context.addCookies([
    { name: "didim_session", value: VALID_SESSION_TOKEN, domain: "localhost", path: "/", httpOnly: true },
  ]);
}

test("카드 상세: [면접 질문 만들기]를 누르면 질문이 생기고 버튼이 사라진다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/cards/831");

  const questions = page.getByRole("region", { name: /이 카드의 면접 질문/ });
  await expect(questions).toContainText("이 카드의 면접 질문 0");
  await expect(questions).toContainText("이 카드의 칸 글만 AI에 보내요"); // 보내는 범위 안내(원칙 6)
  await page.getByRole("button", { name: "면접 질문 만들기" }).click();

  // 근거가 맞는 질문이 3개보다 적으면 그대로 저장하고 몇 개만 만들었는지 알린다(Q-027)
  await expect(page.getByRole("status").filter({ hasText: "근거를 찾은 질문 2개를 만들었어요" })).toBeVisible();
  await expect(questions).toContainText("이 카드의 면접 질문 2");
  await expect(questions).toContainText("그 방법을 고른 이유는 무엇인가요?");
  await expect(page.getByRole("button", { name: "면접 질문 만들기" })).toHaveCount(0); // 카드당 한 번
});

test("카드 상세: 질문이 있으면 목록과 '근거가 바뀜'을 보여 주고, 후보 카드는 저장 안내", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/cards/832");
  const questions = page.getByRole("region", { name: /이 카드의 면접 질문/ });
  await expect(questions).toContainText("이 카드의 면접 질문 3");
  await expect(questions.getByRole("listitem").filter({ hasText: "왜 상태를 바꾸는 방법을 골랐나요?" })).toContainText(
    "카드 글이 바뀌어 근거를 찾을 수 없어요",
  );
  await expect(page.getByRole("button", { name: "면접 질문 만들기" })).toHaveCount(0);

  await page.goto("/cards/802"); // 후보 카드
  await expect(page.getByRole("region", { name: /이 카드의 면접 질문/ })).toContainText("카드로 저장하면 면접 질문을 만들 수 있어요.");
  await expect(page.getByRole("button", { name: "면접 질문 만들기" })).toHaveCount(0);
});

test("카드 상세: 질문 만들기가 실패하면 서버 문구를 보여 주고 다시 누를 수 있다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/cards/833");
  await page.getByRole("button", { name: "면접 질문 만들기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "AI 서버에 연결하지 못했어요" })).toBeVisible();
  await expect(page.getByRole("button", { name: "면접 질문 만들기" })).toBeEnabled();
});

test("면접 연습 탭: 질문 목록 · 카드 태그 · 근거 · 맞는 역량 · 질문 없는 카드 · 메모 저장", async ({ context, page }) => {
  await logIn(context);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/applications/930/interview");

  await expect(page.getByRole("navigation", { name: "지원 상세 탭" }).getByRole("link", { name: "면접 연습" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  const list = page.getByRole("region", { name: /예상 질문/ });
  await expect(list.getByRole("heading", { level: 2 })).toHaveText(/예상 질문 3\s*답함 1\/3/);
  await expect(list).toContainText("이 공고에 매칭된 카드 1장에서 모았어요 · 겹치는 질문은 하나로");
  await expect(list.getByRole("listitem").first().getByRole("link", { name: "Redis 재설계" })).toHaveAttribute("href", "/cards/832");
  await expect(list.getByLabel("그 상황에서 무엇이 문제였나요? — 내 답 메모")).toHaveValue("그려진 뒤 실행되는 점을 먼저 말한다");

  // 처음 고른 질문의 근거(카드 칸 원문 인용) · 출처 · 이 카드가 맞는 역량
  const evidence = page.getByRole("region", { name: "선택한 질문의 근거" });
  await expect(evidence.getByRole("blockquote")).toHaveText("useEffect는 그려진 뒤");
  await expect(evidence).toContainText("Redis 재설계 · 상황 · React 정리");
  await expect(evidence.getByRole("listitem")).toHaveText(["React 화면 개발", "클라우드 배포"]);

  // 질문을 고르면 근거가 바뀌고, 카드 글이 바뀐 질문은 표시한다
  await list.getByRole("button", { name: "왜 상태를 바꾸는 방법을 골랐나요?" }).click();
  await expect(evidence.getByRole("blockquote")).toHaveText("상태를 바꾸면 다시");
  await expect(evidence).toContainText("카드 글이 바뀌어 이 인용을 찾을 수 없어요");

  // 질문 없는 카드는 카드 상세로 잇는다
  await expect(list).toContainText("질문 없는 카드 1장");
  await expect(list.getByRole("link", { name: "질문 없는 카드" })).toHaveAttribute("href", "/cards/834");

  // 메모를 쓰고 칸을 벗어나면 저장 — 답한 수가 늘어난다
  const memo = list.getByLabel("왜 상태를 바꾸는 방법을 골랐나요? — 내 답 메모");
  await memo.fill("로그인 사용자만 서버에 둔 이유부터");
  await memo.blur();
  await expect(list.getByRole("status").filter({ hasText: "메모를 저장했어요" })).toBeVisible();
  await expect(list.getByRole("heading", { level: 2 })).toHaveText(/답함 2\/3/);

  // 저장이 실패하면 서버 문구, 쓴 글은 그대로
  const failing = list.getByLabel("다시 그려지는 걸 어떻게 확인했나요? — 내 답 메모");
  await failing.fill("렌더 횟수를 셌다");
  await failing.blur();
  await expect(list.getByRole("alert").filter({ hasText: "메모를 저장하지 못했어요" })).toBeVisible();
  await expect(failing).toHaveValue("렌더 횟수를 셌다");
});

test("면접 연습 탭: 공고 분석 전이면 분석으로 안내한다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/931/interview");
  const list = page.getByRole("region", { name: /예상 질문/ });
  await expect(list.getByRole("status")).toContainText("공고 분석에서 내 카드를 매칭하면");
  await expect(list.getByRole("link", { name: "공고 분석으로" })).toHaveAttribute("href", "/applications/931/analysis");
});

// --- 1차 리뷰 반영(R1 · R3) ---

test("카드 상세: 질문은 만들었는데 카드 다시 받기가 실패하면 새로 고침을 안내한다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/cards/835");
  await page.getByRole("button", { name: "면접 질문 만들기" }).click();
  await expect(page.getByRole("status").filter({ hasText: "질문 2개를 만들었어요" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "질문 목록을 불러오지 못했어요" })).toHaveText(
    "질문 목록을 불러오지 못했어요. 새로 고침해 확인해 주세요.",
  );
  await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0); // 실패로 보이지 않는다(Next 경로 안내 빈 alert 제외)
});

test("면접 연습 탭: 매칭 카드가 없을 때 · 질문 없는 카드만 있을 때 · 불러오기 실패", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/932/interview");
  await expect(page.getByRole("region", { name: /예상 질문/ }).getByRole("status")).toContainText("이 공고에 매칭된 경험 카드가 없어요");

  await page.goto("/applications/933/interview");
  const list = page.getByRole("region", { name: /예상 질문/ });
  await expect(list.getByRole("status")).toContainText("매칭된 카드 1장에 아직 면접 질문이 없어요");
  await expect(list.getByRole("link", { name: "질문 없는 카드" })).toHaveAttribute("href", "/cards/834");

  await page.goto("/applications/934/interview");
  await expect(page.getByRole("alert").filter({ hasText: "면접 질문을 불러오지 못했어요" })).toHaveText(
    "면접 질문을 불러오지 못했어요. 잠시 뒤 다시 해 주세요.",
  );
});

test("면접 연습 탭: 메모를 저장하는 동안 이어 쓴 글도 지워지지 않고 저장된다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/935/interview");
  const memo = page.getByLabel("느린 메모 질문인가요? — 내 답 메모");
  await memo.fill("첫 줄");
  await memo.blur(); // 저장 시작(1.5초)
  await memo.fill("첫 줄 그리고 둘째 줄"); // 저장 중에 이어 씀
  await memo.blur(); // 저장 중이라 건너뜀 → 끝난 뒤 다시 보냄
  await expect(memo).toHaveValue("첫 줄 그리고 둘째 줄");
  await expect(page.getByRole("status").filter({ hasText: "메모를 저장했어요" })).toBeVisible({ timeout: 8000 });
  await expect(memo).toHaveValue("첫 줄 그리고 둘째 줄");

  await page.reload(); // 서버에도 마지막 글이 남았다
  await expect(page.getByLabel("느린 메모 질문인가요? — 내 답 메모")).toHaveValue("첫 줄 그리고 둘째 줄");
});

test("카드 상세: 다른 탭에서 먼저 만들었으면(409) 서버 문구와 함께 그 질문을 보여 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/cards/837");
  await page.getByRole("button", { name: "면접 질문 만들기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "이미 면접 질문이 있어요" })).toBeVisible();
  const questions = page.getByRole("region", { name: /이 카드의 면접 질문/ });
  await expect(questions).toContainText("이 카드의 면접 질문 1");
  await expect(questions).toContainText("다른 탭에서 만든 질문인가요?");
  await expect(page.getByRole("button", { name: "면접 질문 만들기" })).toHaveCount(0);
});

test("카드 상세: 409 뒤 카드 다시 받기까지 실패하면 새로 고침을 안내한다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/cards/838");
  await page.getByRole("button", { name: "면접 질문 만들기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "이미 면접 질문이 있어요" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "질문 목록을 불러오지 못했어요" })).toHaveText(
    "질문 목록을 불러오지 못했어요. 새로 고침해 확인해 주세요.",
  );
});
