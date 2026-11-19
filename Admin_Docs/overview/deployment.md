# 배포 체크리스트 (D-033 — Vercel Services 한 프로젝트 + Supabase, 서울)

## 한눈에 보기 (코드 몰라도 OK)
상태: [준비] 코드 준비 끝(F-016). 아래를 위에서부터 차례로 하면 배포돼요. 비밀값은 이 문서 · 커밋에 적지 않고 각 콘솔에만 넣어요.

```
                      ┌─ /api/* ──▶ 서비스 backend (FastAPI) ─▶ Supabase (PostgreSQL, 서울)
브라우저 ─▶ didim.vercel.app ┤                    ▲             └▶ NVIDIA AI API
   (로그인 쿠키는 이 주소)   └─ 그 밖 ──▶ 서비스 frontend (Next.js) ─┘ 내부 주소 BACKEND_URL(binding)
```
- 설정은 레포 맨 위 `vercel.json`(서비스 두 개 · 경로 · binding · 지역). 주소는 하나라 아래 `<주소>`는 모두 같은 값이에요.

## 1. Supabase (DB)
- [ ] 프로젝트 만들기 — **지역은 서울(ap-northeast-2)**(Vercel 함수 icn1과 같게), DB 비밀번호는 길게 새로(비밀번호 관리자에만 보관)
- [ ] **Project Settings → Data API 끄기**(또는 노출 스키마에서 `public` 빼기) — 디딤은 RLS를 쓰지 않아 켜 두면 테이블이 REST로 열려요
- [ ] Database → Settings → **Enforce SSL** 켜기(암호화 없는 접속 거부)
- [ ] Connect → **Session pooler** 주소 복사. 드라이버 표기는 로컬 `DATABASE_URL`과 같게. SSL은 `sslmode=verify-full&sslrootcert=<Supabase CA 인증서 파일>`(인증서는 공개 파일, 대시보드에서 받음 — Vercel에서 쓰려면 `backend/`에 커밋하고 그 경로를 적은 뒤 미리보기 배포의 `/api/health`로 연결 확인) — 어려우면 최소 `sslmode=require`(암호화만, 인증서 검증 없음)
- [ ] 비밀번호가 든 주소를 **명령 줄에 쓰지 않기**(셸 기록에 남음). 가린 입력으로 환경변수에 넣고, 끝나면 지우기:
  - PowerShell 7.1+: `$env:DATABASE_URL = Read-Host -MaskInput` → 아래 명령 → `Remove-Item Env:DATABASE_URL`
  - Windows PowerShell 5.1: `$s = Read-Host -AsSecureString; $env:DATABASE_URL = [Net.NetworkCredential]::new('', $s).Password` → 아래 명령 → `Remove-Item Env:DATABASE_URL; Remove-Variable s`(또는 창 닫기)
  - Git Bash: `read -rs DATABASE_URL; export DATABASE_URL` → 아래 명령 → `unset DATABASE_URL`
  - 이미 기록에 남았다면 그 줄을 지우거나 DB 비밀번호를 바꾸기
- [ ] 내 컴퓨터에서 구조 만들기: `cd backend` → `uv run alembic upgrade head`
  - `pg_trgm` · `btree_gin` 확장 권한 오류가 나면 Database → Extensions에서 켜고 다시
- [ ] 샘플 데이터: `uv run python -m scripts.seed_sample` (AI 안 부름) — 끝나면 환경변수 지우기

## 2. 구글 로그인 (Google Cloud Console)
- [ ] 운영용 OAuth 클라이언트 새로(웹 애플리케이션) — 로컬 것과 분리
- [ ] 승인된 리디렉션 URI: `https://<주소>/api/auth/google/callback`
- [ ] 승인된 JavaScript 원본: `https://<주소>`
- [ ] OAuth 동의 화면은 '테스트' 그대로, 테스트 사용자에 본인 Gmail(서버 허용 목록 F-015와 두 겹)
- [ ] (노션을 쓰면) 노션 통합 리디렉션 `https://<주소>/api/notion/callback`

## 3. Vercel 프로젝트 만들기 (New Project 화면)
- [ ] GitHub 레포 가져오기 → Project Name `didim`(주소는 보통 `https://didim.vercel.app` — 이미 있으면 다른 이름이 붙으니 배포 뒤 실제 주소 확인)
- [ ] **Root Directory `./`**(레포 맨 위), **Application Preset `Services`** — 맨 위 `vercel.json`을 읽어 backend · frontend 두 서비스로 만들어요. 'Import single project'는 누르지 않기
- [ ] Environment Variables(Deploy 전에, 비밀값은 종류를 **Sensitive**로 — 넣은 뒤엔 대시보드에서도 다시 못 읽음). 두 서비스가 같이 써요:
  - `DATABASE_URL`(1의 pooler 주소) · `SESSION_SECRET`(새로: `python -c "import secrets; print(secrets.token_urlsafe(48))"`)
  - `GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` · `GOOGLE_REDIRECT_URI=https://<주소>/api/auth/google/callback`(2와 한 글자도 같게)
  - `FRONTEND_URL=https://<주소>` · `SITE_URL=https://<주소>` · `COOKIE_SECURE=true` · `ALLOWED_LOGIN_EMAILS=<본인 Gmail>`(비우면 백엔드가 뜨지 않음 — F-015)
  - `LLM_PROVIDER=nvidia` · `NVIDIA_API_KEY` · `NVIDIA_MODEL`
  - (노션) `NOTION_CLIENT_ID` · `NOTION_CLIENT_SECRET` · `NOTION_REDIRECT_URI=https://<주소>/api/notion/callback` · `NOTION_TOKEN_KEY`(새로)
  - **`BACKEND_URL`은 넣지 않기** — Vercel이 frontend 서비스에 내부 주소를 넣어 줘요(binding)
