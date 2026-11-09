# T-002 PostgreSQL 테스트가 연결 단계에서 끝없이 멈춤 (Windows · localhost · IPv6)

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 해결했어요(2026-11-09).
무슨 문제였나: DB 포트를 "내 컴퓨터에서만"(127.0.0.1) 열도록 바꾼 뒤, PostgreSQL 테스트가 아무 오류 없이 멈춰 버렸어요. 주소를 `localhost`로 썼는데, Windows는 `localhost`를 IPv6(`::1`)로 먼저 시도하고, 그 연결이 거절된 걸 DB 드라이버가 알아채지 못한 채 계속 기다렸어요.
어떻게 해결했나: DB 주소를 `127.0.0.1`로 쓰고, 연결 대기 시간에 5초 제한을 넣었어요. 이제 같은 상황이 와도 끝없이 멈추지 않아요.

## 개발자 상세
- 증상: `TEST_DATABASE_URL=…@localhost:5432/didim_test uv run pytest`가 출력 없이 멈춤. `pg_stat_activity`에 테스트 연결이 하나도 없음. `pytest -o faulthandler_timeout=15`로 본 스택: `conftest.py db_session → drop_all → … → psycopg/connection.py connect → psycopg/waiting.py wait_conn → selectors.select`에서 대기.
- 원인:
  - docker-compose 포트를 `"5432:5432"` → `"127.0.0.1:5432:5432"`로 바꿔(F-001 2차 R2 제안) IPv6 쪽(`::1:5432`)이 더 이상 열려 있지 않음.
  - `localhost`는 `::1`, `127.0.0.1` 순으로 풀림. 파이썬 소켓으로는 `::1` 연결이 바로 거절(10061)되지만, psycopg의 비동기 연결 대기(Windows select)에서는 거절을 감지하지 못해 시간 제한 없이 기다림.
  - 이전에는 IPv6도 열려 있어서 드러나지 않았음.
- 해결:
  - DB 주소 호스트를 `127.0.0.1`로(`backend/.env.example`, START_HERE, 오류 메시지 예시).
  - `create_db_engine`에서 PostgreSQL이면 `connect_timeout=DB_CONNECT_TIMEOUT_SECONDS(5)`. `localhost`로 써도 5초 뒤 다음 주소(127.0.0.1)로 넘어가 통과(느리지만 멈추지 않음)함을 확인.
- 재발 방지:
  - 로컬 DB 주소는 `127.0.0.1`로 쓴다.
  - 외부 연결(DB · API)에는 항상 시간 제한을 둔다(EXAONE 호출도 같은 원칙).
  - 테스트가 출력 없이 멈추면 `-o faulthandler_timeout=15`로 어디서 기다리는지 먼저 본다.
- 관련: F-001 2차 지적 반영, docker-compose.yml

최종 수정: 2026-11-09 · 관련: F-001, D-008
