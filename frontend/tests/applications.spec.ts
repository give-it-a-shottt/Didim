import { expect, test } from "@playwright/test";
import { logIn } from "./helpers";

// 지원 · 공고 분석(F-007) 화면: 목록(D-day 순 · 상태 배지) · 공고 추가 모달 · 공고 분석 탭(뽑기 → 매칭 · 근거 · 실패) · 상태 · 지우기.
// 가짜 백엔드(tests/mock-backend.mjs)의 공고 901~907을 쓴다(테스트마다 다른 공고 — 병렬로 돌아도 서로 안 건드림).

test("지원 목록: D-day 순으로 상태 배지 · D-day가 보이고, 줄을 누르면 공고 분석 탭이 열린다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("지원");
  const list = page.getByRole("list", { name: "지원 목록" });
  const urgent = list.getByRole("link", { name: /누리랩 · 풀스택 개발자/ });
  await expect(urgent).toContainText("작성 중");
  await expect(urgent).toContainText("D-3");
  await expect(urgent).toContainText("요구 역량 2개 중 1개에 근거");
  const names = await list.getByRole("link").allTextContents();
  expect(names.findIndex((name) => name.includes("누리랩"))).toBeLessThan(names.findIndex((name) => name.includes("바른책방")));

  await urgent.click();
  await expect(page).toHaveURL(/\/applications\/901\/analysis$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("누리랩 · 풀스택 개발자 (신입)");
  await expect(page.getByRole("navigation", { name: "지원 상세 탭" }).getByRole("link", { name: "공고 분석" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("공고 분석: 역량마다 근거 칩 · 상태가 보이고, 근거 없는 역량은 기록 검색으로 잇는다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/901/analysis");

  const table = page.getByRole("table", { name: "요구 역량과 내 카드" });
  await expect(table).toContainText("React 화면 개발");
  await expect(table).toContainText("React로 화면을 만든 경험"); // 공고 원문 인용
  await expect(table).toContainText("클라우드 배포 (우대)");
  await expect(table.getByText("근거 있음")).toBeVisible();
  await expect(table.getByText("근거 없음")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "요약 · 근거" })).toContainText("요구 역량 2개 중 1개에 내 카드가 있어요");

  // 첫 역량이 골라져 있음 — 카드 칸 원문(명조 인용) + 카드 링크 + AI 이유
  const evidence = page.getByRole("region", { name: /선택한 역량의 근거/ });
  await expect(evidence.getByRole("blockquote")).toHaveText("useEffect는 그려진 뒤 부수 효과를 실행해요.");
  await expect(evidence.getByRole("link", { name: /useEffect로 구독 정리/ })).toHaveAttribute("href", "/cards/801");
  await expect(evidence).toContainText("React 훅으로 화면을 다룬 경험이에요.");

  await table.getByRole("button", { name: "기록에서 찾기" }).click();
  await expect(evidence).toContainText("이 역량을 보여 줄 카드가 아직 없어요");
  await expect(evidence.getByRole("link", { name: "내 기록에서 찾기" })).toHaveAttribute(
    "href",
    `/records?q=${encodeURIComponent("클라우드 배포")}`,
  );
});

test("공고 추가 → [분석하기]: 저장하고 분석 탭에서 역량 뽑기 · 매칭이 이어서 돈다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications");

  await page.getByRole("button", { name: "공고 추가" }).first().click();
  const dialog = page.getByRole("dialog", { name: "공고 추가" });
  await dialog.getByLabel(/회사/).fill("새회사");
  await dialog.getByLabel(/직무/).fill("웹 개발자");
  await dialog.getByLabel(/공고 본문/).fill("자격 요건\n- TypeScript로 개발한 경험\n- 테스트 코드를 쓴 경험\n");
  await expect(dialog).toContainText("이 본문을 AI에 보내 요구 역량을 뽑아요");
  await expect(dialog.getByLabel(/공고 본문/)).toHaveAccessibleDescription(/캡처 도구.*텍스트 작업/);
  await dialog.getByRole("button", { name: "분석하기" }).click();

  await expect(page).toHaveURL(/\/applications\/\d+\/analysis$/); // ?analyze=1은 시작한 뒤 지운다
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("새회사 · 웹 개발자");
  const table = page.getByRole("table", { name: "요구 역량과 내 카드" });
  await expect(table).toContainText("TypeScript로 개발한 경험");
  await expect(table.getByText("근거 있음")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "요약 · 근거" })).toContainText("요구 역량 2개 중 1개에 내 카드가 있어요");
});

