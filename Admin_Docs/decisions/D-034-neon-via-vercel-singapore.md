# D-034 DB는 Supabase 대신 Vercel에서 만든 Neon(싱가포르)으로, Vercel 함수 지역도 싱가포르로

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] Neon · Vercel에서 만들기는 사용자가 골랐고, 나머지(싱가포르 · Production만 · 주소 변환)는 AI 제안을 사용자가 계획으로 승인했어요(2026-11-19). D-032의 'DB = Supabase(서울)'와 D-033의 '지역 icn1(서울)'을 바꿔요. 나머지(Services 한 프로젝트 · 시간 상한 · 보안)는 그대로예요.
무엇을: Vercel 마켓플레이스의 Neon 연동으로 DB를 만들어요. 그러면 Vercel이 `DATABASE_URL`(풀러 주소) · `DATABASE_URL_UNPOOLED`(직접 주소)를 프로젝트 환경변수로 넣어 줘요. Neon에는 서울이 없어서 DB는 싱가포르(`aws-ap-southeast-1`)로, Vercel 함수도 싱가포르(`sin1`)로 맞춰요.
왜 (사용자 말): Supabase 무료로는 프로젝트를 2개만 만들 수 있는데 이미 2개를 쓰고 있어서 → "네온으로 변경하시죠", "버셀에서 바로 네온을 쓸 수 있는 걸로 알고 있습니다".
[AI 메모] 기존 Supabase DB를 같이 쓰는 안은 AI가 권하지 않았어요(아래 후보 표).

## 개발자 상세

### 후보
| 후보 | 장점 | 단점 |
|---|---|---|
| 기존 Supabase DB 같이 쓰기 | 새로 만들 것 없음 | 테이블 · `alembic_version`이 섞이고, Data API를 끄면 기존 앱이 멈춤 · 켜 두면 디딤 테이블이 열림 |
| 안 쓰는 Supabase 프로젝트 멈추고 새로 | 계획 그대로 | 멈출 프로젝트가 있어야 함 |
| Vercel 연동 Neon (선택) | 무료 플랜 프로젝트 넉넉(100개), Data API 같은 자동 REST가 기본으로 없음, 환경변수 자동 주입 | 서울 지역 없음(싱가포르), 5분 쉬면 잠듦(첫 요청 조금 느림, 무료에선 못 끔), Vercel 경유 무료 플랜 여부는 설치 화면에서 확인 |

### 결정
- DB: Vercel 마켓플레이스 → Neon → Install, Region **Singapore(aws-ap-southeast-1)**, 연결할 환경은 **Production만**(Preview 체크 해제 — 미리보기 배포가 운영 DB를 쓰지 않게), 미리보기용 DB 브랜치는 만들지 않음.
- 지역: Vercel 함수 `regions: ["sin1"]`(레포 맨 위 `vercel.json`) — NullPool이라 요청마다 DB에 새로 연결해서 함수와 DB가 같은 곳이어야 함. 한국에서 화면까지는 조금 멀어지지만(왕복 수십 ms) DB 연결이 매번 서울↔싱가포르를 오가는 것보다 낫다.
- 주소 형식: Neon은 `postgresql://…?sslmode=require…`로 준다. 디딤은 psycopg 3를 써서 `create_db_engine`이 `postgresql://` · `postgres://`를 `postgresql+psycopg://`로 바꿔 쓴다(`app/db/session.py` `normalize_database_url`) — 앱 · 마이그레이션 · 시드가 모두 이 함수를 거친다.
- 연결: 앱은 `DATABASE_URL`(풀러, PgBouncer transaction 모드 — 프로토콜 수준 prepared statement 지원)로. DB 구조 만들기(`alembic upgrade head`) · 샘플 시드는 **직접 주소(`DATABASE_URL_UNPOOLED`)**로 내 컴퓨터에서 — Neon 문서가 마이그레이션은 직접 연결을 권함.
- `vercel env pull`로 값을 받지 않는다(D-033 — 운영 비밀값이 로컬 파일로, 로컬 /api 넘김이 꺼짐). 직접 주소는 Vercel Storage → Neon 화면(또는 거기서 여는 Neon 콘솔의 Connect)에서 한 번 보고 가린 입력으로 넣는다 — Sensitive 환경변수는 Settings 화면에서 다시 볼 수 없어서.
- 암호화: Neon이 주는 주소 그대로 `sslmode=require` + `channel_binding=require`(접속은 암호화하고, 로그인 때 중간자가 끼면 실패). D-032의 'Enforce SSL · verify-full(인증서 검증)'은 Supabase용이라 이 결정으로 대체 — 인증서 검증까지 할지는 [Q-032](../OPEN_QUESTIONS.md).

### 확인한 근거 (2026-11-19, Neon 문서 — regions · connection pooling · plans · Vercel managed integration)
- 지역: AWS us-east-1/2 · us-west-2 · eu-central-1 · eu-west-2 · ap-southeast-1(싱가포르) · ap-southeast-2 · sa-east-1 — 서울 · 도쿄 없음.
- 풀러: `-pooler` 호스트, PgBouncer `pool_mode=transaction`, `max_prepared_statements=1000`, SQL 수준 PREPARE는 안 됨, 마이그레이션은 직접 연결.
- 무료: 프로젝트 100개, 프로젝트당 1GB, 5분 쉬면 잠듦(끌 수 없음).
- Vercel 연동: `DATABASE_URL`(풀러) · `DATABASE_URL_UNPOOLED`(직접) · `PGHOST` 등 주입, Sensitive 기본, 환경은 Production · Preview 기본 체크.
- 확인 못 한 것(만들 때 · 배포 때): Vercel 경유 Free 플랜, 설치 화면의 지역 목록, `pg_trgm` · `btree_gin`(마이그레이션 0003이 만듦), 잠들었다 깨는 시간.

### 이 결정을 바꿔야 하는 조건
- 한국에서 응답이 눈에 띄게 느리면 → 서울 지역이 있는 DB(Supabase 등)로 옮기고 `regions`를 icn1로.
- Neon 무료 한도(1GB · 컴퓨트 시간)에 걸리면 → 플랜 또는 다른 DB.

최종 수정: 2026-11-19 · 관련: D-032, D-033, F-016
