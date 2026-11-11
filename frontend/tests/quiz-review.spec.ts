import { type BrowserContext, expect, test } from "@playwright/test";

// 퀴즈 · 복습(F-004) 화면: 기록 · 복습 홈 '오늘 복습 N' · 노트 목록 → 퀴즈(집중 모드) → 결과 · 오답노트,
// 노트 상세 [문제 만들기] · [이 노트 풀기]. 가짜 백엔드(tests/mock-backend.mjs)의 문제 101 · 102와 노트 6 · 7을 쓴다.
const VALID_SESSION_TOKEN = "playwright-valid-session-token";

async function logIn(context: BrowserContext) {
  await context.addCookies([
    { name: "didim_session", value: VALID_SESSION_TOKEN, domain: "localhost", path: "/", httpOnly: true },
  ]);
}

test("기록 · 복습 홈에 오늘 복습 N과 노트 목록이 나오고, 노트를 누르면 노트 상세로 간다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records");

  const todayCard = page.getByRole("region", { name: "오늘 복습" });
  await expect(todayCard).toContainText("2문제");
  await expect(todayCard.getByRole("link", { name: "복습 시작" })).toHaveAttribute("href", "/quiz/today");
  await expect(page.getByRole("heading", { name: "노트 2" })).toBeVisible();
  const note = page.getByRole("link", { name: /React 정리/ });
  await expect(note).toContainText("문제 2개");
  await expect(page.getByRole("link", { name: /코드 노트/ })).toContainText("문제 없음");

  await note.click();

  await expect(page).toHaveURL(/\/records\/1$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("React 정리");
  await expect(page.getByRole("heading", { name: "문제 2개" })).toBeVisible();
  await expect(page.getByRole("link", { name: "이 노트 풀기" })).toHaveAttribute("href", "/quiz/note-1");
});

