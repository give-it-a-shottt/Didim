# F-001 계정 · 사용자별 데이터 분리 · 사용량 제한

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 1주차 기준 [됨] · 5차 리뷰 완료(2026-11-09)
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
- 3차 수정(2026-11-09, 2차 판정 반영):
  - 테스트 DB 설정을 `tests/conftest.py` 한 곳으로 모음(`db_session` 이동, `tmp_path: Path`). PostgreSQL 테스트는 **테스트 전용 DB**(`didim_test`)만 허용하고 이름이 `_test`로 끝나지 않으면 테스트 시작 전에 멈춤. 셸의 `DATABASE_URL`은 테스트에서 항상 덮어씀.
  - `tests/test_db_config.py`: DATABASE_URL 기본값 없음 · 빈 값이면 `DatabaseConfigError` 단위 테스트 2개.
  - docker-compose: 포트 `127.0.0.1:5432:5432`, `docker/postgres-init`이 처음 만들 때 `didim_test` 생성(기존 볼륨엔 수동 생성). PostgreSQL 17 · 포트를 architecture에 기록.
  - T-002: 포트를 127.0.0.1로 묶은 뒤 `localhost` 연결이 끝없이 멈춤 → 주소를 127.0.0.1로, PostgreSQL 연결에 `connect_timeout` 5초.
- 3차 확인: pytest 10개(SQLite) 통과, 같은 10개 PostgreSQL `didim_test`(127.0.0.1) 통과, `localhost`로도 멈추지 않고 통과(36초), 개발 DB(`didim`)를 주면 안전장치가 테스트 전에 멈춤, 셸에 개발 DB 주소가 있어도 개발 DB 데이터 그대로(전 1건 · 후 1건), 떠도는 .db 파일 없음, 포트가 127.0.0.1에만 열림 확인(2026-11-09)

- 4차 수정(2026-11-09, 3차 판정 반영):
  - `backend/.env.example`: `SESSION_SECRET` 예시 값을 32자 미만(`CHANGE_ME`)으로 바꾸고 만드는 명령을 주석으로. 길이 검사는 서버 시작이 아니라 로그인 · 세션 요청 때 돌아서, 예시 값을 그대로 두면 로그인부터 실패함.
  - `tests/test_db_config.py`: 테스트 2개 추가 — `_test` 가드가 개발 DB 주소에서 멈추는지, PostgreSQL 엔진에 `connect_timeout`이 들어가는지(`create_engine`을 가짜로 바꿔 DB 없이 확인). 각 테스트에 무엇을 · 왜 · 실패하면 무슨 뜻인지 설명을 적음.
  - `START_HERE.md` 실행 절: 기존 볼륨에 `didim_test`를 만드는 `createdb` 한 줄.
- 4차 확인: pytest 12개(SQLite) 통과, 같은 12개 PostgreSQL `didim_test` 통과(2026-11-09)
- 5차 수정(2026-11-09, 4차 판정 반영):
  - `tests/conftest.py`: 가드 함수를 넘겨주는 fixture `test_db_url_guard` 추가 → `test_db_config.py`가 conftest를 직접 import하지 않음(`tests/__init__.py`나 import 방식이 바뀌어도 안 깨짐).
  - `tests/test_auth_and_isolation.py`: `.env.example`의 예시 SESSION_SECRET을 파일에서 읽어, 그 값으로는 로그인이 시작되지 않고(`oauth_not_configured`, state 쿠키 없음) `/api/auth/me`가 500인지 확인하는 테스트 2개.
- 5차 확인: pytest 14개(SQLite) 통과, 같은 14개 PostgreSQL `didim_test` 통과(2026-11-09)

- fix-01 Alembic(2026-11-10, D-015 · Q-016 답): 서버 시작 때 `create_all` 대신 DB 버전 확인(`app/db/schema_version.py` — 연결 안 됨 · 뒤처짐 · 코드보다 앞섬을 다른 오류로 안내, 주소 비노출). 버전 파일 `migrations/versions/0001`(users · notes · chunks 그대로), `alembic.ini`(주소 없음) · `migrations/env.py`(DATABASE_URL · 넘겨받은 연결 재사용). 테스트는 `create_all` 유지, `tests/test_migrations.py` 13개가 "버전 파일 적용 결과 = 모델"(compare_metadata) · downgrade · 상황별 안내 · lifespan 시작 멈춤을 확인. 개발 DB는 `alembic stamp 0001` 적용.
- fix-01 확인: pytest 110개 SQLite · PostgreSQL `didim_test` 통과, 개발 DB stamp 뒤 lifespan 시작 · `/api/health` 200(2026-11-10)

## 리뷰
- [review/SUMMARY.md](review/SUMMARY.md) — 1차 `[통과]`(다른 에이전트) → 2차 `[주의]`(신규 주의 4 · 제안 4, 전부 반영) → 3차 `[통과]`(신규 제안 3, 전부 반영) → 4차 `[통과]`(신규 제안 2, 전부 반영) → 5차 `[통과]`(R1 · R3, 지적 없음). 1주차 기준 [됨](사용자 확인, 2026-11-09)
- [review/fix-01-alembic/SUMMARY.md](review/fix-01-alembic/SUMMARY.md) — Alembic 도입(D-015): 1차 `[주의]`(주의 4 · 제안 8, 전부 반영) → 2차 `[통과]`(R1 · R3 · R4, 제안 2 — 한 줄짜리, 사용자 판정 대기)

## 열린 질문
- Q-017, Q-018 (Q-016은 D-015로 닫힘)

## 면접 예상 질문