test("공고 추가: 서버가 거절하면(422) 모달에 이유를 보여 주고 닫지 않는다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications");
  await page.getByRole("button", { name: "공고 추가" }).first().click();
  const dialog = page.getByRole("dialog", { name: "공고 추가" });
  await dialog.getByLabel(/회사/).fill("   ");
  await dialog.getByLabel(/직무/).fill("개발자");
  await dialog.getByLabel(/공고 본문/).fill("본문");
  await dialog.getByRole("button", { name: "분석하기" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("회사 이름을(를) 적어 주세요.");
  await expect(dialog).toBeVisible();
});

test("공고 분석: 분석 전이면 보내는 범위를 알리고, 매칭만 실패하면 뽑은 역량은 남기고 [매칭 다시]를 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/903/analysis");

  await expect(page.getByRole("region", { name: "공고가 원하는 것 · 내 근거" })).toContainText("AI 사용량을 최대 2회 써요");
  await page.getByRole("button", { name: "요구 역량 뽑기" }).click();

  const failure = page.getByRole("alert").filter({ hasText: "매칭하지 못했어요" });
  await expect(failure).toContainText("뽑은 요구 역량은 남겨 뒀어요");
  await expect(failure).toContainText("지금은 AI에 연결할 수 없어요");
  await expect(failure.getByRole("button", { name: "매칭 다시" })).toBeVisible();
  await expect(page.getByRole("table", { name: "요구 역량과 내 카드" })).toContainText("React로 화면을 만든 경험");
});

test("공고 분석: ①이 끝난 직후(새 데이터를 받기 전)에도 '찾지 못했어요'를 띄우지 않고 ② 진행을 보여 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/906/analysis");
  await page.getByRole("button", { name: "요구 역량 뽑기" }).click();

  const region = page.getByRole("region", { name: "공고가 원하는 것 · 내 근거" });
  await expect(region.getByRole("status").filter({ hasText: "내 저장 카드와 맞춰 보고 있어요" })).toBeVisible();
  await expect(region.getByRole("status").filter({ hasText: "요구 역량 2개를 찾았어요" })).toBeVisible();
  await expect(region).not.toContainText("찾지 못했어요");
});

test("공고 분석: 하루 상한(429)이면 서버 문구를 보여 준다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/904/analysis");
  await page.getByRole("button", { name: "요구 역량 뽑기" }).click();
  const failure = page.getByRole("alert").filter({ hasText: "요구 역량을 뽑지 못했어요" });
  await expect(failure).toContainText("오늘 AI 사용량(30회)을 다 썼어요");
  await expect(failure.getByRole("button", { name: "다시 뽑기" })).toBeVisible();
});

test("지원 상세: 상태를 바꾸고, 공고를 지우면 목록으로 돌아간다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/905/analysis");

  const status = page.getByLabel("상태");
  await expect(status).toHaveValue("submitted");
  await status.selectOption("writing");
  await expect(status).toHaveValue("writing");

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "공고 지우기" }).click();
  await expect(page).toHaveURL(/\/applications$/);
  await expect(page.getByRole("list", { name: "지원 목록" })).not.toContainText("지울회사");
});

test("지원 상세: 상태 바꾸기 · 지우기가 실패하면 그 자리에 이유를 보여 주고 값 · 화면은 그대로 둔다", async ({ context, page }) => {
  await logIn(context);
  await page.goto("/applications/907/analysis");

  const status = page.getByLabel("상태");
  await expect(status).toHaveValue("ready");
  await status.selectOption("writing");
  await expect(page.getByRole("alert").filter({ hasText: "상태를 바꾸지 못했어요" })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("상태")).toHaveValue("ready"); // 서버 값은 그대로

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "공고 지우기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "공고를 지우지 못했어요" })).toBeVisible();
  await expect(page).toHaveURL(/\/applications\/907\/analysis$/);
});