test("오늘 복습: 답을 내면 채점 · 해설 · 근거 · 다음 복습일이 나오고, 다 풀면 결과 화면에 점수가 나온다", async ({
  context,
  page,
}) => {
  await logIn(context);
  await page.goto("/quiz/today");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("오늘 복습");
  const progress = page.getByRole("progressbar", { name: "퀴즈 진행" });
  await expect(progress).toHaveAttribute("aria-valuenow", "1");
  await expect(progress).toHaveAttribute("aria-valuemax", "2");
  // 목록에는 정답 · 해설이 없어서 답을 내기 전에는 보이지 않는다
  await expect(page.getByText("useEffect는 화면을 그린 뒤 실행돼요.")).toHaveCount(0);
  const submit = page.getByRole("button", { name: "답 내기" });
  await expect(submit).toBeDisabled();

  // 1번 문제(객관식): 틀린 보기를 고른다
  await page.getByRole("radio", { name: "그리기 전" }).check();
  await submit.click();

  await expect(page.getByRole("heading", { name: /틀렸어요/ })).toBeFocused();
  await expect(page.getByText("useEffect는 화면을 그린 뒤 실행돼요.")).toBeVisible();
  await expect(page.locator("blockquote")).toHaveText("useEffect는 그려진 뒤 부수 효과를 실행해요.");
  await expect(page.getByRole("link", { name: "근거 원문 보기: React 정리" })).toHaveAttribute(
    "href",
    "/records/1?chunk=11#chunk-11",
  );
  await expect(page.getByText("다음 복습: 11월 11일")).toBeVisible();
  await expect(page.getByText("오답노트에 넣었어요. 2번 연속 맞히면 빠져요.")).toBeVisible();
  await expect(page.getByText("정답", { exact: true })).toBeVisible();
  await expect(page.getByText("내 답 · 틀림")).toBeVisible();
  await expect(page.getByRole("radio", { name: "그려진 뒤" })).toBeDisabled(); // 답을 낸 뒤에는 바꿀 수 없다

  // 2번 문제(OX, 오답노트에 있던 문제): 맞힌다
  await page.getByRole("button", { name: "다음 문제" }).click();
  await expect(progress).toHaveAttribute("aria-valuenow", "2");
  await expect(page.getByRole("heading", { name: "상태를 바꾸면 다시 그려진다." })).toBeFocused();
  await page.getByRole("radio", { name: "O", exact: true }).check();
  await page.getByRole("button", { name: "답 내기" }).click();

  await expect(page.getByRole("heading", { name: /맞았어요/ })).toBeVisible();
  await expect(page.getByText("2번 연속 맞혀서 오답노트에서 빠졌어요.")).toBeVisible();
  await expect(page.getByText("다음 복습: 11월 12일")).toBeVisible();

  await page.getByRole("button", { name: "결과 보기" }).click();

  await expect(page).toHaveURL(/\/quiz\/today\/result\?correct=1&total=2$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("복습을 마쳤어요");
  await expect(page.getByRole("region", { name: "이번 점수" })).toContainText("1 / 2");
  await expect(page.getByText("50%")).toBeVisible();
  await expect(page.getByRole("link", { name: "틀린 문제 다시 풀기" })).toHaveAttribute("href", "/quiz/wrong");
});

test("[답 내기]가 실패하면 이유가 보이고, 같은 문제에서 다시 낼 수 있다(네트워크 끊김 · 서버 오류)", async ({
  context,
  page,
}) => {
  await logIn(context);
  await page.goto("/quiz/today");
  const submit = page.getByRole("button", { name: "답 내기" });
  await page.getByRole("radio", { name: "그려진 뒤" }).check();

  // 1) 네트워크 끊김
  await page.route("**/api/quizzes/101/answer", (route) => route.abort("internetdisconnected"));
  await submit.click();
  await expect(page.getByRole("alert").filter({ hasText: "네트워크 문제" })).toContainText(
    "네트워크 문제로 보내지 못했어요. 연결을 확인하고 다시 시도해 주세요.",
  );
  await expect(page.getByRole("radio", { name: "그려진 뒤" })).toBeEnabled(); // 보기가 잠기지 않는다
  await page.unroute("**/api/quizzes/101/answer");

  // 2) 서버 오류(JSON이 아닌 500 본문) → 기본 문구
  await page.route("**/api/quizzes/101/answer", (route) =>
    route.fulfill({ status: 500, contentType: "text/plain", body: "Internal Server Error" }),
  );
  await submit.click();
  await expect(page.getByText("답을 보내지 못했어요. 잠시 뒤 다시 시도해 주세요.")).toBeVisible();
  await page.unroute("**/api/quizzes/101/answer");

  // 3) 다시 내면 정상 채점 — 같은 문제(1/2)에 그대로 있다
  await submit.click();
  await expect(page.getByRole("heading", { name: /맞았어요/ })).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "퀴즈 진행" })).toHaveAttribute("aria-valuenow", "1");
  await expect(page.getByText("답을 보내지 못했어요")).toHaveCount(0); // 이전 오류 문구는 사라진다
});

test("[답 내기] 중 로그인이 풀리면(401) 다시 로그인하러 가는 링크가 보인다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/quiz/today");
  await page.route("**/api/quizzes/101/answer", (route) =>
    route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "로그인이 필요해요." }) }),
  );
  await page.getByRole("radio", { name: "그려진 뒤" }).check();
  await page.getByRole("button", { name: "답 내기" }).click();

  await expect(page.getByText("로그인이 풀렸어요. 다시 로그인해 주세요.")).toBeVisible();
  await expect(page.getByRole("link", { name: "로그인하러 가기" })).toHaveAttribute("href", "/login");
});

