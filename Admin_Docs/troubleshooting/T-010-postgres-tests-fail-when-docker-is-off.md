# T-010 Docker가 꺼져 있으면 PostgreSQL 테스트가 대부분 오류(연결 시간 초과)

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 해결했어요(2026-11-13). 코드 문제가 아니라 환경 문제예요.
무슨 문제였나: PostgreSQL로 테스트를 돌렸더니 204개 통과 · 254개 오류로 22분이 걸렸어요. 코드가 크게 깨진 것처럼 보였어요.
어떻게 해결했나: DB가 들어 있는 Docker Desktop이 꺼져 있었어요. Docker를 켜고 DB 컨테이너를 올린 뒤 다시 돌리니 458개가 50초 만에 모두 통과했어요.

## 개발자 상세
- 증상: `TEST_DATABASE_URL`(PostgreSQL 테스트 DB)로 `pytest` → `ERROR ... sqlalchemy.exc....`가 수백 개, 요약 줄이 잘려 원인이 안 보임. 파일 하나만 돌리면 `psycopg.errors.ConnectionTimeout: connection timeout expired`. `docker ps`는 `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`.
- 원인: Docker Desktop이 꺼져 DB(127.0.0.1:5432)가 없음. 테스트마다 연결 시간 초과를 기다려서 오래 걸림.
- 해결: Docker Desktop 실행 → 엔진이 뜰 때까지 기다림(`docker info`) → `docker compose up -d` → `pg_isready`로 준비 확인 → 테스트 다시 실행. 컨테이너가 다시 만들어져도(Recreated) 데이터는 볼륨에 남아 개발 DB 버전(0007)이 그대로였다.
- 재발 방지: PostgreSQL 테스트 전에 `docker exec didim-db-1 pg_isready` 한 번. 오류가 수백 개 한꺼번에 나면 코드보다 DB 연결부터 의심한다(파일 하나만 `-x`로 돌려 첫 오류를 본다).

최종 수정: 2026-11-13 · 관련: T-002, D-008
