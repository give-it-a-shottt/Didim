# 배포 체크리스트 (D-033 · D-034 — Vercel Services 한 프로젝트 + Vercel 연동 Neon, 싱가포르)

## 한눈에 보기 (코드 몰라도 OK)
상태: [됨] 배포 확인(2026-11-19) — 운영 주소 `https://didim-gamma.vercel.app`. [x]는 그날 한 것, [ ]는 아직 확인 안 한 것이에요. 비밀값은 이 문서 · 커밋에 적지 않고 각 콘솔에만 넣어요. 첫 배포에서 겪은 일은 [T-013](../troubleshooting/T-013-vercel-services-region-and-neon-setup.md).

```
                      ┌─ /api/* ──▶ 서비스 backend (FastAPI) ─▶ Neon PostgreSQL (싱가포르)
브라우저 ─▶ didim-gamma.vercel.app ┤                    ▲             └▶ NVIDIA AI API
   (로그인 쿠키는 이 주소)   └─ 그 밖 ──▶ 서비스 frontend (Next.js) ─┘ 내부 주소 BACKEND_URL(binding)
```
- 설정은 레포 맨 위 `vercel.json`(서비스 두 개 · 경로 · binding). 지역은 `vercel.json`의 sin1이 먹지 않아 대시보드에서 골라요(4, T-013). 주소는 하나라 아래 `<주소>`는 모두 같은 값(`didim-gamma.vercel.app`)이에요.

## 1. Vercel 프로젝트 먼저 만들기 + Neon 연결
- [x] Vercel New Project: GitHub 레포 → Project Name `didim` → **Root Directory `./`** · **Application Preset `Services`**('Import single project'는 누르지 않기)
- [x] 이 단계에선 환경변수 없이 **Deploy** — 첫 배포는 DB가 없어 기능이 안 돼도 괜찮아요(주소를 받으려는 것). 실제 주소를 확인(Settings → Domains — 해시가 붙은 배포별 주소 말고, 운영 주소 `didim-gamma.vercel.app`)
- [x] 프로젝트 → **Storage**(또는 Marketplace) → **Neon** → Install / Create:
  - Region: **Singapore (aws-ap-southeast-1)** — Vercel 함수 sin1과 같게(D-034). 칸의 ▾를 눌러 **목록에서 직접 클릭**하고, 만든 직후 Storage → DB → Region이 'AWS Asia Pacific 1 (Singapore)'인지 확인(글자만 들어가 Ohio로 만들어진 적 있음 — T-013)
  - Auth · Realtime은 끄기(디딤은 로그인을 직접 함 — D-010)
  - Installation Plan: **Free**(없으면 멈추고 Claude에게)
  - 연결할 프로젝트 `didim`, Environments는 **Production만**(Preview 체크 해제 — 미리보기가 운영 DB를 쓰지 않게), 미리보기용 DB 브랜치 만들기는 끄기
  - **Custom Prefix에 `DATABASE`를 직접 입력**(회색 `STORAGE`는 예시 — 뒤에 `_URL`이 붙어 `DATABASE_URL`이 됨), Sensitive 켜기
- [x] Settings → Environment Variables에 `DATABASE_URL` · `DATABASE_URL_UNPOOLED` 등이 **자동으로 생겼는지** 확인(직접 넣지 않음)
- [x] **`vercel env pull`은 하지 않기**(운영 비밀값이 로컬 파일로 — D-033)
- [x] 내 컴퓨터에서 DB 구조 만들기 — **직접 주소(`DATABASE_URL_UNPOOLED`, 호스트에 `-pooler`가 없는 것)**를 Vercel Storage → Neon 화면(또는 거기서 여는 Neon 콘솔의 Connect)에서 한 번 보고, 명령 줄에 쓰지 말고 가린 입력으로:
  - PowerShell 7.1+: `$env:DATABASE_URL = Read-Host -MaskInput` → `cd backend` → **[확인]** → `uv run alembic upgrade head` → `uv run python -m scripts.seed_sample` → `Remove-Item Env:DATABASE_URL`
  - Windows PowerShell 5.1: `$s = Read-Host -AsSecureString; $env:DATABASE_URL = [Net.NetworkCredential]::new('', $s).Password` → 위 명령 → `Remove-Item Env:DATABASE_URL; Remove-Variable s`(또는 창 닫기)
  - Git Bash: `read -rs DATABASE_URL; export DATABASE_URL` → 위 명령 → `unset DATABASE_URL`
  - **[확인]** 주소를 넣은 뒤 · `alembic` 전에 어디에 붙는지 보기(비밀번호는 안 나옴): `uv run python -c "from sqlalchemy.engine import make_url; from app.config import load_settings; print(make_url(load_settings().database_url).host)"` → `neon.tech`로 끝나고 `-pooler`가 없어야 해요(`localhost`거나 비었으면 멈추기)
  - 값만 복사해요 — `.env.local` 탭의 `DATABASE_URL_UNPOOLED="…"`에서 따옴표 안쪽(`postgresql://`부터). 이름 · 따옴표가 섞이면 `Could not parse SQLAlchemy URL`(T-013). 주소 전체는 대화 · 채팅에 붙여 넣지 않기
  - 주소가 `postgresql://`로 시작해도 그대로 붙여 넣으면 돼요(디딤이 바꿔 씀 — D-034). 이미 셸 기록에 남았다면 그 줄을 지우거나 Neon에서 비밀번호를 바꾸기
  - `alembic upgrade head` 다음(주소를 지우기 전)에 `uv run alembic current`가 마지막 버전(head)을 보여 주는지 확인
  - `pg_trgm` · `btree_gin` 확장 오류가 나면 멈추고 Claude에게 — 2026-11-19 오류 없이 head까지, 샘플 시드도 결과 파일과 저장 개수가 같음

