# 아키텍처

## 한눈에 보기 (코드 몰라도 OK)
상태: [주의] 계획이에요. 세팅만 끝났고(2026-11-08) 기능 코드는 없어서, 만들면서 실제 모양으로 고쳐요.
무엇을: 화면(Next.js)이 서버(FastAPI)에 요청하면, 서버는 DB 한 곳(PostgreSQL)에서 내 기록과 "뜻이 비슷한 조각"을 함께 찾고, 필요한 조각만 AI에 보내 퀴즈 · 카드 · 자소서를 만들어요. AI가 만든 것은 항상 근거(어느 노트 · 카드의 어디)와 같이 저장돼요.
왜: DB를 하나로 두면 운영이 단순하고, 근거를 같이 저장해야 "지어낸 문장"을 잡아낼 수 있어요.

```
브라우저 ── Next.js (화면)
   │  fetch /api/*  (Next.js가 FastAPI로 넘김 = 같은 주소처럼 보임)
   ▼
FastAPI (서버, 모든 경로가 /api 아래)
   ├─ 가져오기 어댑터: Markdown | Notion  ──▶ 같은 기록 모양
   ├─ RAG: 나누기 → 임베딩 → 검색 (BM25 + 벡터, 사용자 조건 필수)
   ├─ 생성: 퀴즈 · 카드 후보 · 공고 역량 · 자소서 · 면접 질문
   │    └─ 근거 검사 루프: 쓰기 → 검사 → 고치기
   ├─ LLM 클라이언트: mock | exaone | local (D-014, F-014)
   └─ 사용량 제한 · 평가 로그
   ▼
PostgreSQL + pgvector (기록 · 조각 · 임베딩 · 카드 · 공고 · 문장 · 근거)
```

## 개발자 상세

### 지금 폴더 구조 (2026-11-09, Q-013 임시)
```
frontend/                 Next.js 16 (App Router, TypeScript, Tailwind 4)
  next.config.ts          /api/* → BACKEND_URL 프록시(rewrites), /applications/[id] → 공고 분석 탭(redirects)
  playwright.config.ts    Playwright 스모크 · 인증 리다이렉트 테스트 설정 (D-013)
  src/app/                화면(라우트) — 19개, 표는 screens.md
    (guest)/ (app)/ (focus)/   레이아웃 3종(URL에 안 나옴, 회원 레이아웃은 MemberAuthGuard로 보호)
  src/components/         공통 컴포넌트(app-sidebar, screen-placeholder, member-auth-guard, logout-button)
  src/lib/site.ts         사이트 이름 · 설명 · 주소 · 공개/회원 경로 (SEO)
  src/lib/auth.ts         서버에서 httpOnly 쿠키로 /api/auth/me 확인 · 비로그인 시 /login 이동
  src/app/robots.ts, sitemap.ts   검색 엔진 안내
  tests/                  Playwright E2E · 스모크 테스트 (auth-and-routes.spec.ts, mock-backend.mjs)
backend/                  FastAPI (uv)
  app/main.py             앱 생성, lifespan DB 초기화, 라우터를 /api 아래에 붙임
  app/config.py           환경변수 · 쿠키/상한 상수
  app/api/                라우터 (health.py, auth.py, deps.py)
  app/services/           비즈니스 로직 (auth_service.py, note_service.py)
  app/db/                 SQLAlchemy 2.0 모델(User, Note, Chunk) · 세션 (base.py, models.py, session.py)
  app/llm/                LLM 연결(D-014, F-014) — 인터페이스 · mock · OpenAI 호환 클라이언트 · JSON 검사(complete_json)
  scripts/                손으로 돌리는 확인 스크립트 (llm_ping.py)
  tests/                  pytest (test_health.py, test_auth_and_isolation.py, test_db_config.py, test_llm.py)
```
- 레이어(라우터 → 서비스 → DB)는 `app/api/`(라우터) → `app/services/`(비즈니스 로직) → `app/db/`(모델 · 세션) 한 방향으로만 흐른다. `app/llm/`은 서비스가 부르는 아래층이고 db · api를 가져다 쓰지 않는다.

### 상태 관리 지도 (D-012)
기준: 서버 데이터 → 서버 컴포넌트 또는 TanStack Query / 여러 화면이 같이 쓰는 UI 상태 → Zustand / 화면 하나 → useState. 쓸 때마다 한 줄 추가해요.

