# D-033 Vercel 배포는 프로젝트 두 개 대신 Services 한 프로젝트로 한다

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 사용자가 추천안을 골랐어요(2026-11-19). D-032의 '구성'만 바꿔요 — Vercel 상한에 맞춘 값(AI 100초 · 노션 80초 · 가져오기 3MB), 서울 지역, 운영 보안은 D-032 그대로예요.
무엇을: 화면(Next.js)과 백엔드(FastAPI)를 Vercel 프로젝트 하나에 '서비스' 둘로 올려요. 주소는 하나(`didim.vercel.app` 같은)이고, Vercel이 `/api/*`는 백엔드로, 나머지는 화면으로 바로 나눠 보내요. 화면 서버가 백엔드를 부를 때는 Vercel이 넣어 주는 내부 주소(`BACKEND_URL`)를 써요.
왜 (사용자 선택): Vercel에서 프로젝트를 만들 때 이 방식이 나와서 비교했어요. 백엔드 주소가 따로 공개되지 않고, 화면이 백엔드로 '넘기는' 단계가 없어서 120초 상한 · 출처 머리말 전달 걱정이 줄어요. 대신 아직 Beta예요.

## 개발자 상세

### 후보
| | A. Services 한 프로젝트 (선택) | B. 프로젝트 두 개(D-032 처음 안) |
|---|---|---|
| 주소 | 하나 — Vercel이 경로로 나눔 | 화면 · 백엔드 따로, 화면이 `/api/*`를 백엔드 주소로 넘김 |
| 백엔드 공개 | 같은 주소의 `/api/*`로만 | 백엔드 `*.vercel.app` 주소도 공개 |
| 화면 → 백엔드 넘김 | 없음(브라우저 요청이 Vercel에서 바로 백엔드로) | 있음 — 바깥 서버로 넘긴 요청 120초 상한, 머리말 전달은 배포 뒤 확인 필요 |
| 화면 서버 → 백엔드 | binding(내부 주소, 공개 인터넷 안 거침, 실행 때 주입) | `BACKEND_URL` 직접(빌드 때 값) |
| 방화벽 · 배포 보호 · 환경변수 | 한 번에 | 프로젝트마다 |
| 걸리는 점 | Beta, 환경변수를 두 서비스가 같이 봄 — 화면의 빌드(npm 설치 스크립트 · next build)와 Next 서버에서도 DB 주소 · 세션 비밀키 · AI 키가 보여서, npm 의존성 하나가 오염되거나 Next 서버에 취약점이 생기면 비밀값 전체가 노출될 수 있음(브라우저 번들로는 안 나감) | 검증된 방식 |