## 2. 구글 로그인 (Google Cloud Console)
- [x] 운영용 OAuth 클라이언트 새로(웹 애플리케이션) — 로컬 것과 분리
- [x] 승인된 리디렉션 URI: `https://<주소>/api/auth/google/callback`
- [x] 승인된 JavaScript 원본: `https://<주소>`
- [x] OAuth 동의 화면은 '테스트' 그대로, 테스트 사용자에 본인 Gmail(서버 허용 목록 F-015와 두 겹)
- [ ] (노션을 쓰면 — 나중에 하기로, 2026-11-19) 노션 통합 리디렉션 `https://<주소>/api/notion/callback`

## 3. 나머지 환경변수 넣기 (Settings → Environment Variables)
- [x] 아래를 **Production**에 넣기(비밀값은 Type **Secret**, 나머지는 **Config** — 화면에 따라 자물쇠 = Sensitive). 노션 4개는 아직. `DATABASE_URL`은 Neon이 넣어 줬으니 넣지 않기:
  - `SESSION_SECRET`(새로: `cd backend` → `uv run python -c "import secrets; print(secrets.token_urlsafe(48))"`)
  - `GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` · `GOOGLE_REDIRECT_URI=https://<주소>/api/auth/google/callback`(2와 한 글자도 같게)
  - `FRONTEND_URL=https://<주소>` · `SITE_URL=https://<주소>` · `COOKIE_SECURE=true` · `ALLOWED_LOGIN_EMAILS=<본인 Gmail>`(비우면 백엔드가 뜨지 않음 — F-015)
  - `LLM_PROVIDER=nvidia` · `NVIDIA_API_KEY` · `NVIDIA_MODEL`(`backend/.env.example`과 같은 값)
  - (노션) `NOTION_CLIENT_ID` · `NOTION_CLIENT_SECRET` · `NOTION_REDIRECT_URI=https://<주소>/api/notion/callback` · `NOTION_TOKEN_KEY`(새로)
  - **넣지 않기**: `BACKEND_URL`(Vercel이 binding으로), `DATABASE_URL`(Neon이), `EXAONE_API_KEY` · `LLM_BASE_URL` · `LLM_MODEL`, `NEXT_PUBLIC_`으로 시작하는 이름
  - 로컬 `.env`를 통째로 붙여 넣지 않기(localhost · 개발 DB 값이라 틀림)
- [x] Deployments → 최신 배포 → **Redeploy**(환경변수는 새 배포부터 반영 — Ready · Current가 된 배포를 열기. 이전 배포를 보면 'DATABASE_URL이 비어 있어요'로 500 — T-013)

## 4. Vercel 설정 (배포 뒤 한 번)
- [x] Settings → Functions: **Fluid compute 켜짐**, Function Region을 **Singapore(sin1)로 고르기** — Services에선 `vercel.json`의 `regions`가 먹지 않아 미국으로 되어 있었음(T-013). 고른 뒤 Redeploy, `/api/health` 응답 머리말 `x-vercel-id`의 가운데가 `sin1`인지 확인, backend 함수의 Max Duration이 **150초 이상**인지(Hobby 기본 300초 — 낮으면 Default Max Duration 150으로)
- [x] Settings → Deployment Protection: 미리보기 배포 보호 켜기. 레포가 공개면 Git Fork Protection 켜짐 확인
- [x] Firewall: 요청 횟수 제한 규칙 `auth-demo-rate-limit` — Request Path가 `/api/auth/google`로 시작 **또는** `/api/demo/session`, IP당 60초 20번, 넘으면 거부(무료 한도 소진 방지). `/api/auth/me`는 넣지 않음(화면 서버가 페이지마다 부름). 저장 뒤 **Publish**까지, 공격받으면 Attack Challenge Mode — 서비스 방식이라 한 곳에서 둘 다 적용
- [ ] CLI로 배포할 때는 `.gitignore`가 아니라 `.vercelignore`를 따름 — 레포 맨 위 `.vercelignore` 하나가 `.env` · `.env.*`를 뺌(Root가 `./`라서)

