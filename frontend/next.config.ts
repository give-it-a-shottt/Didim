import type { NextConfig } from "next";

// 브라우저는 항상 같은 주소의 /api/* 로만 요청하고, Next.js가 FastAPI로 넘긴다.
// 화면과 서버가 같은 주소처럼 보여야 FastAPI가 준 로그인 쿠키(httpOnly)가 그대로 오간다. (D-010, Q-012)
// BACKEND_URL은 서버에서만 읽는 환경변수라 브라우저 번들에 들어가지 않는다.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

// rewrites 프록시는 기본 30초가 지나면 요청을 끊는다(node_modules/next/dist/server/lib/router-utils/proxy-request.js).
// [문제 만들기]는 AI를 기다리느라 최대 180초(backend/app/llm/settings.py DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS)까지 걸려서,
// 30초에 끊기면 화면은 실패로 보이는데 서버는 문제를 저장하는 일이 생긴다. AI 상한 + 저장 여유 20초로 둔다(F-004).
const PROXY_TIMEOUT_MS = 200_000;

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
  // APL_02_001 지원 상세에는 자체 내용이 없어서 첫 탭(공고 분석)으로 보낸다. (screens.md)
  async redirects() {
    return [
      {
        source: "/applications/:id",
        destination: "/applications/:id/analysis",
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
