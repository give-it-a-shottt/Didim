import type { NextConfig } from "next";

// 브라우저는 항상 같은 주소의 /api/* 로만 요청하고, Next.js가 FastAPI로 넘긴다.
// 화면과 서버가 같은 주소처럼 보여야 FastAPI가 준 로그인 쿠키(httpOnly)가 그대로 오간다. (D-010, Q-012)
// BACKEND_URL은 서버에서만 읽는 환경변수라 브라우저 번들에 들어가지 않는다.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
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
