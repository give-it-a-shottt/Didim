import { expect, test } from "@playwright/test";

// 기본 보안 머리말(D-032, next.config.ts headers): 공개 화면 · 로그인 화면 · 회원 화면 입구(로그인 화면으로 이동) · 없는 주소 모두에 붙는다.
const PATHS: { path: string; status: number }[] = [
  { path: "/", status: 200 },
  { path: "/login", status: 200 },
  { path: "/report", status: 200 },
  { path: "/demo", status: 200 },
  { path: "/home", status: 200 }, // 로그인 전이라 /login으로 이동한 뒤의 응답
  { path: "/no-such-page", status: 404 },
];

for (const { path, status } of PATHS) {
  test(`${path}: 다른 사이트의 iframe 금지 · 부분 CSP · nosniff · Referrer-Policy`, async ({ request }) => {
    const response = await request.get(path);
    expect(response.status()).toBe(status);
    const headers = response.headers();
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["content-security-policy"]).toBe("frame-ancestors 'none'; object-src 'none'; base-uri 'self'");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  });
}
