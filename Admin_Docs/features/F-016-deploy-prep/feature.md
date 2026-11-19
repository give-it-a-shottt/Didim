# F-016 배포 준비 (Vercel + Supabase)

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 코드 준비 · 리뷰 5차 [통과](2026-11-19, 4차부터 D-033 Services 한 프로젝트). 실제 배포는 [체크리스트](../../overview/deployment.md).
언제: 8주차, 배포 전(D-032)
무엇을: Vercel 상한에 맞게 값을 낮추고(AI 100초 · 가져오기 3MB), Vercel이 백엔드를 찾게 하고, 운영 보안(문서 경로 끄기 · 보안 머리말)을 넣어요.
왜: 배포를 Vercel + Supabase로 정해서(D-032, 구성은 D-033 — Services 한 프로젝트, DB는 D-034 — Vercel 연동 Neon).

## 설계 의도 (사용자 선택 2026-11-19 — 대화에서 고른 것)
- 배포 구성: Vercel 두 프로젝트(화면 · 백엔드) + Supabase. → 덧붙임(사용자 선택 2026-11-19): Vercel Services 한 프로젝트로 바꿈(D-033). → 덧붙임(사용자 선택 2026-11-19): DB는 Supabase 대신 Vercel에서 만드는 Neon. [AI 메모] 싱가포르 · sin1 · Production만은 AI 제안을 사용자가 계획으로 승인(D-034).
- 기록 가져오기: 합계만 3MB로(파일 20개 · 파일당 1MB 그대로).
- AI 시간 상한: Vercel 120초 안으로(100초).
- 보안: 운영에서 `/docs` 끄기, 화면 기본 보안 머리말.
- 완료 기준:
  1. 가져오기 요청 상한(합계 + 1MB)이 4.5MB보다 작다. 화면 · 서버의 합계 값이 같다.
  2. 한 요청이 걸리는 시간(AI 전체 상한 + 저장 여유, 노션 가져오기 예산 + 여유)이 120초 안이다. (사용자 확인 2026-11-19, 2차 리뷰 R4 — 처음 문장: 'AI 전체 상한 + 저장 여유가 120초 안이다.') [AI 메모: Services에선 120초 상한이 안 걸릴 가능성이 높지만 보수적으로 유지 — D-033]
  3. 운영(F-015 `is_production`)이면 FastAPI 문서 경로가 꺼진다. 로컬은 그대로.
  4. Vercel이 백엔드 앱을 찾는 진입 파일과 파이썬 버전 파일이 있다.
  5. 모든 화면 응답에 보안 머리말이 붙고, 백엔드 응답에는 nosniff가 붙는다. (사용자 확인 2026-11-19, 2차 리뷰 R4 — 처음 문장: '모든 화면 응답에 보안 머리말이 붙는다.')

