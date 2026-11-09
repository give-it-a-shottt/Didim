import os

# 테스트는 빠르게 돌리려고 기본으로 SQLite(메모리)를 쓴다. 운영 · 개발 DB는 PostgreSQL이다(D-008).
# 앱은 DATABASE_URL이 없으면 시작하지 않으므로, 테스트에서만 여기서 명시적으로 넣는다.
# PostgreSQL로 같은 테스트를 돌리려면 TEST_DATABASE_URL을 주고 실행한다(예: docker-compose의 DB).
os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL", "sqlite://"))