### 결정
- 레포 맨 위 `vercel.json`(Services): 서비스 `backend`(root `backend/`, FastAPI, 진입 `index:app`) · `frontend`(root `frontend/`, Next.js, binding `backend` → `BACKEND_URL`). 경로 `/api/(.*)` → backend, `/(.*)` → frontend(마지막). 지역 `regions: ["icn1"]`(서울). 서비스는 받은 원래 경로(`/api/...`)를 그대로 보므로 FastAPI 라우터는 그대로.
- `backend/vercel.json` · `frontend/vercel.json`은 지운다 — 서비스 방식에선 실행 설정을 맨 위 서비스 안에 둔다. 함수 최대 실행 시간은 Fluid compute 기본값(Hobby 300초)에 맡기고 배포 뒤 대시보드에서 150초 이상인지 확인(서비스 안 `functions` 키 이름이 FastAPI 진입과 맞는지 확인 못 해서 넣지 않음).
- 화면 코드: `lib/backend.ts`는 `BACKEND_URL` 끝의 `/`를 지운다(binding 값의 모양을 모름). `next.config.ts`의 `/api/*` rewrites는 로컬용으로 남긴다(배포에선 맨 위 경로가 먼저 받아 쓰이지 않음).
- 환경변수: 프로젝트 하나에 넣는다. `BACKEND_URL`은 넣지 않는다(Vercel이 주입). `FRONTEND_URL` · `SITE_URL` · 구글 리디렉션 URI는 같은 한 주소.
- 환경변수 공유 위험은 받아들이고 줄인다(사용자 선택 2026-11-19, F-016 4차 리뷰 R2): frontend 설치는 `npm ci`(lockfile 그대로만 — 새 버전이 몰래 들어오는 것은 막지만 lockfile에 있는 패키지의 설치 스크립트는 그대로 돌고 그때도 환경변수가 보임. `--ignore-scripts`는 빌드가 깨질 수 있어 다음에 미리보기 배포로 시험할지 정함, F-016 5차 R2), 규칙 — 비밀값에 `NEXT_PUBLIC_` 붙이지 않기, `next.config`의 `env` 쓰지 않기, `process.env` 전체를 로그로 남기지 않기. Vercel Services가 서비스별 환경변수를 지원하면 그때 나눈다. 다른 방법 — 프로젝트 두 개로 되돌려 비밀값을 백엔드에만 — 은 고르지 않았다.
- 함수 최대 실행 시간은 Fluid compute 기본값(Hobby 300초)에 맡기고 배포 뒤 150초 이상인지 대시보드에서 확인한다(사용자 선택 2026-11-19, 4차 리뷰 R4). 다른 방법 — 서비스 안 `functions`에 직접 적기(키 이름이 틀리면 첫 배포 실패) — 은 고르지 않았다.
- CLI 배포용 `.vercelignore`는 레포 맨 위 하나(Root가 `./`라서) — `.env` · `.env.*`(예시 파일 제외), 하위 폴더 것은 지운다(4차 R2). `next.config.ts`의 `/api/*` rewrites는 배포(`VERCEL`)에서 끈다 — 맨 위 규칙에 안 걸린 요청이 빌드 때 기본값(localhost)으로 넘겨지다 실패하지 않게.
- D-032의 값(AI 100초 · 노션 80초 · 가져오기 3MB · 서울 · NullPool · 보안)은 그대로 둔다. 120초 상한이 Services에선 안 걸릴 가능성이 높지만 문서에 명시가 없어([추정]) 보수적으로 유지.

- 덧붙임(2026-11-19): 지역은 `sin1`(싱가포르)로 바뀜 — DB를 Neon(서울 없음, 싱가포르)으로 바꿔서([D-034](D-034-neon-via-vercel-singapore.md)).
- 덧붙임(2026-11-19, 배포 확인): 맨 위 `regions`는 Services에서 **먹지 않았다** — 함수가 미국에 있어서 대시보드 Settings → Functions에서 sin1로 골랐다([T-013](../troubleshooting/T-013-vercel-services-region-and-neon-setup.md)). `vercel.json`의 값은 의도 기록으로 남김. 진입 `index:app` · binding · `/api/*` 넘김은 배포에서 동작 확인.

### 확인한 근거 (2026-11-19, Vercel 문서 — Services · Services routing · Service bindings · Service configuration reference)
- Services는 모든 플랜에서 Beta. 서비스는 맨 위 rewrites가 가리킬 때만 공개, 받은 원래 경로를 그대로 봄(`/api/users` → `/api/users`).
- 서비스 방식에선 `functions` · `installCommand` · `buildCommand` · `devCommand` · `ignoreCommand` · `outputDirectory` · `framework`를 맨 위에 둘 수 없음(서비스 안으로).
- binding은 실행 때만(빌드 · middleware에선 안 됨), 공개 인터넷 · 방화벽 · 배포 보호를 거치지 않는 내부 호출, 인증은 하지 않음(우리는 쿠키로 사용자를 확인하므로 그대로).
- 확인 못 한 것(배포 때): `regions`를 맨 위에 둬도 되는지(안 먹으면 Settings → Functions에서 icn1), 서비스 요청의 시간 상한, 진입 `index:app` 인식.

### 이 결정을 바꿔야 하는 조건
- Services Beta가 막히거나 바뀌면 → B(프로젝트 두 개, D-032 처음 안 — 지운 `vercel.json` 두 개와 체크리스트 이전 판은 git 기록에).

최종 수정: 2026-11-19 · 관련: D-032, D-010, D-031, F-016
