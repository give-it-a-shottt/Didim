# 배포 체크리스트 (D-032 — Vercel 두 프로젝트 + Supabase)

## 한눈에 보기 (코드 몰라도 OK)
상태: [준비] 코드 준비 끝(F-016). 아래를 위에서부터 차례로 하면 배포돼요. 비밀값은 이 문서 · 커밋에 적지 않고 각 콘솔에만 넣어요.

```
브라우저 ─▶ Vercel ① frontend (Next.js) ── /api/* 넘김 ─▶ Vercel ② backend (FastAPI) ─▶ Supabase (PostgreSQL)
            (로그인 쿠키는 ① 주소에)                                                   └▶ NVIDIA AI API
```

## 1. Supabase (DB)
- [ ] 프로젝트 만들기 — **지역은 서울(ap-northeast-2)**(Vercel 함수 icn1과 같게, D-032), DB 비밀번호는 길게 새로(비밀번호 관리자에만 보관)
- [ ] **Project Settings → Data API 끄기**(또는 노출 스키마에서 `public` 빼기) — 디딤은 RLS를 쓰지 않아 켜 두면 테이블이 REST로 열려요
- [ ] Database → Settings → **Enforce SSL** 켜기(암호화 없는 접속 거부)
- [ ] Connect → **Session pooler** 주소 복사. 드라이버 표기는 로컬 `DATABASE_URL`과 같게. SSL은 `sslmode=verify-full&sslrootcert=<Supabase CA 인증서 파일>`(인증서는 공개 파일, 대시보드에서 받음 — Vercel 함수에서 쓰려면 `backend/`에 커밋하고 그 경로를 적은 뒤 미리보기 배포의 `/api/health`로 연결 확인) — 어려우면 최소 `sslmode=require`(암호화만, 인증서 검증 없음)
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
- [ ] 승인된 리디렉션 URI: `https://<① 주소>/api/auth/google/callback` — **백엔드(②) 주소가 아니라 화면(①) 주소**
- [ ] 승인된 JavaScript 원본: `https://<① 주소>`
- [ ] OAuth 동의 화면은 '테스트' 그대로, 테스트 사용자에 본인 Gmail(서버 허용 목록 F-015와 두 겹)
- [ ] (노션을 쓰면) 노션 통합 리디렉션 `https://<① 주소>/api/notion/callback`

## 3. Vercel ② backend
- [ ] 레포 연결, Root Directory `backend`(Python 3.13은 `.python-version`, 진입은 `index.py`, 함수 최대 150초는 `vercel.json`)
- [ ] Settings → Functions: **Fluid compute 켜짐**, 배포된 함수의 Max Duration이 150초인지(`vercel.json`이 먹었는지) 확인 — 안 먹었으면 Default Max Duration을 150으로. 함수 지역이 **icn1(서울)**인지(`vercel.json`의 `regions`)
- [ ] 환경변수(**Production에만**, 비밀값은 종류를 **Sensitive**로 — 넣은 뒤엔 대시보드에서도 다시 못 읽음):
  - `DATABASE_URL`(1의 pooler 주소) · `SESSION_SECRET`(새로: `python -c "import secrets; print(secrets.token_urlsafe(48))"`)
  - `GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` · `GOOGLE_REDIRECT_URI`(2의 리디렉션 URI와 한 글자도 같게)
  - `FRONTEND_URL=https://<① 주소>` · `COOKIE_SECURE=true` · `ALLOWED_LOGIN_EMAILS=<본인 Gmail>`(비우면 시작 안 함 — F-015)
  - `LLM_PROVIDER=nvidia` · `NVIDIA_API_KEY` · `NVIDIA_MODEL`
  - (노션) `NOTION_CLIENT_ID` · `NOTION_CLIENT_SECRET` · `NOTION_REDIRECT_URI` · `NOTION_TOKEN_KEY`(새로)
- [ ] 배포 뒤 `https://<② 주소>/api/health` → `{"status":"ok"}`, `https://<② 주소>/docs` → 404(운영이면 꺼짐)
- [ ] 미리보기 배포 보호(Deployment Protection) 켜기. 레포가 공개면 Git Fork Protection 켜짐 확인
- [ ] CLI로 배포할 때는 `.gitignore`가 아니라 `.vercelignore`를 따름 — `backend/` · `frontend/`에 `.env*`를 빼는 `.vercelignore`가 있음
- [ ] Firewall: ① · ② 모두 `/api/auth/*` · `/api/demo*` 요청 횟수 제한 규칙(무료 한도 소진 방지), 공격받으면 Attack Challenge Mode

## 4. Vercel ① frontend
- [ ] 레포 연결(같은 레포, 프로젝트 하나 더), Root Directory `frontend`
- [ ] 환경변수(Production): `BACKEND_URL=https://<② 주소>` · `SITE_URL=https://<① 주소>` — 둘 다 **빌드할 때** 읽혀서 바꾸면 다시 배포
- [ ] 순서: ①을 먼저 한 번 배포해 주소를 받고 → ②의 `FRONTEND_URL` · `GOOGLE_REDIRECT_URI`와 구글 콘솔을 채우고 → ① · ② 다시 배포

## 5. 확인
- [ ] `https://<① 주소>/api/health` → ok(화면 → 백엔드 넘김)
- [ ] 랜딩 첫 화면 평가 수치 · `/report` 수치(→ `eval/summary`가 함수에 같이 묶였는지)
- [ ] `/demo` → 샘플 체험
- [ ] 본인 Gmail 로그인 → `/home`, 다른 Gmail → '지금은 샘플 체험만 열려 있어요'(또는 구글 화면에서 먼저 막힘)
- [ ] 퀴즈 만들기 한 번 — AI 호출 · 응답 시간(100초 안)
- [ ] 로그인 뒤 `/home` 응답 시간 — 몇 초씩 걸리면 함수 · DB 지역이 다른지 확인(NullPool이라 요청마다 새로 연결)
- [ ] 출처 머리말이 백엔드까지 가는지(로그아웃 · 체험 열기 출처 확인) — Claude에게 확인 요청
- [ ] 응답 머리말: 화면 `X-Frame-Options: DENY` · CSP 등, 백엔드 `nosniff`(F-016)
- [ ] 운영인데 허용 목록을 빼면 함수가 뜨지 않는지(미리보기 배포에서 `ALLOWED_LOGIN_EMAILS`만 비워 로그 확인 — F-015 · F-016)

## 알아 둘 것
- 백엔드(②) 주소는 공개다(화면이 넘기려면 공개여야 함). 주소가 숨겨졌다는 데 기대지 않는다 — 인증은 매 요청 쿠키로, 횟수 제한은 Vercel Firewall로(D-032).

## 배포 뒤 남은 결정
- 주소(Q-015) — 도메인을 붙이면 `SITE_URL` · `FRONTEND_URL` · 구글 리디렉션 URI를 같이 바꾼다
- 운영에서 Secure 쿠키를 코드로 강제할지(지금은 설정값 + 시작 경고)

최종 수정: 2026-11-19 · 관련: D-032, D-031, D-010, F-015, F-016, Q-015