test("없는 공고 · 이상한 공고 주소는 찾을 수 없다고 나온다", async ({ context, page }) => {
  await logIn(context);
  // 로그인 확인이 Suspense 안이라 응답이 먼저 흘러가서(200) 상태 코드 대신 Next의 찾을 수 없음 화면으로 확인한다(카드 상세와 같은 방식)
  for (const path of ["/applications/999999/analysis", "/applications/abc/analysis"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
  }
});

// 공고 원문 접기 안전 타이머의 여유 — posting-aside.tsx의 COLLAPSE_FALLBACK_SLACK_MS와 같은 값(바꾸면 같이 바꾼다, 12차 리뷰 R1).
// 전환 시간은 테스트가 화면(computed style)에서 직접 읽는다 — CSS 토큰 --motion-duration이 바뀌어도 따라간다.
const COLLAPSE_FALLBACK_SLACK_MS = 100;

test("공고 원문: 펼치면 전체 글, 접으면 높이가 줄어든 뒤 4줄 자르기로 돌아온다(끝 신호 · 안전 타이머, 펼치는 중 접기, 움직임 줄이기면 바로)", async ({
  context,
  page,
}) => {
  await logIn(context);
  await page.goto("/applications/901/analysis");
  const body = page.locator("#posting-body");
  const openButton = page.getByRole("button", { name: "원문 전체 보기" });
  const closeButton = page.getByRole("button", { name: "원문 접기" });
  const state = () => body.getAttribute("data-state");
  const transitionMs = () =>
    body.evaluate((element) => {
      const value = getComputedStyle(element).transitionDuration.split(",")[0].trim();
      return value.endsWith("ms") ? parseFloat(value) : parseFloat(value) * 1000;
    });
  const motionMs = await transitionMs();
  expect(motionMs).toBeGreaterThan(0); // 움직임이 있는 기본 화면
  const timerMs = motionMs + COLLAPSE_FALLBACK_SLACK_MS; // 안전 타이머가 터지는 때

  await expect(body).toHaveAttribute("data-state", "short");
  await expect(body).toHaveClass(/line-clamp-4/);
  await openButton.click();
  await expect(closeButton).toHaveAttribute("aria-expanded", "true");
  await expect(body).toHaveAttribute("data-state", "full");
  await expect(body).toHaveClass(/max-h-120/);

  // ① 끝 신호: 누른 직후에는 전체 글을 둔 채 높이만 줄이고(시간 창에 기대지 않게 바로 읽음), 전환이 끝나면 짧은 글로
  await closeButton.click();
  expect(await state()).toBe("full");
  expect(await body.getAttribute("class")).toContain("max-h-4-lines overflow-hidden");
  await expect(body).toHaveAttribute("data-state", "short");
  await expect(body).toHaveClass(/line-clamp-4/);

  // ② 접는 도중 다시 펼치면 앞서 건 타이머 · 늦은 끝 신호가 다시 접지 않는다 — 전체 글이 그대로(11차 리뷰 R3)
  await openButton.click();
  await closeButton.click();
  await openButton.click();
  await page.waitForTimeout(timerMs + motionMs); // 안전 타이머가 터질 때를 넉넉히 넘긴 뒤에도
  expect(await state()).toBe("full");
  await expect(closeButton).toHaveAttribute("aria-expanded", "true");

  // ③ 취소 신호(transitioncancel)로는 바꾸지 않고, 신호가 없으면 안전 타이머가 바꾼다 — 펼치는 중에 접으면 '펼치기'의
  //    취소 신호가 와서 접기 끝으로 오해했다. 실제 전환은 끄고(시간은 200ms로 남겨 둠) 신호만 보내 확인한다
  await closeButton.click(); // ②에서 펼쳐 둔 것을 먼저 다 접고
  await expect(body).toHaveAttribute("data-state", "short");
  await openButton.click();
  await body.evaluate((element) => {
    (element as HTMLElement).style.transitionProperty = "none";
  });
  await closeButton.click();
  await body.evaluate((element) =>
    element.dispatchEvent(new TransitionEvent("transitioncancel", { propertyName: "max-height", bubbles: true })),
  );
  await page.waitForTimeout(timerMs / 3); // 안전 타이머보다 이르게
  expect(await state()).toBe("full");
  await expect(body).toHaveAttribute("data-state", "short", { timeout: timerMs * 3 }); // 안전 타이머
  await body.evaluate((element) => {
    (element as HTMLElement).style.transitionProperty = "";
  });

  // ④ 움직임 줄이기: 전환 시간이 0이라 신호가 없다 — 누르자마자 짧은 글
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openButton.click();
  expect(await body.evaluate((element) => getComputedStyle(element).transitionDuration)).toBe("0s");
  await closeButton.click();
  expect(await state()).toBe("short");
  expect(await body.getAttribute("class")).toContain("line-clamp-4");
});
