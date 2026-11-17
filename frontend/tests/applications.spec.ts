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
const COLLAPSE_FALLBACK_SLACK_MS = 100;
// 갈래를 시간에 기대지 않고 가르려고 전환을 길게 늘린다(12차 리뷰 R3) — 안전 타이머는 이 값 + 여유 뒤에야 터진다
const LONG_MOTION_MS = 5000;

test("공고 원문: 끝 신호 · 안전 타이머 · 펼치는 중 접기 · 화면 떠남 · 움직임 줄이기에서 모두 짧은 글로 끝난다", async ({ context, page }) => {
  await logIn(context);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/applications/901/analysis");
  const body = page.locator("#posting-body");
  const openButton = page.getByRole("button", { name: "원문 전체 보기" });
  const closeButton = page.getByRole("button", { name: "원문 접기" });
  const state = () => body.getAttribute("data-state");
  const setMotion = (style: { duration?: string; property?: string }) =>
    body.evaluate((element, value) => {
      const target = element as HTMLElement;
      target.style.transitionDuration = value.duration ?? "";
      target.style.transitionProperty = value.property ?? "";
    }, style);
  const sendTransition = (type: "transitionend" | "transitioncancel") =>
    body.evaluate(
      (element, eventType) => element.dispatchEvent(new TransitionEvent(eventType, { propertyName: "max-height", bubbles: true })),
      type,
    );
  const fallbackMs = LONG_MOTION_MS + COLLAPSE_FALLBACK_SLACK_MS;

  await expect(body).toHaveAttribute("data-state", "short");
  await expect(body).toHaveClass(/line-clamp-4/);

  // ① 끝 신호: 실제 전환은 끄고(시간은 5초로 남김) 끝 신호만 보낸다 — 타이머(5.1초)보다 훨씬 먼저 짧은 글이면 끝 신호로 바뀐 것
  await setMotion({ duration: `${LONG_MOTION_MS}ms`, property: "none" });
  await openButton.click();
  await expect(body).toHaveAttribute("data-state", "full");
  await expect(body).toHaveClass(/max-h-120/);
  await closeButton.click();
  expect(await state()).toBe("full"); // 접는 중에는 전체 글을 둔 채 높이만 줄인다
  expect(await body.getAttribute("class")).toContain("max-h-4-lines overflow-hidden");
  await sendTransition("transitionend");
  await expect(body).toHaveAttribute("data-state", "short", { timeout: fallbackMs / 5 });
  await expect(body).toHaveClass(/line-clamp-4/);

  // ② 취소 신호로는 바뀌지 않고, 신호가 없으면 안전 타이머가 바꾼다
  await openButton.click();
  await closeButton.click();
  await sendTransition("transitioncancel");
  await page.waitForTimeout(fallbackMs / 5);
  expect(await state()).toBe("full");
  await expect(body).toHaveAttribute("data-state", "short", { timeout: fallbackMs * 2 });

  // ③ 접는 도중 다시 펼치면 앞서 건 타이머 · 늦은 끝 신호가 다시 접지 않는다
  await openButton.click();
  await closeButton.click();
  await openButton.click();
  await sendTransition("transitionend"); // 늦게 온 접기 끝 신호
  await page.waitForTimeout(500);
  expect(await state()).toBe("full");
  await expect(closeButton).toHaveAttribute("aria-expanded", "true");

  // ④ 펼치는 중 접기(실제 전환 5초): 브라우저가 '펼치기'를 취소하고(transitioncancel) 진행된 만큼만 되돌린다 —
  //    누른 직후에는 전체 글이고(취소 신호로 바로 접히지 않음), 되돌림의 끝 신호로 타이머보다 먼저 짧은 글이 된다
  await closeButton.click();
  await setMotion({}); // 실제 전환을 다시 켬
  await setMotion({ duration: `${LONG_MOTION_MS}ms` });
  await expect(body).toHaveAttribute("data-state", "short", { timeout: fallbackMs * 2 });
  await openButton.click();
  await page.waitForTimeout(100); // 펼치는 전환이 시작되도록
  await closeButton.click();
  expect(await state()).toBe("full");
  await expect(body).toHaveAttribute("data-state", "short", { timeout: fallbackMs / 2 });
  await setMotion({});

  // ⑤ 화면 떠남: 접는 중(타이머가 걸린 채) 다른 탭으로 옮겨도 오류가 없다(타이머는 화면을 떠날 때 지운다)
  await openButton.click();
  await closeButton.click();
  await page.getByRole("navigation", { name: "지원 상세 탭" }).getByRole("link", { name: "자소서" }).click();
  await expect(page).toHaveURL(/\/applications\/901\/draft$/);
  await page.waitForTimeout(COLLAPSE_FALLBACK_SLACK_MS * 5);
  expect(pageErrors).toEqual([]);

  // ⑥ 움직임 줄이기: 전환 시간이 0이라 신호가 없다 — 누르자마자 짧은 글
  await page.goto("/applications/901/analysis");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openButton.click();
  expect(await body.evaluate((element) => getComputedStyle(element).transitionDuration)).toBe("0s");
  await closeButton.click();
  expect(await state()).toBe("short");
  expect(await body.getAttribute("class")).toContain("line-clamp-4");
});