## 5. 확인
- [x] `https://<주소>/api/health` → `{"status":"ok"}`(backend 서비스)
- [x] 랜딩 첫 화면 평가 수치 · `/report` 수치 — frontend가 binding으로 backend를 부르는지, `eval/summary`가 backend에 같이 묶였는지
- [x] `/demo` → 샘플 체험, [체험 끝내기] → 로그아웃
- [x] 본인 Gmail 로그인 → `/home`, 다른 Gmail → '지금은 샘플 체험만 열려 있어요'(또는 구글 화면에서 먼저 막힘)
- [x] 퀴즈 만들기 한 번 — AI 호출 · 응답 시간(100초 안) — 1분 안
- [ ] 로그인 뒤 `/home` 응답 시간 — 몇 초씩 걸리면 함수 · DB 지역이 다른지 확인(NullPool이라 요청마다 새로 연결)
- [ ] 10분쯤 쉰 뒤 첫 `/api/health` · `/home` — Neon이 잠들었다 깨는 시간. 연결 시간 제한(5초)에 걸려 오류가 나면 Claude에게(D-034)
- [ ] 같은 화면을 10번쯤 새로 고침 — 가끔만 나는 DB 오류(`prepared statement` 등)가 없는지(Neon 풀러 — D-034)
- [x] 응답 머리말: 화면 `X-Frame-Options: DENY` · CSP 등, `/api/*` 응답 `nosniff`(F-016) — HSTS · Referrer-Policy도 있음, `/docs` · `/api/docs` 404, robots · sitemap이 운영 주소
- [ ] 운영인데 허용 목록을 빼면 backend가 뜨지 않는지(미리보기 배포에서 `ALLOWED_LOGIN_EMAILS`만 비워 로그 확인 — F-015 · F-016)
- [ ] Claude에게 확인 요청: 위 결과와 Vercel 빌드 로그(서비스 두 개 · 진입 `index:app` · 지역)

## 알아 둘 것
- 공개되는 건 한 주소뿐이에요. `/api/*`만 backend로 가고, backend의 `/docs`처럼 `/api` 밖 경로는 밖에서 닿지 않아요(운영에선 꺼져 있기도 함 — D-032).
- 환경변수는 두 서비스가 같이 봐요 — frontend 빌드 · 서버에도 DB 주소 · 비밀키가 보여요(브라우저로는 안 나감). 그래서 지킬 규칙: 비밀값에 `NEXT_PUBLIC_` 붙이지 않기, `next.config`의 `env` 쓰지 않기, `process.env` 전체를 로그로 남기지 않기. frontend 설치는 `npm ci`(lockfile 그대로 — 새 버전이 몰래 들어오는 것만 막고 설치 스크립트는 그대로 돎)(D-033).
- frontend 폴더에서 `vercel env pull` 하지 않기 — `.env.local`에 `VERCEL=1`이 들어가 로컬에서 `/api/*` 넘김(next.config rewrites)이 꺼지고, 운영 비밀값이 로컬 파일로 내려와요(F-016 5차 R2).
- Services는 아직 Beta예요. 막히면 프로젝트 두 개 방식(D-032 처음 안)으로 되돌릴 수 있어요 — 이전 체크리스트는 git 기록에.

## 배포 뒤 남은 결정
- 주소: `didim-gamma.vercel.app` 그대로로 정함(Q-015 닫힘, 2026-11-19). 나중에 도메인을 붙이면 `SITE_URL` · `FRONTEND_URL` · 구글 · 노션 리디렉션 URI를 같이 바꾼다
- Neon 무료는 5분 쉬면 잠들어 오랜만의 첫 요청이 느려요 — 문제가 되면 다시 본다(D-034)
- 운영에서 Secure 쿠키를 코드로 강제할지(지금은 설정값 + 시작 경고)

최종 수정: 2026-11-19 · 관련: T-013, D-034, D-033, D-032, D-031, D-010, F-015, F-016, Q-015
