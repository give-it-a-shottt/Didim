# F-000 개발 환경 세팅

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 세팅 끝. R2 1차 [통과], 제안 2건은 정해진 시점에 고쳐요.
무엇을: 화면(Next.js)과 서버(FastAPI)의 빈 뼈대를 만들고, 화면 주소의 `/api/*` 요청이 서버로 넘어가게 연결했어요. 집으로 치면 전기 · 수도만 들어온 빈 집이에요.
왜: 1주차 기능(F-001 · F-002)을 바로 올릴 수 있는 바닥이 필요해서요.

## 설계 의도 (사용자 확인 — 코드 작성 전에 채움, 문장 정리사 사용)
- 이 기능이 해결하는 문제: 세팅 작업이라 기능 설계 의도 대신 사용자 요청 범위를 따라요 — Next.js + Tailwind + TypeScript + FastAPI + Vercel로 세팅(2026-11-08).
- 완료 기준: 해당 없음(세팅)
- 화면 · API · 데이터: 해당 없음(세팅)

## 결과 (AI 작성 — 구현 후)
- frontend/: create-next-app으로 생성(Next.js 16.4.5 · React 19.3 · Tailwind 4 · TypeScript, App Router, src/). [next.config.ts](../../../frontend/next.config.ts)에 `/api/*` → `BACKEND_URL` 프록시(rewrites) 추가. `.env.example`에 변수 이름만.
- backend/: uv 프로젝트(Python 3.13, fastapi[standard] 0.162, 개발용 pytest · httpx). `app/main.py`(라우터를 /api 아래에), `app/api/health.py`(GET /api/health), `tests/test_health.py`.
- 루트 `.gitignore`: `.env`, `.env.*` 제외, `.env.example`은 커밋.
- 의도와 다른 점: uv가 pyproject.toml에 git 설정의 이메일을 자동으로 넣어서 지웠어요. uv 기본 src/ 패키지 구조 대신 FastAPI에서 흔한 `app/` 구조로 바꿨어요(Q-013).

## 리뷰
- [SUMMARY](review/SUMMARY.md) — 1차 [통과], 범위: 패키지 추가(R2). 최종 판정 완료(제안 2건 수용, 시점에 맞춰 고침).

## 열린 질문
- Q-012, Q-013

## 면접 예상 질문
- Q1. 화면(Next.js)과 서버(FastAPI)가 따로 있는데, 왜 CORS를 열지 않고 Next.js가 `/api/*`를 넘겨주는 프록시 구조로 했나요?
- Q2. npm audit에 취약점 8건이 나왔는데 왜 바로 `npm audit fix --force`로 고치지 않았나요?
- Q3. FastAPI의 자동 API 문서(/docs)는 운영에서 어떻게 할 건가요?
- 답 (사용자 확인 — 문장 정리사 사용)

최종 수정: 2026-11-08 · 관련: D-008, D-010, D-011
