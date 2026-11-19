import type { NextConfig } from "next";

// 브라우저는 항상 같은 주소의 /api/* 로만 요청하고, Next.js가 FastAPI로 넘긴다.
// 화면과 서버가 같은 주소처럼 보여야 FastAPI가 준 로그인 쿠키(httpOnly)가 그대로 오간다. (D-010, Q-012)
// BACKEND_URL은 서버에서만 읽는 환경변수라 브라우저 번들에 들어가지 않는다.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

// rewrites 프록시는 기본 30초가 지나면 요청을 끊는다(node_modules/next/dist/server/lib/router-utils/proxy-request.js).
// [문제 만들기]는 AI를 기다리느라 최대 100초(backend/app/llm/settings.py DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS)까지 걸려서,
// 30초에 끊기면 화면은 실패로 보이는데 서버는 문제를 저장하는 일이 생긴다. AI 상한 + 저장 여유 20초로 둔다(F-004).
// 이 값은 next start(로컬)용이다. 배포(Vercel)는 바깥 서버로 넘긴 요청을 120초에 끊어서 AI 상한을 100초로 낮췄다(D-032).
const PROXY_TIMEOUT_MS = 120_000;

const nextConfig: NextConfig = {
  cacheComponents: true,
  experimental: {
    proxyTimeout: PROXY_TIMEOUT_MS,
  },
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // 기본 보안 머리말(D-032): 다른 사이트가 디딤을 iframe에 넣지 못하게(클릭재킹), 파일 종류 추측 금지, 다른 사이트로 갈 때 주소 줄이기.
  // 화면 모양 · 동작에는 영향이 없다.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          // 부분 CSP — 전체 CSP(nonce)는 cacheComponents와 부딪혀 넣지 않음. form-action은 구글 로그인 이동과 부딪힐 수 있어 뺌(D-032)
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'; object-src 'none'; base-uri 'self'" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
  // APL_02_001 지원 상세에는 자체 내용이 없어서 첫 탭(공고 분석)으로 보낸다. (screens.md)
  async redirects() {
    return [
      {
        source: "/applications/:id",
        destination: "/applications/:id/analysis",
        permanent: false,
      },
      // 평가 리포트는 회원 화면(/settings/report)에서 공개 페이지로 옮겼다(F-010, D-029)
      {
        source: "/settings/report",
        destination: "/report",
        permanent: false,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
