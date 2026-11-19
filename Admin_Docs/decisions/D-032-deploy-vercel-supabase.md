# D-032 배포는 Vercel 두 프로젝트(화면 · 백엔드) + Supabase(DB)로 한다

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 사용자가 골랐어요(2026-11-19). **구성(프로젝트 두 개)은 [D-033](D-033-vercel-services-one-project.md)으로 대체** — Services 한 프로젝트. 아래 값(100초 · 80초 · 3MB · 서울 · NullPool · 보안)은 그대로. 코드 준비는 F-016, 실제 배포 · 확인은 체크리스트([overview/deployment.md](../overview/deployment.md)).
무엇을: 화면(Next.js)과 백엔드(FastAPI)를 각각 Vercel 프로젝트로, DB는 Supabase PostgreSQL로 올려요. 브라우저는 화면 주소하고만 이야기하고, 화면이 `/api/*`를 백엔드로 넘겨요(D-010 그대로).
왜 (사용자 선택): 서비스 셋을 따로 관리하지 않고 Vercel · Supabase 두 곳으로 끝나고, 무료 플랜에서 잠들어 수십 초 기다리는 일이 없어서요. 대신 Vercel의 상한 두 가지에 맞춰 디딤의 값을 낮췄어요.

## 개발자 상세

### 후보
| 후보 | 장점 | 단점 |
|---|---|---|
| A. Vercel(화면) + Render · Railway(백엔드) + Neon · Supabase | 백엔드가 보통 서버라 시간 · 크기 제약이 적음 | 관리할 곳 셋, 무료 플랜은 잠들어 첫 요청이 느림 |
| B. Vercel 두 프로젝트 + Supabase (선택) | 두 곳으로 끝, Python 3.13 · uv 그대로, 잠들지 않음 | 서버리스 함수 — 요청 4.5MB · 바깥으로 넘긴 요청 120초 상한, DB는 풀러로 |
| C. 한 서버에 Next(`next start`) + FastAPI | 상한을 우리가 정함(200초 그대로) | 서버 · HTTPS · 배포를 직접 관리 |

### 결정
- 구성: Vercel 프로젝트 ① `frontend`(Root `frontend`, 환경변수 `BACKEND_URL` · `SITE_URL`) ② `backend`(Root `backend`, 진입 `index.py`, `.python-version` 3.13). DB는 Supabase — 접속은 풀러 주소(Session 모드부터, SSL).
- Vercel 상한에 맞춘 값(사용자 선택 2026-11-19):
  - AI 전체 시간 상한 180초 → **100초**(`app/llm/settings.py`). ①에서 ②로 넘긴 요청은 다른 주소라 '바깥 서버로 넘김'이고 120초에 끊겨서 — 넘으면 화면은 504인데 서버는 저장하는 일(T-005)을 막으려고. D-022의 '요청 한 번 + 상한' 구조는 그대로, 값만 바뀜.
  - 기록 가져오기 합계 20MB → **3MB**(파일 20개 · 파일당 1MB는 그대로). Vercel 함수는 요청 하나를 4.5MB까지 받아서, 요청 상한(합계 + 1MB = 4MB)이 그 안에 들게. 다른 방법 — 파일 3개로 줄이기 — 은 고르지 않았다.
