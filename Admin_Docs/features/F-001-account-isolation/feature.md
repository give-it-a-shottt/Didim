# F-001 계정 · 사용자별 데이터 분리 · 사용량 제한

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 1주차 구현 · 1차 리뷰 완료(2026-11-09)
언제: 1주차(사용량 기록은 2주차, 사용량 제한 · 삭제 버튼 · 사용량 화면은 7주차)
무엇을: 로그인 · 회원가입, 모든 조회에 사용자 조건, 하루 AI 사용량 상한, 설정의 데이터 삭제 · 사용량 표시
왜: 모든 기능이 올라가는 바닥이고, 나중에 붙이면 모든 조회 · 검색을 다시 고쳐야 해서요.

## 설계 의도 (사용자 확인 — 코드 작성 전에 채움, 문장 정리사 사용)
- 이 기능이 해결하는 문제 (사용자 확인): 로그인과 데이터 분리는 모든 기능이 올라가는 바닥이라 1주차에 넣었다. 자소서와 경험은 민감한 정보이고, 디딤은 AI가 내 기록만 근거로 써야 하는 서비스다. 나중에 붙이면 모든 조회와 검색을 다시 고쳐야 하고, 그 사이 다른 사람의 기록이 섞일 위험이 있다.
- 완료 기준(무엇이 되면 끝인지) (사용자 확인):
  - 1주차
    - 로그인은 구글 로그인으로 간단하게 시작한다.
    - 구글 로그인 · 로그아웃이 된다.
    - 로그인하지 않으면 회원 화면과 API를 막는다.
    - 모든 사용자 테이블에 user_id가 있고, 조회할 때 user_id 조건을 건다.
    - A가 올린 노트가 B에게 보이지 않는 테스트를 통과한다.
    - 사용자를 삭제하면 그 사용자의 데이터가 같이 지워지도록 DB를 설계한다.
  - 나중에 할 것
    - 2주차: 사용량 기록
    - 7주차: 사용량 제한, 삭제 버튼, 사용량 화면
- 화면 · 컴포넌트 (사용자 확인):
  - 로그인(`AUT_01_001`, `/login`): 구글 로그인 버튼을 두고, 로그인에 성공하면 홈(`/home`)으로 보낸다.
  - 설정(`SET_01_001`, `/settings`): 1주차에는 "계정" 칸만 먼저 만들어서 로그아웃 버튼을 둔다.
  - 회원 화면 보호: 로그인하지 않은 상태로 회원 화면에 접근하면 `/login`으로 보낸다.
- API (사용자 확인):
  - `GET /api/auth/google/login`: 구글 로그인 화면으로 보낸다(위조 방지용 `state` 확인값 함께 저장).
  - `GET /api/auth/google/callback`: 구글에서 돌아오면 계정을 확인(없으면 생성)하고 `httpOnly` 세션 쿠키를 발급한 뒤, 성공하면 `/home`으로 보내고 실패하면 `/login?error=...`로 보낸다.
  - `GET /api/auth/me`: 로그인 상태면 내 정보(`id`, `email`, `name`)를 돌려주고(200), 아니면 `401`을 돌려준다.
  - `POST /api/auth/logout`: 세션 쿠키를 지우고 `204`를 돌려준다.
- 데이터 (사용자 확인):
  - `users` 테이블: `id`, 구글 고유 번호(`google_sub`, 중복 불가), 이메일(`email`), 이름(`name`), 하루 사용량 상한(`daily_limit`), 생성일(`created_at`)을 둔다.
  - 사용자별 데이터 분리: 모든 사용자 테이블에 `user_id`(외래키, 사용자 삭제 시 함께 삭제 `ON DELETE CASCADE`)를 두고, 모든 조회에 `user_id` 조건을 건다.
  - 테이블 생성 순서(`Q-003`): `data-model.md`의 전체 테이블 계획은 그대로 가고, DB에는 주차별로 실제 쓰는 테이블부터 만든다(1주차: `users`, `notes`, `chunks`).

