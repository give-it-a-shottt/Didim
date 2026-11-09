# START HERE

## 한눈에 보기 (코드 몰라도 OK)

상태: [주의] 기획 끝, 개발 환경 세팅 끝(2026-11-08). 기능 코드는 시작 전이에요.

**이 서비스는 무엇이고 누구를 위한 것인지** (사용자 확인)

- 무엇: 공부 기록을 퀴즈로 복습하고, 그 기록을 근거로 자소서 · 면접을 준비하는 서비스
- 누구를 위해: 공부 기록은 쌓이는데 복습도 지원서도 매번 처음부터 하는 취준생(첫 사용자는 나)

**지금 상태** — [STATUS.md](STATUS.md): 됨 2 · 일부 1 · 다음 11 · 열린 질문 13개

- 끝난 것: 서비스 이름(디딤), 경험 카드 10장(노션), 디자인 기획(IA v2 · 플로우 · 디자인 4안 · 모드 · 토큰 → `didim-design.md`), 결정 D-001~D-014, 개발 환경 세팅(F-000), 화면 뼈대 + SEO 기본 + Playwright 스모크 테스트(F-013), 계정 · 사용자별 데이터 분리 1주차 구현 및 1차 리뷰(F-001)
- 다음(1주차, 이 순서로):
  1. F-001 2차 리뷰 판정 → 지적 반영(테스트 전용 DB · 가드 등) → 3차 리뷰 → [됨] 판단(1주차 범위), 면접 예상 질문 답
  2. 마이그레이션 도구(Q-016) — 2주차 chunks.embedding 전에 꼭
  3. LLM 구조 · 모델 결정(Q-001 · Q-002, D-008)
  4. F-002(마크다운 가져오기) 설계 의도 → 구현 → 리뷰
- 확인 필요: [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md)에 모아 뒀어요.

**읽는 순서**

1. 이 문서
2. [STATUS.md](STATUS.md) — 지금 어디까지 왔나
3. [overview/architecture.md](overview/architecture.md) — 화면 → 서버 → DB → AI 흐름
4. [overview/screens.md](overview/screens.md) — 무엇이 어디 있는지
5. [features](features/) 최신 3개, [decisions](decisions/) D-003(근거 우선) · D-005(평가) · D-006(범위)
6. [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) — 아직 못 정한 것

**폴더 역할**

| 폴더 · 파일 | 답하는 질문 |
|---|---|
| [STATUS.md](STATUS.md) | 지금 어디까지 왔고, 어떻게 확인했나 |
| [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) | 아직 결정 못 한 게 뭔가 |
| [overview](overview/) | 지금 어떻게 생겼나 |
| [decisions](decisions/) | 왜 이렇게 했나 |
| [features](features/) | 무엇을 만들었고, 리뷰 결과는 어땠나 |
| [troubleshooting](troubleshooting/INDEX.md) | 뭐가 막혔고 어떻게 풀었나 |
| [_system](_system/rules.md) | 규칙 · 용어 · 리뷰어 기준 (참고용) |

## 개발자 상세

### 기술 스택
- Frontend: Next.js 16 + TypeScript + Tailwind CSS 4 (배포: Vercel)
- Backend: Python 3.13, FastAPI (패키지 관리: uv, 배포 위치는 Q-012)
- DB: PostgreSQL + pgvector
- AI: LLM API + 임베딩, RAG, 에이전트 루프(쓰기 → 검사 → 고치기)

### 실행
비밀값은 각 폴더의 `.env.example`을 보고 `.env`(커밋 안 함)에 직접 넣어요. 레포 루트 `.env`는 로컬 DB용, `backend/.env`는 서버용이에요.
```
# DB (처음 한 번 + 컴퓨터를 켤 때마다) — Docker Desktop을 켠 뒤
docker compose up -d db          # 레포 루트에서. PostgreSQL + pgvector (D-008)

# 서버 (터미널 1)
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000 --env-file .env   # DATABASE_URL이 없으면 시작하지 않아요
uv run pytest                    # 테스트(기본은 메모리 SQLite)
TEST_DATABASE_URL=<로컬 PostgreSQL 주소> uv run pytest   # 같은 테스트를 PostgreSQL에서

# 화면 (터미널 2)
cd frontend
npm install
npm run dev              # 3000번이 다른 프로젝트와 겹치면: npx next dev --port 3001
npm run test:e2e         # Playwright (가짜 백엔드로 실행, D-013)
```
- 확인: 브라우저에서 `화면주소/api/health` → `{"status":"ok"}`면 화면 → 서버 연결이 된 거예요.

### 폴더 지도
```
CLAUDE.md            Claude Code가 먼저 읽는 규칙
didim-design.md      디자인 원본 (IA · 플로우 · 토큰)
frontend/            Next.js 화면
backend/             FastAPI 서버
Admin_Docs/
  START_HERE.md      한 장 요약
  STATUS.md          지금 어디까지 왔나
  OPEN_QUESTIONS.md  아직 못 정한 것
  overview/          architecture · data-model · api-list · screens
  decisions/         D-00X (결정 1개 = 파일 1개)
  features/          F-00X/feature.md (+ 리뷰), REVIEW_LOG.md
  troubleshooting/   T-00X, INDEX.md
  _system/           rules · glossary · reviewers R1~R4
```

