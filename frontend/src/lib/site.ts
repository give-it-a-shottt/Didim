import type { Metadata } from "next";

// 사이트 공통 정보. 검색 엔진 · 링크 미리보기(메타데이터, robots.txt, sitemap.xml)에서 쓴다.

// 배포 주소는 아직 정하지 않았다(Q-015). 서버에서만 읽는 환경변수라 브라우저 번들에 들어가지 않는다.
// 형식이 틀리면 빌드 · 실행이 멈추므로, 무엇이 틀렸는지 바로 알 수 있게 메시지를 남긴다.
// "foo:bar"처럼 http · https가 아닌 값은 파싱은 되지만 origin이 "null"이 되므로 같이 막는다.
function readSiteUrl(): string {
  const value = process.env.SITE_URL ?? "http://localhost:3000";
  const invalid = new Error(
    `환경변수 SITE_URL 형식이 올바르지 않아요: "${value}". http:// 또는 https://로 시작해야 해요. 예) https://didim.example.com`,
  );
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw invalid;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw invalid;
  }
  return url.origin;
}

export const SITE_URL = readSiteUrl();

export const SITE_NAME = "디딤";

// 사이트 설명 문구 (F-013 최종 판정, 사용자 확인 2026-11-09)
export const SITE_DESCRIPTION =
  "세상에서 제일 쓰기 어려운 사람은 나였어요. 그래서 내 기록에서 시작해요.";

// 검색 엔진에 노출하는 공개 페이지(sitemap.xml에 들어감).
// 공개 페이지를 추가하면 이 목록과 screens.md를 같이 고친다.
export const PUBLIC_PATHS = ["/", "/login"] as const;

// 회원 화면은 개인 기록이라 검색 결과에 올리지 않는다.
// robots.txt로 막으면 검색 로봇이 이 noindex를 읽지 못해 주소만 색인될 수 있어서,
// 회원 화면은 robots.txt에 적지 않고 noindex로만 막는다. 실제 접근 차단은 로그인(F-001)이 한다.
export const MEMBER_ROBOTS: Metadata["robots"] = { index: false, follow: false };
