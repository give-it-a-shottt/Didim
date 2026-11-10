# 프로젝트 상태

## 한눈에 보기
됨 6 · 일부 1 · 다음 8 · 열린 질문 13개
최종 수정: 2026-11-10

## 기능별 상태
| 기능 | 상태 | 한 줄 설명 | 확인 방법 | 최근 리뷰 | 날짜 |
|---|---|---|---|---|---|
| [F-000](features/F-000-dev-setup/feature.md) 개발 환경 세팅 | [됨] | Next.js · FastAPI 뼈대와 `/api` 프록시 동작. 남은 것: 레포 구조(Q-013) · 배포 위치(Q-012), 제안 2건은 시점에 맞춰 고침 | 테스트 backend/tests/test_health.py 2개 통과, 화면 주소의 /api/health → FastAPI 응답 직접 실행(2026-11-08) | 1차 [통과] | 2026-11-08 |
| [F-013](features/F-013-screen-skeleton/feature.md) 화면 뼈대 | [됨] | 레이아웃 3종 + URL 19개 빈 화면 + SEO 기본(제목 · 설명, 회원 noindex, robots.txt · sitemap.xml) | tsc · eslint · next build 통과, 운영 서버에서 URL 19개 200 · 307 이동 · 404 · 메타데이터 · robots.txt · sitemap 직접 실행(2026-11-08 · 09), 테스트 frontend/tests/auth-and-routes.spec.ts 4개 통과(2026-11-09) | 4차 [통과] | 2026-11-09 |
| [F-001](features/F-001-account-isolation/feature.md) 계정 · 데이터 분리 | [됨] | 1주차 기준 [됨](사용자 확인): 구글 OAuth 로그인 · 로그아웃, 회원 화면 16개 가드, users · notes · chunks user_id 격리 · CASCADE 삭제. fix-01: DB 구조는 Alembic 버전 파일로, 서버는 시작 때 버전만 확인(D-015). 남은 것: 2주차 사용량 기록 · 7주차 사용량 제한/삭제 버튼/사용량 화면 | 테스트 backend/tests 110개 통과(SQLite · PostgreSQL didim_test, test_auth_and_isolation.py 8개 · test_migrations.py 13개 포함), 개발 DB `alembic stamp 0001` 뒤 서버 시작 · /api/health 200 직접 실행(2026-11-10). frontend/tests/auth-and-routes.spec.ts 4개 통과, tsc · eslint · next build 통과(2026-11-09) | 5차 [통과] · fix-01-alembic 2차 [통과] | 2026-11-10 |
| [F-014](features/F-014-llm-client/feature.md) LLM 연결 구조 | [됨] | mock · exaone · local 교체, JSON 검사 · 재시도, 사용량 집계, 전체 180초 상한. 남은 것: 하루 상한은 첫 AI 기능 때 | 테스트 backend/tests/test_llm.py 83개 포함 97개 통과, 실제 EXAONE에 "안녕"을 보내 답 받음 — scripts/llm_ping exaone 직접 실행(2.9초, 호출 1번, 2026-11-10) | 3차 [통과] | 2026-11-10 |
| [F-002](features/F-002-import-markdown/feature.md) 마크다운 가져오기 | [됨] | 1주차(읽기 · 나누기) 기준 [됨]: 마크다운 파일 올리기 → 제목 · 길이 기준 조각 + 제목 경로 · 원문 위치 저장. 남은 것: 리뷰 제안 4건(F-003 때) · '만들기'(3 · 4주차) | 테스트 backend/tests 152개 통과(SQLite · PostgreSQL 17 didim_test, test_import_markdown.py 41개 포함, 2026-11-10), frontend/tests/import-records.spec.ts 6개 포함 10개 통과, tsc · eslint · next build 통과, 실제 uvicorn으로 Next 프록시 업로드 · 주소 우회 400 · 가짜 쿠키 401 · 413 직접 실행(2026-11-10) | 4차 [통과] | 2026-11-10 |
| [F-003](features/F-003-record-search-rag/feature.md) 기록 검색 + 근거 | [됨] | 2주차 기준 [됨]: 키워드 검색(pg_trgm) · 검색창 · 결과 줄 · 노트 상세 위치 강조 · 검색 로그 · 평가 기준선(낱말 겹침 1.00 · 다른낱말 0.60, 상위 5개). 남은 것: 결과를 노트별로 묶을지(Q-021), 검색 횟수 상한(Q-020), 명조 글꼴(Q-018), 임베딩 비교(D-016) | 평가: 경험 카드 10장 · 질문 20개로 scripts/search_eval 직접 실행 0.80(16/20, 2026-11-10). 테스트 backend/tests SQLite 178 · PostgreSQL 185개 통과(test_search.py · test_search_eval.py 포함), Playwright 16개(record-search.spec.ts 6개) · tsc · eslint · next build 통과(2026-11-10). 1차 구현 때 실제 uvicorn + next dev(개발 DB)로 프록시 거쳐 검색 · 노트 상세 강조 직접 실행. 성능: 사용자당 조각 1만에서 맞는 것 없음 6ms(didim_test 실측) | 5차 [통과] (3~5차: 노트 상세 마크다운 · 드래그 앤 드롭) | 2026-11-10 |
| [F-004](features/F-004-quiz-review/feature.md) 퀴즈 · 복습 | [일부] | 3주차. 설계 의도 받음(2026-11-10), 구현 전 | - | - | 2026-11-10 |
| [F-005](features/F-005-notion-import/feature.md) 노션 연결 | [다음] | 4주차 | - | - | - |
| [F-006](features/F-006-experience-cards/feature.md) 경험 카드 | [다음] | 4주차 | - | - | - |
| [F-007](features/F-007-posting-analysis/feature.md) 공고 분석 · 매칭 | [다음] | 5주차 | - | - | - |
| [F-008](features/F-008-evidence-draft/feature.md) 근거 달린 자소서 | [다음] | 3~4주차(단순) · 6주차 | - | - | - |
| [F-009](features/F-009-interview-practice/feature.md) 면접 연습 | [다음] | 주차 미정(Q-005) | - | - | - |
| [F-010](features/F-010-eval-and-sample/feature.md) 평가 · 샘플 체험 | [다음] | 7주차 | - | - | - |
| [F-011](features/F-011-landing/feature.md) 랜딩 | [다음] | 8주차 | - | - | - |
| [F-012](features/F-012-home-onboarding/feature.md) 홈 · 첫 방문 안내 | [다음] | 주차 미정(Q-006) | - | - | - |