- 보안(사용자 선택 2026-11-19): 운영에서 FastAPI 문서 경로(`/docs` · `/redoc` · `/openapi.json`)를 끈다(운영 판단은 F-015 `is_production`과 같은 기준). 화면에 기본 보안 머리말(`X-Frame-Options: DENY` · `frame-ancestors 'none'` · `nosniff` · `Referrer-Policy`).
- 배포 때 콘솔에서 직접 할 것(코드 밖): Supabase **Data API 끄기**(디딤은 RLS를 쓰지 않아 켜 두면 테이블이 REST로 열림), DB 비밀번호 새로 · SSL, Vercel 환경변수는 Production에만 · 미리보기 배포 보호, 운영용 `SESSION_SECRET` · 구글 OAuth 클라이언트 새로. 목록은 체크리스트에.
- 덧붙임(사용자 선택 2026-11-19, F-016 1차 리뷰):
  - 노션 가져오기 시간 예산 140초 → **80초**(요청 하나가 넘칠 여유 40초 — 120초 안). 저장 여유는 **20초** 하나로(AI 100 + 20 = 120).
  - 운영 DB 연결은 쥐고 있지 않는다(NullPool) — Vercel 함수 여러 개가 Supabase 풀러를 채우지 않게.
  - 허용 목록 검사(F-015)는 시작 처리(lifespan)가 아니라 **앱을 불러올 때** — 런타임이 lifespan을 건너뛰어도 열린 채로 뜨지 않게.
  - (D-033으로 대체 — 기본값(Hobby 300초) + 배포 뒤 150초 이상 확인) 백엔드 함수 최대 실행 시간 150초를 `backend/vercel.json`에 적는다(Vercel 설정 기본값에 기대지 않음). 150 = 화면이 끊는 120초 + 그 뒤 저장 · 정리가 끝날 여유 30초(Hobby 최대 300초 안).
  - 지역은 **서울**: Vercel 함수 `icn1`(두 `vercel.json`의 `regions`), Supabase `ap-northeast-2`. NullPool이라 요청마다 DB에 새로 연결해서, 지역이 다르면 요청마다 수 초가 늘어서(사용자 선택 2026-11-19, F-016 2차 리뷰 R2).
  - 보안 머리말: 화면에 부분 CSP(`frame-ancestors 'none'; object-src 'none'; base-uri 'self'`), 백엔드 응답에 `nosniff`, 로그인 쿠키가 실린 '요청'의 응답에 `Cache-Control: no-store`(공개 응답은 그대로 — 로그인 콜백의 302처럼 요청에 쿠키가 없는 응답엔 안 붙지만 개인 기록이 없음). 처리하지 못한 예외의 500은 Starlette가 미들웨어 바깥에서 만들어 머리말이 없다 — 본문이 'Internal Server Error' 한 줄이라 그대로 둔다(F-016 3차 리뷰 R2). 넣지 않은 것 — 전체 CSP(nonce 방식은 cacheComponents와 부딪힘), `form-action`(구글 로그인 이동과 부딪힐 수 있음), HSTS(`*.vercel.app`은 .app 최상위가 브라우저 HSTS 목록에 있어 처음부터 HTTPS — 사용자 도메인을 붙일 때 Q-015에서 다시), Permissions-Policy.
  - 다음에(MVP 뒤): DB 두 번째 겹 — public 테이블 RLS(정책 없이) + Supabase 공개 역할 권한 회수, 실행용 최소 권한 역할.
- 백엔드(②) 주소는 화면이 넘기려면 공개여야 해서 사실상 공개 API다 — 주소가 숨겨졌다는 데 기대지 않고, 앞단이 넣는 머리말을 신뢰 근거로 삼지 않는다(Origin 검사는 CSRF 방어일 뿐), IP 기준 제한은 Vercel 방화벽에서. 지금 구조는 안전 — `vercel.app`은 공개 접미사라 ①의 쿠키가 ②로 가지 않고, CORS가 없고, 매 요청 쿠키를 확인한다(F-016 1차 리뷰 R2).
- 덧붙임(2026-11-19): **구성은 [D-033](D-033-vercel-services-one-project.md)으로 바뀌었다** — Vercel 프로젝트 두 개 대신 Services 한 프로젝트(주소 하나, `/api/*`는 Vercel이 바로 backend로). 위의 값(100초 · 80초 · 3MB · 서울 · NullPool · 보안)은 그대로.
- 이 결정으로 Q-012(FastAPI를 어디에)를 닫는다. 남은 것: 주소(Q-015), 운영에서 Secure 쿠키를 코드로 강제할지(지금은 `COOKIE_SECURE=true`로 설정하고 꺼져 있으면 시작 경고 — F-015).

### 확인한 근거 (2026-11-19 검색)
- Vercel: 바깥으로 넘긴 요청(external rewrite) 상한 120초(전에는 35초), Python 함수는 3.12 · 3.13 · 3.14, `pyproject.toml` + `uv.lock`을 읽음, Hobby 함수 실행 최대 300초, 요청 본문 4.5MB.
- Supabase: 풀러 Transaction 모드(6543)는 prepared statement를 지원하지 않음(끄거나 Session 모드).
- 확인 못 한 것(배포 때 확인): Supabase에서 `pg_trgm` · `btree_gin` 확장, Vercel이 `backend/eval/summary`를 함수에 같이 묶는지, Vercel 경유 시 `Sec-Fetch-Site` · `Origin`이 백엔드까지 가는지.

### 이 결정을 바꿔야 하는 조건
- AI 요청이 100초 안에 자주 못 끝나면(느린 모델 · 혼잡) → C(직접 서버)나 A로 옮기고 상한을 되돌린다.
- 기록을 3MB보다 크게 한 번에 올려야 하면 → 화면에서 나눠 보내기(여러 요청) 또는 A · C.
- Vercel · Supabase 무료 조건이 바뀌어 막히면 → A.

최종 수정: 2026-11-19 · 관련: D-010, D-022, D-031, Q-012, Q-015, F-002, F-015, F-016, T-005