## 결과 (AI 작성 — 구현 후)
- 시간 상한(120초 안): AI 전체 `DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS` 180 → 100 + 저장 여유 20, 노션 가져오기 예산 `NOTION_IMPORT_TIME_BUDGET_SECONDS` 140 → 80 + 넘칠 여유 40, 로컬 `next.config.ts` `PROXY_TIMEOUT_MS` 200 → 120초. 코드 주석의 옛 숫자도 고침.
- 가져오기: `config.MAX_IMPORT_TOTAL_BYTES` = 3MB(요청 상한 4MB < 4.5MB), 화면 `MAX_IMPORT_TOTAL_MB` = 3.
- 운영 판단(F-015 `is_production`)으로: 문서 경로 끄기(`config.api_docs_urls` → `main.py`), 운영 DB는 연결을 쥐지 않음(`db/session.py` `create_db_engine(pooled=False)` = NullPool), 허용 목록 검사는 앱을 불러올 때(`config.check_login_allowlist_from_env`, main.py 모듈 수준 — 처음엔 lifespan).
- Vercel: `backend/index.py`(`from app.main import app`), `backend/.python-version`(3.13). 처음엔 `.vercelignore` 두 개(backend/ · frontend/)와 `backend/vercel.json`(icn1 · 150초) · `frontend/vercel.json`(icn1)이었다가, Services 한 프로젝트로 바꾸며(D-033) 레포 맨 위 `vercel.json` 하나로 — 서비스 backend(진입 `index:app`) · frontend(binding `BACKEND_URL`), 경로 `/api/(.*)` → backend · 나머지 → frontend, `regions: ["sin1"]`(처음 icn1 → D-034에서 Neon 싱가포르에 맞춤). 함수 최대 시간은 Fluid 기본값(Hobby 300초)에 맡기고 대시보드에서 확인. 화면 `lib/backend.ts`는 `BACKEND_URL` 끝 `/` 제거. 4차 리뷰 반영: frontend 설치 `npm ci`, 레포 맨 위 `.vercelignore` 하나(하위 것은 지움), 배포에선 `next.config.ts` `/api/*` rewrites 끔(`VERCEL`), 환경변수 공유 위험과 규칙은 D-033.
- 보안 머리말: 화면 `next.config.ts` `headers()` — `X-Frame-Options: DENY` · `Content-Security-Policy: frame-ancestors 'none'; object-src 'none'; base-uri 'self'` · `nosniff` · `Referrer-Policy: strict-origin-when-cross-origin`. 백엔드 `app/api/security_headers.py`(순수 ASGI, 가장 바깥) — 모든 응답 `nosniff`, 로그인 쿠키가 실린 요청의 응답 `Cache-Control: no-store`.
- 체크리스트([overview/deployment.md](../../overview/deployment.md)): Vercel 안에서 Neon 만들기(싱가포르 · Production만 · 마이그레이션은 직접 주소 — D-034), 비밀값을 셸 기록에 남기지 않는 명령, Sensitive 환경변수, Fork Protection, Firewall 횟수 제한, Fluid compute · Max Duration 확인, 공개는 한 주소의 `/api/*`뿐이라는 점 · 환경변수 공유 규칙(D-033).
- 테스트: backend `tests/test_deploy_config.py` 9(맨 위 vercel.json · .vercelignore 포함, 요청 크기 · 한 요청 시간 · 문서 경로 함수 · 진입 파일 · 운영 앱 /docs 404(하위 프로세스) · 목록 없는 운영은 불러올 때 실패 · NullPool), `tests/test_security_headers.py` 3(nosniff · no-store · 가드 401/403 · 404), conftest가 앱을 불러오기 전에 운영 환경변수를 지움. frontend `tests/security-headers.spec.ts` 6경로(/ · /login · /report · /demo · /home · 없는 주소). 의존성 취약점 npm audit(운영) 0 · pip-audit 0.
- DB 주소 형식: `db/session.py` `normalize_database_url` — Neon · Vercel 연동의 `postgresql://` · `postgres://`를 `postgresql+psycopg://`로(D-034), 테스트 `test_db_config.py`.
- 실제 Vercel · Neon 배포로는 아직 확인 안 함(체크리스트 5).

## 리뷰
- [review/SUMMARY.md](review/SUMMARY.md) — 1차 [위험](노션 예산 140초 — 고침) → 2차 [주의](지역 · 테스트 · 문서) → 3차 [통과] → 4차 [주의](D-033 Services 전환 — .vercelignore · 환경변수 공유 · 문서) → 5차 [통과](제안 4 반영).
- 다음에 고칠 것: DB 두 번째 겹(RLS 정책 없이 + 공개 역할 권한 회수, 최소 권한 실행 역할) — MVP 뒤. `npm ci --ignore-scripts`를 미리보기로 시험할지.

## 열린 질문
- Q-015 주소, 운영 Secure 강제 여부(D-032 '남은 것')

최종 수정: 2026-11-19 · 관련: D-032, D-031, D-022, F-002, F-015, T-005
