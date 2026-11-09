-- 테스트 전용 DB. 테스트는 이 DB의 테이블을 모두 지웠다 다시 만든다(backend/tests/conftest.py).
-- 개발 DB(POSTGRES_DB, 기본 didim)와 분리하려고 처음 컨테이너를 만들 때 한 번 생성한다.
CREATE DATABASE didim_test;