### 결정
| 번호 | 제목 | 상태 |
|---|---|---|
| [D-001](decisions/D-001-markdown-first-notion-later.md) | 마크다운 먼저, 노션 4주차, 어댑터 구조 | [통과] |
| [D-002](decisions/D-002-paste-postings-no-crawling.md) | 공고는 붙여넣기, 크롤링 금지, 사람인 API는 이후 | [통과] |
| [D-003](decisions/D-003-evidence-first-drafts.md) | 근거 우선 — 문장마다 근거, 제출 시 확인창 | [통과] |
| [D-004](decisions/D-004-multi-user-from-day-one.md) | 처음부터 남이 쓰는 서비스 | [통과] |
| [D-005](decisions/D-005-seeded-synthetic-eval.md) | 평가는 정답을 심어 둔 가상 데이터 | [통과] |
| [D-006](decisions/D-006-mvp-scope.md) | MVP 범위와 2차, 퀴즈는 객관식 + OX | [통과] |
| [D-007](decisions/D-007-landing-story-motion.md) | 랜딩 스토리 모션, 밀리면 축소 | [통과] |
| [D-008](decisions/D-008-stack-and-llm-client.md) | 스택과 LLM 호출 구조 | [주의] mock ↔ real 확인 필요 |
| [D-009](decisions/D-009-design-direction.md) | 디자인 4안 "작업대 위의 각주" | [통과] |
| [D-010](decisions/D-010-auth-in-fastapi.md) | 구글 로그인은 FastAPI가 처리(httpOnly 쿠키) | [통과] |
| [D-011](decisions/D-011-skeleton-first-screens-by-week.md) | 화면은 뼈대(레이아웃 + 라우트) 먼저, 각 화면은 주차별 완성 | [통과] |
| [D-012](decisions/D-012-state-management.md) | 상태 관리: 서버 데이터는 TanStack Query, 공용 UI 상태만 Zustand (App Router 유지) | [통과] |
| [D-013](decisions/D-013-frontend-test-playwright.md) | 프론트엔드 테스트 도구는 Playwright로 한다 | [통과] |
| [D-014](decisions/D-014-llm-exaone-swappable.md) | LLM은 K-EXAONE 2.5 메인, mock · exaone · local 교체 구조 | [통과] |

### 기능 (8주 로드맵)
| 번호 | 기능 | 주차 | 상태 |
|---|---|---|---|
| [F-000](features/F-000-dev-setup/feature.md) | 개발 환경 세팅 | 1 | [됨] R2 1차 [통과] |
| [F-013](features/F-013-screen-skeleton/feature.md) | 화면 뼈대(레이아웃 + URL 19개) | 1 | [됨] 4차 [통과] |
| [F-001](features/F-001-account-isolation/feature.md) | 계정 · 데이터 분리 · 사용량 제한 | 1 · 2 · 7 | [일부] 1주차 구현 · 1차 [통과] (2·7주차 남음) |
| [F-002](features/F-002-import-markdown/feature.md) | 마크다운 가져오기 | 1 | 설계 의도 전 |
| [F-003](features/F-003-record-search-rag/feature.md) | 기록 검색 + 근거 (RAG) | 2 | 설계 의도 전 |
| [F-004](features/F-004-quiz-review/feature.md) | 퀴즈 · 복습 주기 · 오답노트 | 3 | 설계 의도 전 |
| [F-005](features/F-005-notion-import/feature.md) | 노션 연결 | 4 | 설계 의도 전 |
| [F-006](features/F-006-experience-cards/feature.md) | 경험 카드 | 4 | 설계 의도 전 |
| [F-007](features/F-007-posting-analysis/feature.md) | 공고 분석 · 매칭 | 5 | 설계 의도 전 |
| [F-008](features/F-008-evidence-draft/feature.md) | 근거 달린 자소서 + 근거 검사 | 3~4(단순) · 6 | 설계 의도 전 |
| [F-009](features/F-009-interview-practice/feature.md) | 면접 연습 | 미정(Q-005) | 설계 의도 전 |
| [F-010](features/F-010-eval-and-sample/feature.md) | 평가 세트 · 리포트 · 샘플 체험 | 7 | 설계 의도 전 |
| [F-011](features/F-011-landing/feature.md) | 랜딩 | 8 | 설계 의도 전 |
| [F-012](features/F-012-home-onboarding/feature.md) | 홈 · 첫 방문 안내 | 미정(Q-006) | 설계 의도 전 |

일정이 밀리면 줄이는 순서: ① 랜딩을 "히어로 + 고정 섹션 1개"로(D-007) ② 근거 검사는 규칙 기반 단순 버전 유지(D-003) ③ 노션 연결을 7주 이후로(D-001)

최종 수정: 2026-11-08
