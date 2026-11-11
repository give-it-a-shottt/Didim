"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// TanStack Query(D-012): 화면에서 보내는 수정 요청(퀴즈 답 제출 · 문제 만들기)을 맡는다.
// 서버 렌더마다 새 클라이언트, 브라우저에서는 하나를 계속 쓴다(Next 16 문서 client-side-data-fetching/tanstack-query.md).
let browserQueryClient: QueryClient | undefined;

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      // 답 제출 · 문제 만들기는 다시 보내면 기록이 두 번 남거나 AI를 두 번 부를 수 있어서 자동 재시도하지 않는다.
      mutations: { retry: false },
    },
  });
}

function getQueryClient(): QueryClient {
  if (typeof window === "undefined") return makeQueryClient();
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

export function QueryProvider({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={getQueryClient()}>{children}</QueryClientProvider>;
}
