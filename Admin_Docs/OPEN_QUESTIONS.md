# 열린 질문

## 한눈에 보기
열림 2개 · 닫힘 24개
최종 수정: 2026-11-13

## 열림
| 번호 | 질문 | 누가 정해야 하나 | 올린 사람 | 관련 | 임시 처리 | 날짜 |
|---|---|---|---|---|---|---|
| Q-012 | FastAPI는 어디에 올릴까? (Vercel에 같이 vs 별도 서버) | 사용자 | AI | D-008, D-010 | 8주차(랜딩 · 배포 때)에 정함(사용자 확인 2026-11-13). 아직 배포 안 함. 로컬에서는 Next.js가 `/api/*`를 FastAPI로 넘기는 프록시(rewrites)로 같은 주소처럼 씀. 정할 때 운영에서 FastAPI 문서 경로 끄기(F-000 R2 제안)와 Vercel 빌드 환경변수 BACKEND_URL도 같이 처리. 배포 DB에서 pg_trgm · btree_gin 확장 설치 권한(0003)과 확장이 없을 때 검색 응답(F-003 1차 리뷰 I)도 함께 확인. 면접관 시연 방식(영상 · 미리 만든 결과 · 직접 시연)도 같이 정한다 — 배포된 사이트에서 남이 AI를 부르면 EXAONE 약관(제3자 호출 금지)에 걸릴 수 있음(Q-019) | 2026-11-08 |
| Q-015 | 사이트 주소(도메인)는 무엇으로 할까? sitemap · robots · 링크 미리보기에 쓰여요 | 사용자 | AI | F-013, Q-012 | 배포(Q-012) 때 같이 정함(사용자 확인 2026-11-13). 환경변수 SITE_URL, 없으면 http://localhost:3000. 형식이 틀리면 이유를 적은 오류로 빌드가 멈춤. robots · sitemap은 빌드 때 만들어져서 배포 시 빌드 환경변수로 넣어야 함 | 2026-11-09 |

