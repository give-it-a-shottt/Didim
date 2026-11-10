# 화면 구성

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] IA v2를 사용자가 확인했어요(2026-11-07). URL 표도 확인받아 뼈대(빈 화면)로 만들었어요(2026-11-08, D-011).
무엇을: 화면 32개(2차 2개 별도)를 5개 메뉴 + 기록 추가 버튼으로 묶었어요. 자세한 표 · 플로우는 디자인 md와 피그마에 있어요.
왜: 여기는 "무엇이 어디 있는지" 지도만 두고, 디자인 내용은 한 곳(디자인 md)에서만 고쳐요.

```
[게스트] 랜딩 LND_01_001 → 로그인 AUT_01_001
[회원]
├─ 00 기록 추가 [버튼]  IMP_01_001 → 002 → 003 · 900
├─ 01 홈               HOM_01_900 첫 방문 · DEM_01_001 샘플 체험 · HOM_01_001 대시보드
├─ 02 기록 · 복습       REV_01_001 · 002 · 003 · REV_02_001 퀴즈 · 002 결과 · REV_03_001 오답노트
├─ 03 경험 카드         CRD_01_001 목록 · 002 상세 · 003 만들기 · 후보 검토(시트)
├─ 04 지원             APL_01_001 D-day 목록 · 002 공고 추가 · APL_02_001 지원 상세(탭 002 공고 분석 · 003 자소서 · 004 면접 연습)
└─ 05 설정             SET_01_001 설정 · SET_02_001 평가 리포트
[2차] SRC_01_001 Cmd+K 검색 · APL_01_003 칸반
```

## 개발자 상세

### URL 표 (사용자 확인 2026-11-08)
판단 3개: ① 모달 · 시트 · 상태(_900) 화면은 URL 없이 그 페이지 안에서 띄운다 ② 지원 상세 탭 3개는 URL을 나눈다 ③ 퀴즈는 풀이 한 번마다 URL(sessionId)을 준다.

| 화면 ID | URL | 레이아웃 | 파일(frontend/src/app/) | 완성할 기능 |
|---|---|---|---|---|
| LND_01_001 랜딩 | `/` | 게스트 | (guest)/page.tsx | F-011 |
| AUT_01_001 로그인 | `/login` | 게스트 | (guest)/login/page.tsx | F-001 |
| HOM_01_001 대시보드 · HOM_01_900 첫 방문 | `/home` | 사이드바 | (app)/home/page.tsx | F-012 |
| DEM_01_001 샘플 체험 | `/demo` | 사이드바 | (app)/demo/page.tsx | F-010 |
| REV_01_001 기록 · 복습 홈 (+900) | `/records` (`?q=` 검색어) | 사이드바 | (app)/records/page.tsx | F-003 검색창 · 결과(됨), 노트 목록 · 오늘 복습은 F-004 |
| REV_01_002 노트 상세 | `/records/[noteId]` (`?chunk=` 강조할 조각) | 사이드바 | (app)/records/[noteId]/page.tsx | F-003 원문 · 위치 강조(됨), 개념 · 문제 탭은 F-004 |
| REV_01_003 노트 관리 | `/records/manage` | 사이드바 | (app)/records/manage/page.tsx | F-002 |
| REV_03_001 오답노트 | `/records/wrong-answers` | 사이드바 | (app)/records/wrong-answers/page.tsx | F-004 |
| REV_02_001 퀴즈 | `/quiz/[sessionId]` | 집중 모드 | (focus)/quiz/[sessionId]/page.tsx | F-004 |
| REV_02_002 퀴즈 결과 | `/quiz/[sessionId]/result` | 사이드바 | (app)/quiz/[sessionId]/result/page.tsx | F-004 |
| CRD_01_001 카드 목록 (+900) | `/cards` | 사이드바 | (app)/cards/page.tsx | F-006 |
| CRD_01_002 카드 상세 · 편집 | `/cards/[cardId]` | 사이드바 | (app)/cards/[cardId]/page.tsx | F-006 |
| APL_01_001 지원 목록 | `/applications` | 사이드바 | (app)/applications/page.tsx | F-007 |
| APL_02_001 지원 상세 | `/applications/[id]` → `/analysis`로 이동 | 사이드바 | (app)/applications/[id]/layout.tsx (탭 틀), 이동은 next.config.ts redirects | F-007 |
| APL_02_002 공고 분석 | `/applications/[id]/analysis` | 사이드바 | …/[id]/analysis/page.tsx | F-007 |
| APL_02_003 자소서 | `/applications/[id]/draft` | 사이드바(접힘) | …/[id]/draft/page.tsx | F-008 |
| APL_02_004 면접 연습 | `/applications/[id]/interview` | 사이드바 | …/[id]/interview/page.tsx | F-009 |
| SET_01_001 설정 | `/settings` | 사이드바 | (app)/settings/page.tsx | F-001 |
| SET_02_001 평가 리포트 | `/settings/report` | 사이드바 | (app)/settings/report/page.tsx | F-010 |

- URL 없는 화면: IMP_01_001~003 · 900(기록 추가 모달), APL_01_002(공고 추가 모달), CRD_01_003(후보 검토 시트), REV_01_900 · CRD_01_900 · APL_02_900(상태). 2차 SRC_01_001 · APL_01_003은 만들지 않음.
- 레이아웃 3종(라우트 그룹, URL에는 안 나옴): `(guest)` 게스트 · `(app)` 왼쪽 메뉴 · `(focus)` 메뉴 숨김(퀴즈).
- 로그인 확인(회원 화면 막기)은 F-001에서 붙인다.
- SEO용 메타 경로(화면 · API 아님): `/robots.txt`(frontend/src/app/robots.ts), `/sitemap.xml`(sitemap.ts). 공개 페이지는 `/`, `/login`뿐이고, 공개 페이지를 추가하면 `frontend/src/lib/site.ts`의 `PUBLIC_PATHS`도 같이 고친다.

### 참고
- 전체 명세표(화면 ID · 유형 · 구성 요소 · 이동 · 기기)와 플로우 A · B · C, 예외 7개: `didim-design.md` 2~3장
- 화면 ID ↔ 기능 연결은 각 feature.md의 "화면 · 컴포넌트" 칸

최종 수정: 2026-11-08 · 관련: D-006, D-009, D-011