test("근거 칩을 누르면 노트 상세에서 그 조각이 강조되고, 뒤로 오면 풀던 자리가 남아 있다", async ({
  context,
  page,
}) => {
  await logIn(context);
  await page.goto("/quiz/today");
  await page.getByRole("radio", { name: "그려진 뒤" }).check();
  await page.getByRole("button", { name: "답 내기" }).click();
  await expect(page.getByRole("heading", { name: /맞았어요/ })).toBeVisible();

  await page.getByRole("link", { name: "근거 원문 보기: React 정리" }).click();

  await expect(page).toHaveURL(/\/records\/1\?chunk=11#chunk-11$/);
  await expect(page.getByText("고른 부분: # React 정리 > ## useEffect")).toBeVisible();
  await expect(page.locator("[data-chunk-highlight]")).toHaveCount(1);

  await page.goBack();

  await expect(page).toHaveURL(/\/quiz\/today$/);
  await expect(page.getByRole("heading", { name: /맞았어요/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "다음 문제" })).toBeVisible();
});

test("노트 상세 [문제 만들기]: AI에 보내는 범위를 먼저 알리고, 만들면 결과와 [이 노트 풀기]가 나온다", async ({
  context,
  page,
}) => {
  await logIn(context);
  await page.goto("/records/6");

  await expect(page.getByRole("heading", { name: "문제", exact: true })).toBeVisible();
  await expect(page.getByText(/최대 10곳 골라 AI에 보내고/)).toBeVisible();

  await page.getByRole("button", { name: "문제 만들기" }).click();

  await expect(page.getByText("✓ 문제 1개를 만들었어요.")).toBeVisible();
  await expect(page.getByText("원문에서 근거를 확인하지 못한 1개는 버렸어요.")).toBeVisible();
  await expect(page.getByText("오늘 남은 AI 사용: 29회")).toBeVisible();
  // 서버 컴포넌트를 새로 받아 문제 수가 바뀐다
  await expect(page.getByRole("link", { name: "이 노트 풀기" })).toHaveAttribute("href", "/quiz/note-6");
  await expect(page.getByRole("button", { name: "문제 만들기" })).toHaveCount(0);
});

test("노트 상세 [문제 만들기]: 서버가 거절하면(오늘 사용량 다 씀) 서버 문구를 그대로 보여 준다", async ({
  context,
  page,
}) => {
  await logIn(context);
  await page.goto("/records/7");

  await page.getByRole("button", { name: "문제 만들기" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "오늘 AI 사용량" })).toHaveText(
    "오늘 AI 사용량(30회)을 다 썼어요. 한국 시간 0시에 다시 쓸 수 있어요.",
  );
  await expect(page.getByRole("button", { name: "문제 만들기" })).toBeEnabled(); // 다시 누를 수 있다
});

test("오답노트에 틀린 문제가 모이고, [다시 풀기]는 오답노트 세션으로 간다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/records/wrong-answers");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("오답노트");
  await expect(page.getByText("2번 연속 맞히면 빠져요.")).toBeVisible();
  const list = page.getByRole("list", { name: "틀린 문제" });
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list).toContainText("상태를 바꾸면 다시 그려진다.");

  await page.getByRole("link", { name: "1문제 다시 풀기" }).click();

  await expect(page).toHaveURL(/\/quiz\/wrong$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("오답노트 다시 풀기");
  await expect(page.getByRole("progressbar", { name: "퀴즈 진행" })).toHaveAttribute("aria-valuemax", "1");
});

test("세션 주소 확인: 모르는 세션 · 남의 노트는 찾을 수 없음, 문제 없는 노트는 안내, 점수 없는 결과 주소는 안내만", async ({
  context,
  page,
}) => {
  await logIn(context);

  // 로그인 확인이 Suspense 안이라 응답이 먼저 흘러가서(200) 상태 코드 대신 Next의 찾을 수 없음 화면으로 확인한다(노트 상세와 같은 방식).
  for (const path of ["/quiz/abc", "/quiz/note-0", "/quiz/note-99999999999", "/quiz/note-404", "/quiz/abc/result"]) {
    await page.goto(path);
    await expect(page.getByText("This page could not be found."), path).toBeVisible();
  }

  await page.goto("/quiz/note-3");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("이 노트 풀기");
  await expect(page.getByText("이 노트에는 아직 문제가 없어요.")).toBeVisible();
  await expect(page.getByRole("link", { name: "노트로 돌아가기" })).toHaveAttribute("href", "/records/3");

  for (const query of ["", "?correct=3&total=2", "?correct=1&total=0", "?correct=-1&total=2", "?correct=1&total=abc"]) {
    await page.goto(`/quiz/today/result${query}`);
    await expect(page.getByText("보여 줄 점수가 없어요. 푼 답은 이미 저장돼 있어요.")).toBeVisible();
    await expect(page.getByRole("link", { name: "틀린 문제 다시 풀기" })).toHaveCount(0);
  }
});