## 닫힘
| 번호 | 질문 | 답이 옮겨진 곳 | 닫은 날짜 |
|---|---|---|---|
| Q-019 | K-EXAONE 2.5를 다른 사람이 가입해 쓰는 공개 서비스에서도 써도 되나? (약관: 비상업 · 제3자 호출 금지) | [D-014](decisions/D-014-llm-exaone-swappable.md) 약관 · 데이터 — 공개 배포 계획 없음, 포트폴리오용으로 본인만 사용. 시연 방식은 Q-012와 함께 | 2026-11-12 |
| Q-023 | 사용자당 동시에 하나만 도는 AI 요청 제한을 기능마다 따로 둘까, 하나로 묶을까? | [D-020](decisions/D-020-one-ai-job-per-user.md) — 기능을 가리지 않고 1개 | 2026-11-11 |
| Q-022 | 근거(원문 인용)가 0개인 경험 카드를 허용할까? | [F-006 feature.md](features/F-006-experience-cards/feature.md) 설계 의도 — 허용 | 2026-11-11 |
| Q-018 | 글꼴(Pretendard · 원문 인용 Noto Serif KR)은 어떻게 넣을까? | [D-019](decisions/D-019-figma-is-design-source.md) — next/font (Pretendard Std는 local, Noto Serif KR은 google) | 2026-11-11 |
| Q-002 | 임베딩 모델은 무엇으로 할까? | [D-016](decisions/D-016-keyword-search-first.md) — 키워드 검색으로 시작, 임베딩은 평가로 비교한 뒤 | 2026-11-10 |
| Q-016 | DB 구조 변경(마이그레이션)은 어떤 도구로 할까? | [D-015](decisions/D-015-alembic-migrations.md) | 2026-11-10 |
| Q-011 | 화면을 먼저 다 만들고 기능을 붙일까, 기능마다 화면 + 서버를 같이 만들까? | [D-011](decisions/D-011-skeleton-first-screens-by-week.md) | 2026-11-08 |
| Q-009 | 1주차에 로그인 성공 후 어느 화면으로 보낼까? (홈 F-012는 주차 미정) | [F-001](features/F-001-account-isolation/feature.md) | 2026-11-09 |
| Q-010 | 1주차 로그아웃은 설정(SET_01_001)의 "계정" 칸만 먼저 만들어서 둘까? | [F-001](features/F-001-account-isolation/feature.md) | 2026-11-09 |
| Q-003 | data-model의 계획 테이블 전체를 이대로 갈까? (1주차 DB 설계 때 확인) | [data-model.md](overview/data-model.md), [F-001](features/F-001-account-isolation/feature.md) | 2026-11-09 |
| Q-014 | 프론트 테스트 도구는 무엇으로 할까? (예: Playwright로 URL 스모크 테스트) | [D-013](decisions/D-013-frontend-test-playwright.md) | 2026-11-09 |
| Q-001 | LLM 클라이언트를 인터페이스 하나로 묶고 환경변수로 mock ↔ real을 바꾸는 구조를 쓸까? | [D-014](decisions/D-014-llm-exaone-swappable.md) | 2026-11-09 |
| Q-004 | 샘플 체험 데이터는 같은 표에 표시(플래그)로 둘까, 별도 스키마로 둘까? | [D-025](decisions/D-025-sample-data-in-sample-account.md) — 샘플 전용 계정 하나 | 2026-11-13 |
| Q-005 | F-009 면접 연습은 몇 주차에 할까? | START_HERE 기능 표 · STATUS — 6주차 | 2026-11-13 |
| Q-006 | F-012 홈 · 첫 방문 안내는 몇 주차에 할까? | START_HERE 기능 표 · STATUS — 8주차(랜딩과 같이) | 2026-11-13 |
| Q-007 | F-010 평가 데이터에 개발 말고 다른 직무 공고도 섞을까? | F-010 feature.md 설계 의도 '미리 정한 것' — 개발 직무만 | 2026-11-13 |
| Q-008 | 오래 걸리는 처리는 백그라운드 작업 · 폴링 · 스트리밍 중 무엇으로 할까? | [D-022](decisions/D-022-long-ai-work-in-request.md) — 요청 한 번 + 180초 유지 | 2026-11-13 |
| Q-013 | 레포 구조와 도구: frontend/(npm) + backend/(uv) 두 폴더로 갈까? | [D-023](decisions/D-023-two-folder-repo.md) | 2026-11-13 |
| Q-017 | 로그아웃 · 계정 정지 때 이미 발급한 세션을 서버에서 무효로 만들까? | [D-024](decisions/D-024-signed-cookie-session-kept.md) — 서명 쿠키 그대로, 공개 배포 때 다시 | 2026-11-13 |
| Q-020 | 기록 검색에도 사용자별 횟수 상한을 둘까? | F-003 feature.md 설계 의도 '정한 것' — 상한 없음, 공개 배포 때 다시 | 2026-11-13 |
| Q-021 | 기록 검색 결과를 노트별로 묶을까? | F-003 feature.md 설계 의도 '정한 것' — 한 노트에서는 조각 최대 2개(구현 전) | 2026-11-13 |
| Q-026 | 사용자당 공고 수 · 매칭에 읽는 저장 카드 수에 상한을 둘까? | F-007 feature.md 설계 의도 '정한 것' — 둘 다 상한 없음 | 2026-11-13 |
| Q-024 | F-007 숫자 상한(본문 · 역량 · 인용 · 후보 카드 · 매칭 수 등)을 이대로 둘까? | F-007 feature.md 설계 의도 '정한 것' · `config.py` F-007 주석 | 2026-11-13 |
| Q-025 | [매칭 다시] 결과가 0개여도 이전 매칭을 모두 지울까? | F-007 feature.md 설계 의도 '정한 것' | 2026-11-12 |