| 상태 | 어디에 | 왜 | 기능 |
|---|---|---|---|
| 현재 로그인한 사용자 정보(`/settings`, 회원 레이아웃 보호) | 서버 컴포넌트(`requireCurrentUser`) | 첫 화면을 그릴 때 쿠키로 서버에서 바로 확인하고 비로그인이면 `/login`으로 보내기 위해 | F-001 |
| 로그아웃 버튼 진행 중(`isPending`) · 오류 문구(`errorMessage`) | 컴포넌트 안(`useState`, `logout-button.tsx`) | 설정 화면의 로그아웃 버튼 하나에서만 쓰는 일시적인 상태라서 | F-001 |

### DB (D-008)
- 운영 · 개발 DB는 PostgreSQL(+ pgvector). 로컬은 레포 루트 `docker-compose.yml`의 `db` — PostgreSQL 17(pgvector/pgvector:pg17), `127.0.0.1:5432`(내 컴퓨터에서만), 계정은 루트 `.env`(커밋 안 함). 배포 DB 버전은 Q-012와 함께 맞춘다.
- 서버는 `DATABASE_URL`이 없으면 이유를 적은 오류로 시작하지 않는다(조용히 다른 DB로 넘어가지 않음).
- 테스트 DB는 `backend/tests/conftest.py` 한 곳에서 정한다: 기본은 테스트마다 임시 SQLite, `TEST_DATABASE_URL`을 주면 PostgreSQL **테스트 전용 DB**(`didim_test`, 컨테이너를 처음 만들 때 `docker/postgres-init`이 생성). 테스트가 테이블을 지웠다 만들기 때문에 DB 이름이 `_test`로 끝나지 않으면 멈춘다. 셸의 `DATABASE_URL`은 테스트에서 항상 덮어쓴다.
- 테이블은 서버 시작 때 `create_all`로 만든다. 컬럼 변경은 반영되지 않아 마이그레이션 도구를 정해야 한다(Q-016).

### 디자인 토큰 (설계 원칙 7)
- `frontend/src/app/globals.css`의 `@theme`: 색(text · line · bg · primary · sub1 · status), 글자 크기(Pretendard 스케일), 라운드(Radius Default). 값은 디자인 원본에서 옮긴 것이고, 바꿀 때는 디자인 원본을 먼저 고친다.

### SEO (설계 원칙 8)
- 공통 정보: `frontend/src/lib/site.ts`(사이트 이름 · 설명 · 주소 · 공개/회원 경로)
- 제목: 루트 레이아웃의 템플릿 `%s | 디딤`, 페이지마다 `metadata.title` · `description`
- 검색 노출: 공개 페이지(`/`, `/login`)만. 회원 레이아웃 `(app)` · `(focus)`는 `noindex`(`MEMBER_ROBOTS`), `sitemap.xml`엔 공개 페이지만
- `robots.txt`는 `/api/`만 막는다. 회원 화면을 robots.txt로 막으면 검색 로봇이 페이지를 열지 않아 `noindex`를 못 읽고, 외부 링크가 있으면 주소만 색인될 수 있어서다. robots.txt는 누구나 볼 수 있는 파일이라 회원 경로를 적지 않는 것이 구조 노출 면에서도 낫다.
- robots.txt · noindex는 검색 노출 조절이지 접근 차단이 아니다. 회원 화면 접근 차단은 로그인(F-001)이 한다.
- 시맨틱: 레이아웃마다 `<main>` 하나, 화면마다 `<h1>` 하나(탭 화면은 `<h2>`), `<html lang="ko">`
- 서버 렌더링: App Router 서버 컴포넌트가 기본이라 HTML에 내용이 담겨 내려가요. 클라이언트 컴포넌트("use client")는 필요한 부분에만 써요.

### 원칙
- 데이터 분리: 모든 조회 · 벡터 검색에 사용자 ID 조건(D-004).
- AI 출력: 정해진 스키마로 받고, 형식이 틀리면 재시도 · 실패 처리.
- LLM에 보내는 범위 최소화: 필요한 조각만, 무엇을 보내는지 안내.
- 평가 가능하게: 매칭 · 근거 검사 결과를 로그로 남겨 평가 세트로 채점(D-005).
- 오래 걸리는 처리(가져오기 · 초안 생성)는 진행 상태를 저장해서 나갔다 와도 이어 보기(IMP_01_002). 방식(백그라운드 작업 · 폴링 · 스트리밍)은 F-002 설계 의도에서 정해요(Q-008).

최종 수정: 2026-11-08 · 관련: D-001, D-003, D-004, D-008, D-010
