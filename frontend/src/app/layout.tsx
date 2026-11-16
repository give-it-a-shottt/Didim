import type { Metadata } from "next";
import localFont from "next/font/local";
import { SITE_DESCRIPTION, SITE_NAME, SITE_URL } from "@/lib/site";
import "./globals.css";

// 글꼴(Q-018, 사용자 선택 next/font): 빌드할 때 우리 서버에서 함께 내보내 외부 요청이 없고, 글꼴 바뀜으로 화면이 밀리는 것도 줄인다.
// 모든 글은 Pretendard Std 하나(사용자 선택 2026-11-16 — 내 기록 원문의 명조를 없앰, D-026). 가변 굵기 한 파일 · 약 290KB,
// 자주 쓰는 한글 2,780자 + 라틴. 드문 글자는 시스템 글꼴로 보인다.
// 라이선스: SIL OFL 1.1(fonts/Pretendard-LICENSE.txt).
const pretendard = localFont({
  src: "./fonts/PretendardStdVariable.woff2",
  weight: "45 920",
  variable: "--font-pretendard",
  fallback: ["system-ui", "sans-serif"],
});

// 모든 페이지의 기본 메타데이터. 각 페이지는 title만 주면 "제목 | 디딤"이 된다.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    template: `%s | ${SITE_NAME}`,
    default: SITE_NAME,
  },
  description: SITE_DESCRIPTION,
  openGraph: {
    siteName: SITE_NAME,
    locale: "ko_KR",
    type: "website",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ko"
      className={`${pretendard.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