- [ ] Deploy
- [ ] 실제 주소가 `didim.vercel.app`이 아니면: `FRONTEND_URL` · `SITE_URL` · `GOOGLE_REDIRECT_URI` · (노션) `NOTION_REDIRECT_URI`와 구글 · 노션 콘솔을 그 주소로 고치고 다시 배포(`SITE_URL`은 빌드 때 읽혀서 다시 배포해야 반영)

## 4. Vercel 설정 (배포 뒤 한 번)
- [ ] Settings → Functions: **Fluid compute 켜짐**, 함수 지역이 **icn1(서울)**인지(맨 위 `vercel.json`의 `regions` — 안 먹었으면 여기서 고르기), backend 함수의 Max Duration이 **150초 이상**인지(Hobby 기본 300초 — 낮으면 Default Max Duration 150으로)
- [ ] Settings → Deployment Protection: 미리보기 배포 보호 켜기. 레포가 공개면 Git Fork Protection 켜짐 확인
- [ ] Firewall: `/api/auth/*` · `/api/demo*` 요청 횟수 제한 규칙(무료 한도 소진 방지), 공격받으면 Attack Challenge Mode — 서비스 방식이라 한 곳에서 둘 다 적용
- [ ] CLI로 배포할 때는 `.gitignore`가 아니라 `.vercelignore`를 따름 — 레포 맨 위 `.vercelignore` 하나가 `.env` · `.env.*`를 뺌(Root가 `./`라서)

## 5. 확인
- [ ] `https://<주소>/api/health` → `{"status":"ok"}`(backend 서비스)
- [ ] 랜딩 첫 화면 평가 수치 · `/report` 수치 — frontend가 binding으로 backend를 부르는지, `eval/summary`가 backend에 같이 묶였는지
- [ ] `/demo` → 샘플 체험, [체험 끝내기] → 로그아웃
- [ ] 본인 Gmail 로그인 → `/home`, 다른 Gmail → '지금은 샘플 체험만 열려 있어요'(또는 구글 화면에서 먼저 막힘)
- [ ] 퀴즈 만들기 한 번 — AI 호출 · 응답 시간(100초 안)
- [ ] 로그인 뒤 `/home` 응답 시간 — 몇 초씩 걸리면 함수 · DB 지역이 다른지 확인(NullPool이라 요청마다 새로 연결)
- [ ] 응답 머리말: 화면 `X-Frame-Options: DENY` · CSP 등, `/api/*` 응답 `nosniff`(F-016)
- [ ] 운영인데 허용 목록을 빼면 backend가 뜨지 않는지(미리보기 배포에서 `ALLOWED_LOGIN_EMAILS`만 비워 로그 확인 — F-015 · F-016)
- [ ] Claude에게 확인 요청: 위 결과와 Vercel 빌드 로그(서비스 두 개 · 진입 `index:app` · 지역)

## 알아 둘 것
- 공개되는 건 한 주소뿐이에요. `/api/*`만 backend로 가고, backend의 `/docs`처럼 `/api` 밖 경로는 밖에서 닿지 않아요(운영에선 꺼져 있기도 함 — D-032).
- 환경변수는 두 서비스가 같이 봐요 — frontend 빌드 · 서버에도 DB 주소 · 비밀키가 보여요(브라우저로는 안 나감). 그래서 지킬 규칙: 비밀값에 `NEXT_PUBLIC_` 붙이지 않기, `next.config`의 `env` 쓰지 않기, `process.env` 전체를 로그로 남기지 않기. frontend 설치는 `npm ci`(lockfile 그대로 — 새 버전이 몰래 들어오는 것만 막고 설치 스크립트는 그대로 돎)(D-033).
- frontend 폴더에서 `vercel env pull` 하지 않기 — `.env.local`에 `VERCEL=1`이 들어가 로컬에서 `/api/*` 넘김(next.config rewrites)이 꺼지고, 운영 비밀값이 로컬 파일로 내려와요(F-016 5차 R2).
- Services는 아직 Beta예요. 막히면 프로젝트 두 개 방식(D-032 처음 안)으로 되돌릴 수 있어요 — 이전 체크리스트는 git 기록에.

## 배포 뒤 남은 결정
- 주소(Q-015) — 도메인을 붙이면 `SITE_URL` · `FRONTEND_URL` · 구글 · 노션 리디렉션 URI를 같이 바꾼다
- 운영에서 Secure 쿠키를 코드로 강제할지(지금은 설정값 + 시작 경고)

최종 수정: 2026-11-19 · 관련: D-033, D-032, D-031, D-010, F-015, F-016, Q-015
