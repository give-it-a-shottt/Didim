# F-013 화면 뼈대 (레이아웃 + 라우트)

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 끝났어요. 4차 리뷰 [통과](지적 없음), 최종 판정 완료(2026-11-09).
무엇을: 왼쪽 메뉴 같은 공통 틀과, 화면 19개의 주소를 빈 화면으로 만들었어요. 집으로 치면 방 배치와 문을 다 달아 둔 상태예요. 각 방의 인테리어(실제 화면)는 그 주 기능에서 해요.
왜: 전체 지도(URL)를 처음에 확정해서, 기능을 만들 때 "이 화면이 어디 있지"로 헤매지 않으려고요(D-011).

## 설계 의도 (사용자 확인 — 코드 작성 전에 채움, 문장 정리사 사용)
- 이 기능이 해결하는 문제: D-011(화면은 뼈대 먼저, 각 화면은 주차별 완성)을 따른다. (사용자 확인 2026-11-08)
- 완료 기준(무엇이 되면 끝인지): 승인한 URL 표([screens.md](../../overview/screens.md))대로 화면이 열린다. (사용자 확인 2026-11-08 — URL 표 "그대로 가자")
- 함께 넣을 것: SEO 기본(시맨틱 태그, 서버 렌더링, 페이지 제목과 설명)을 함께 넣는다. (사용자 확인 2026-11-09)
- 화면: screens.md URL 표 19개, 레이아웃 3종
- API: 해당 없음
- 데이터: 해당 없음

## 결과 (AI 작성 — 구현 후)
- 바뀐 파일
  - frontend/src/app/layout.tsx: lang="ko", 제목 "디딤"
  - frontend/src/app/(guest|app|focus)/…: 페이지 18개 + 레이아웃 3개(지원 상세 탭 틀 포함)
  - frontend/src/components/app-sidebar.tsx, screen-placeholder.tsx
  - frontend/next.config.ts: `/applications/:id` → `/applications/:id/analysis` 이동(redirects)
  - 지운 것: 기본 시작 페이지(src/app/page.tsx), public/*.svg 5개(기본 페이지에서만 쓰던 그림)
- 실제 구조: 뼈대 페이지는 URL 값(`[id]`)을 읽지 않는다. 지원 상세 탭 링크만 id를 읽고, cacheComponents 규칙에 따라 Suspense 안에서 읽는다.
- 설계 의도와 다른 점: 없음. 디자인(색 · 글꼴 · 토큰)은 아직 적용하지 않았다(기본 Geist 글꼴 그대로).
- 2차(2026-11-09) 추가: 1차 판정대로 사이트 설명 문구 변경. 사용자 요청으로 SEO 기본 추가 — `src/lib/site.ts`, 루트 메타데이터(제목 템플릿 · 설명 · metadataBase · og), 페이지 18개 title · description, `(guest)/layout.tsx`(main), 회원 레이아웃 noindex, `robots.ts` · `sitemap.ts`, ScreenPlaceholder `headingLevel`(탭 화면 h2로 h1 하나 유지).
- 2차 확인: lint · tsc · build(23페이지, robots.txt · sitemap.xml 포함) 통과, 운영 서버에서 제목 "X | 디딤" · 설명 · 회원 페이지 noindex · h1 1개 · main 1개 · robots.txt · sitemap.xml · lang=ko · og 직접 확인(2026-11-09)
- 3차(2026-11-09, 2차 판정 반영): robots.txt는 `/api/`만 막고 회원 화면은 noindex로만(`MEMBER_ROBOTS` 상수로 두 레이아웃 공유, 쓰지 않게 된 `MEMBER_PATH_PREFIXES` 삭제), `SITE_URL` 형식 검사(틀리면 이유를 적은 오류). screens.md에 SEO 메타 경로 · PUBLIC_PATHS 동기화 한 줄.
- 4차(2026-11-09, 3차 판정 반영): readSiteUrl이 http · https가 아닌 값(예: foo:bar)도 같은 오류로 막음.
- 4차 확인: lint · tsc 통과, SITE_URL="foo:bar" · "mailto:a@b.c" · "not a url" 빌드가 모두 "http:// 또는 https://로 시작해야 해요" 오류로 멈춤, SITE_URL="https://a.com/x/" 빌드 → sitemap에 https://a.com/ · /login, 기본값 빌드 정상(2026-11-09)
- 3차 확인: lint · tsc · build 통과, `SITE_URL="not a url"` 빌드가 "환경변수 SITE_URL 형식이 올바르지 않아요" 오류로 멈춤, 운영 서버에서 robots.txt = `Disallow: /api/`만 · 회원 페이지 noindex 유지 · 공개 페이지 robots 없음 · URL 18개 200 + 307 이동 · sitemap 공개 2개 직접 확인(2026-11-09)
- 확인: `tsc` 통과, `eslint` 통과, `next build` 성공(21페이지), 운영 서버에서 19개 URL 200 + 화면 ID 일치, `/applications/a1` → 307 analysis, 탭 링크 3개 정상, 퀴즈에 메뉴 없음, 없는 주소 404 (2026-11-08)

## 리뷰
- [SUMMARY](review/SUMMARY.md) — 1차 [주의] 판정 완료(전부 수용). 2차 [주의] 신규 6건 → 전부 수용 · 반영. 3차 [통과], 신규 제안 1건 → 수용 · 반영. 4차 [통과](범위: 버그 수정 → R1 · R3 · R4), 지적 없음, 최종 판정 완료. 총 4차.

## 열린 질문
- Q-014, Q-015

## 면접 예상 질문
- Q1. 화면이 32개인데 URL은 왜 19개뿐인가요? 모달이나 빈 상태 화면에는 왜 URL을 주지 않았나요?
- Q2. 같은 사이트 안에서 왼쪽 메뉴가 있는 화면과 없는 화면(퀴즈)을 URL을 바꾸지 않고 어떻게 나눴나요?
- Q3. 지원 상세 탭을 화면 안의 상태가 아니라 URL로 나눈 이유는 뭔가요? 그 대신 생긴 제약(params를 Suspense 안에서 읽기)은 뭔가요?
- 답 (사용자 확인 — 문장 정리사 사용)

최종 수정: 2026-11-08 · 관련: D-011, D-006