## 결과 (AI 작성 — 구현 후)
- 바뀐 파일
  - 백엔드(`backend/`):
    - `pyproject.toml`, `.env.example`, `.gitignore`: `sqlalchemy`, `psycopg[binary]`, `httpx` 추가, 환경변수 예시 파일 작성
    - `app/config.py`: 환경변수(`DATABASE_URL`, `SESSION_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL`, `COOKIE_SECURE`)와 쿠키·상한 상수
    - `app/db/base.py`, `app/db/models.py`, `app/db/session.py`: SQLAlchemy 2.0 `User`, `Note`, `Chunk` 모델(`ON DELETE CASCADE`, `(user_id, content_hash)` UNIQUE) 및 SQLite 외래키 활성화·세션 관리
    - `app/services/auth_service.py`: HMAC-SHA256 서명 토큰(`session` · `oauth_state` 목적 분리, 상수 시간 비교, 만료 검증), 구글 OAuth URL 생성 · 코드 교환(`httpx` 타임아웃 · 예외 처리), 사용자 조회·생성
    - `app/services/note_service.py`: `user_id` 조건이 강제된 노트·조각 생성·목록·단건 조회, 계정 삭제(`ON DELETE CASCADE`)
    - `app/api/deps.py`, `app/api/auth.py`, `app/main.py`: `get_current_user` 의존성 및 `/api/auth/google/login`, `/api/auth/google/callback`, `/api/auth/me`, `/api/auth/logout` 라우터
    - `tests/test_auth_and_isolation.py`: 인증·위조/만료 쿠키·OAuth state/실패·사용자 A/B 데이터 분리·중복 노트·계정 삭제 시 연쇄 삭제 pytest 6개(전체 8개 통과)
  - 프론트엔드(`frontend/`):
    - `src/lib/auth.ts`: 서버에서 `didim_session` 쿠키를 전달해 `/api/auth/me`를 확인하는 `getCurrentUserOrNull`, 비로그인 시 `/login`으로 보내는 `requireCurrentUser`
    - `src/components/member-auth-guard.tsx`, `src/app/(app)/layout.tsx`, `src/app/(focus)/layout.tsx`: Next.js 16 `cacheComponents` 규칙에 맞춰 `<Suspense>` 안의 `MemberAuthGuard`로 모든 회원 화면(16개 URL) 보호
    - `src/app/(guest)/login/page.tsx`: 피그마 `AUT_01_001` 기반 로그인 화면, `/api/auth/google/login` 연결, `?error=` 에러 안내 배너
    - `src/app/(app)/settings/page.tsx`, `src/components/logout-button.tsx`: 피그마 `SET_01_001` 기반 설정 "계정" 칸 + 로그아웃 버튼
    - `playwright.config.ts`, `tests/mock-backend.mjs`, `tests/auth-and-routes.spec.ts`: 공개·회원 19개 URL 스모크 테스트 + 비로그인 리다이렉트 + 로그인·로그아웃 E2E 테스트 4개 통과
- 설계 의도와 다른 점: 없음 (1주차 범위 그대로 구현, 사용량 기록은 2주차 · 사용량 제한/삭제 버튼/사용량 화면은 7주차 예정)
- 2차 수정(2026-11-09, Claude Code가 1차 결과를 점검하고 바로잡음):
  - DB: `DATABASE_URL` 기본값(SQLite 파일)을 없애 비어 있으면 이유를 적은 오류로 멈춤. 테스트 DB는 `tests/conftest.py`에 명시(기본 메모리 SQLite, `TEST_DATABASE_URL`로 PostgreSQL). 로컬 PostgreSQL용 `docker-compose.yml` · 루트 `.env.example` 추가. 실행 명령에 `--env-file .env` 추가.
  - 1차 R2 제안 반영: `getCurrentUserOrNull`을 React `cache()`로 감싸 한 요청 안에서 `/api/auth/me`를 한 번만 호출, `server-only` 표시.
  - 원칙 7: 직접 쓴 색 · 크기 값 42곳을 `globals.css` `@theme` 토큰으로 교체(로그인 · 설정 · 회원 레이아웃 · 로그아웃 버튼). 오류 안내는 status/error 토큰(bg · base · text)으로 맞춤.
  - 열린 질문 추가: Q-016(마이그레이션 도구), Q-017(세션 서버 무효화), Q-018(글꼴).
- 2차 확인: pytest 8개 통과(메모리 SQLite) + 같은 8개 PostgreSQL 17(pgvector 이미지)에서 통과, PostgreSQL로 앱 시작 · 테이블 3개 · 외래키 CASCADE 확인, `DATABASE_URL` 없이 시작하면 오류로 멈춤 확인, 테스트 실행 뒤 떠도는 `.db` 파일 없음, lint · tsc · build 통과, 토큰 클래스 CSS 생성 확인, Playwright 4개 통과(2026-11-09)

## 리뷰
- [review/SUMMARY.md](review/SUMMARY.md) — 1차 `[통과]`(다른 에이전트, 제안 1건 → 2차에서 반영), 2차 `[주의]`(신규 주의 4 · 제안 4), 최종 판정 대기

## 열린 질문
- Q-016, Q-017, Q-018

## 면접 예상 질문
1. **질문 (AI 작성)**: 왜 인증 토큰을 `localStorage`에 넣지 않고 FastAPI가 발급하는 `httpOnly` 서명 쿠키(`didim_session`)로 처리했나요? 그리고 Next.js 16 App Router에서 회원 화면 16개를 어떻게 보호했나요?
   - 답 (사용자 확인 — 문장 정리사 사용): (사용자 확인 전)
2. **질문 (AI 작성)**: 멀티유저 환경에서 다른 사용자의 기록(노트·조각)이 조회되거나 RAG 근거로 섞이는 사고를 막기 위해 DB 스키마와 서비스 계층을 어떻게 설계했나요?
   - 답 (사용자 확인 — 문장 정리사 사용): (사용자 확인 전)
3. **질문 (AI 작성)**: OAuth 로그인에서 `state` 쿠키 검증과 세션 쿠키 검증에 같은 `SESSION_SECRET`을 쓰면서 토큰 바꿔치기(OAuth `state` 토큰을 세션 쿠키 자리에 넣는 공격)는 어떻게 막았나요?
   - 답 (사용자 확인 — 문장 정리사 사용): (사용자 확인 전)

최종 수정: 2026-11-09 · 관련: D-004, D-008, D-010, D-013
