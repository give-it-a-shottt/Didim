import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// 검색 로봇에게 서버 API만 읽지 말라고 안내한다.
// 회원 화면은 여기서 막지 않는다: 막으면 로봇이 페이지의 noindex를 못 읽어서 주소만 색인될 수 있다.
// 회원 화면은 각 레이아웃의 noindex(MEMBER_ROBOTS)로 검색에서 빼고, 접근 차단은 로그인(F-001)이 한다.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: "/api/",
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
