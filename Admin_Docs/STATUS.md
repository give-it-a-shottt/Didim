# 프로젝트 상태

## 한눈에 보기
됨 3 · 일부 0 · 다음 11 · 열린 질문 13개
최종 수정: 2026-11-09

## 기능별 상태
| 기능 | 상태 | 한 줄 설명 | 확인 방법 | 최근 리뷰 | 날짜 |
|---|---|---|---|---|---|
| [F-000](features/F-000-dev-setup/feature.md) 개발 환경 세팅 | [됨] | Next.js · FastAPI 뼈대와 `/api` 프록시 동작. 남은 것: 레포 구조(Q-013) · 배포 위치(Q-012), 제안 2건은 시점에 맞춰 고침 | 테스트 backend/tests/test_health.py 2개 통과, 화면 주소의 /api/health → FastAPI 응답 직접 실행(2026-11-08) | 1차 [통과] | 2026-11-08 |
| [F-013](features/F-013-screen-skeleton/feature.md) 화면 뼈대 | [됨] | 레이아웃 3종 + URL 19개 빈 화면 + SEO 기본(제목 · 설명, 회원 noindex, robots.txt · sitemap.xml) | tsc · eslint · next build 통과, 운영 서버에서 URL 19개 200 · 307 이동 · 404 · 메타데이터 · robots.txt · sitemap 직접 실행(2026-11-08 · 09), 테스트 frontend/tests/auth-and-routes.spec.ts 4개 통과(2026-11-09) | 4차 [통과] | 2026-11-09 |
| [F-001](features/F-001-account-isolation/feature.md) 계정 · 데이터 분리 | [됨] | 1주차 기준 [됨](사용자 확인): 구글 OAuth 로그인 · 로그아웃, 회원 화면 16개 가드, users · notes · chunks user_id 격리 · CASCADE 삭제. 남은 것: 2주차 사용량 기록 · 7주차 사용량 제한/삭제 버튼/사용량 화면 | 테스트 backend/tests 14개 통과(SQLite · PostgreSQL), test_auth_and_isolation.py 8개 포함, frontend/tests/auth-and-routes.spec.ts 4개 통과, tsc · eslint · next build 통과(2026-11-09) | 5차 [통과] | 2026-11-09 |
| [F-002](features/F-002-import-markdown/feature.md) 마크다운 가져오기 | [다음] | 1주차 | - | - | - |
| [F-003](features/F-003-record-search-rag/feature.md) 기록 검색 + 근거 | [다음] | 2주차 | - | - | - |
| [F-004](features/F-004-quiz-review/feature.md) 퀴즈 · 복습 | [다음] | 3주차 | - | - | - |
| [F-005](features/F-005-notion-import/feature.md) 노션 연결 | [다음] | 4주차 | - | - | - |
| [F-006](features/F-006-experience-cards/feature.md) 경험 카드 | [다음] | 4주차 | - | - | - |
| [F-007](features/F-007-posting-analysis/feature.md) 공고 분석 · 매칭 | [다음] | 5주차 | - | - | - |
| [F-008](features/F-008-evidence-draft/feature.md) 근거 달린 자소서 | [다음] | 3~4주차(단순) · 6주차 | - | - | - |
| [F-009](features/F-009-interview-practice/feature.md) 면접 연습 | [다음] | 주차 미정(Q-005) | - | - | - |
| [F-010](features/F-010-eval-and-sample/feature.md) 평가 · 샘플 체험 | [다음] | 7주차 | - | - | - |
| [F-011](features/F-011-landing/feature.md) 랜딩 | [다음] | 8주차 | - | - | - |
| [F-012](features/F-012-home-onboarding/feature.md) 홈 · 첫 방문 안내 | [다음] | 주차 미정(Q-006) | - | - | - |