1. **질문 (AI 작성)**: 왜 인증 토큰을 `localStorage`에 넣지 않고 FastAPI가 발급하는 `httpOnly` 서명 쿠키(`didim_session`)로 처리했나요? 그리고 Next.js 16 App Router에서 회원 화면 16개를 어떻게 보호했나요?
   - 답 (사용자 확인 — AI 초안을 외워 설명, 2026-11-10):
     - localStorage에 토큰을 두면 자바스크립트로 읽을 수 있어서, 화면에 악성 스크립트가 하나라도 들어오면(XSS) 토큰을 그대로 가져갈 수 있어요. httpOnly 쿠키는 자바스크립트가 아예 못 읽고, 브라우저가 요청할 때 자동으로 붙여 보내기만 해요.
     - 그래서 로그인은 FastAPI가 처리하고, 성공하면 서버가 서명한 세션 쿠키를 `httpOnly` · `SameSite=Lax`(운영에서는 `Secure`도)로 내려 줘요. Lax는 다른 사이트에서 몰래 보내는 요청(CSRF)에 쿠키가 덜 붙게 해 줘요.
     - 회원 화면 보호는 Next.js 서버에서 해요. 회원 화면 레이아웃 두 개(`(app)`, `(focus)`)에 `MemberAuthGuard`를 넣어, 화면을 그리기 전에 서버가 쿠키를 FastAPI `/api/auth/me`로 보내 확인하고, 로그인 안 했으면 `/login`으로 보내요. 레이아웃에 한 번 걸면 그 아래 16개 화면이 다 보호돼서 화면마다 검사를 따로 넣지 않아도 돼요.
     - 화면만 막는 게 아니라 회원용 API도 FastAPI의 `get_current_user`를 거치게 해서 쿠키를 다시 검사해요(지금은 `/api/auth/me`, 앞으로 붙는 API도 같은 방식). 그래서 주소를 직접 호출해도 막혀요.
     - 아쉬운 점: 서명 쿠키라 서버에 세션을 저장하지 않아서, 로그아웃해도 쿠키가 유출됐다면 만료(7일)까지는 유효해요. 서버에서 무효화할지는 Q-017로 남겨 뒀어요.
2. **질문 (AI 작성)**: 멀티유저 환경에서 다른 사용자의 기록(노트·조각)이 조회되거나 RAG 근거로 섞이는 사고를 막기 위해 DB 스키마와 서비스 계층을 어떻게 설계했나요?
   - 답 (사용자 확인 — AI 초안을 외워 설명, 2026-11-10):
     - DB와 코드, 두 겹으로 막았어요.
     - DB: 노트(`notes`)와 조각(`chunks`) 테이블에 모두 `user_id`를 외래키로 두고, 사용자를 지우면 그 사람 데이터가 같이 지워지게 `ON DELETE CASCADE`를 걸었어요. 노트의 같은 글 중복을 막는 UNIQUE도 `(user_id, content_hash)`로 걸어서, 사용자별로만 중복을 막아요.
     - 코드: 노트 · 조각을 조회하는 함수는 전부 `user_id`를 필수 인자로 받고(`list_notes_for_user` 등), `user_id` 없이 조회하는 함수는 아예 만들지 않았어요. 단건 조회도 `note_id`와 `user_id`를 같이 걸어서, B가 A의 노트 번호를 알아도 못 봐요.
     - `user_id`는 사용자가 보낸 값이 아니라 서버가 세션 쿠키에서 꺼낸 값만 써요.
     - 조각에도 `user_id`를 직접 둔 이유는, 나중에 벡터 검색(RAG)을 할 때 조인 없이 바로 사용자 조건을 걸어 다른 사람 기록이 근거로 섞이지 않게 하려는 거예요(D-004).
     - "A의 노트가 B에게 안 보인다"와 "사용자를 지우면 데이터도 지워진다"를 테스트로 고정했어요.
3. **질문 (AI 작성)**: OAuth 로그인에서 `state` 쿠키 검증과 세션 쿠키 검증에 같은 `SESSION_SECRET`을 쓰면서 토큰 바꿔치기(OAuth `state` 토큰을 세션 쿠키 자리에 넣는 공격)는 어떻게 막았나요?
   - 답 (사용자 확인 — AI 초안을 외워 설명, 2026-11-10):
     - state는 로그인 요청 위조를 막는 값이에요. 로그인을 시작할 때 무작위 state를 쿠키에 저장하고 구글에도 같이 보낸 뒤, 돌아왔을 때 주소의 state와 쿠키의 state가 같은지 비교해요.
     - 문제는 state 토큰과 세션 토큰을 같은 비밀키로 서명한다는 점이에요. 서명만 보면 둘 다 "진짜"라서, state 토큰을 세션 쿠키 자리에 넣으면 통과할 수도 있어요.
     - 그래서 토큰 안에 용도(`purpose`)를 넣었어요. 세션 토큰은 `session`과 사용자 번호, state 토큰은 `oauth_state`와 무작위 값만 담아요. 검사할 때 서명뿐 아니라 "기대한 용도가 맞는지"도 확인해서, 용도가 다르면 거부해요(401).
     - 용도는 서명된 내용 안에 있어서 공격자가 용도만 바꿀 수도 없어요. 바꾸면 서명이 깨지니까요. 만료 시간도 같이 검사해요(state 10분, 세션 7일).
     - 이 바꿔치기 경우를 테스트로 확인했어요. 더 단단히 하려면 용도별로 키를 따로 쓰는 방법도 있어요.

최종 수정: 2026-11-10 · 관련: D-004, D-008, D-010, D-013
