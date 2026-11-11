# 트랜잭션 격리 수준

## 네 단계
SQL 표준은 격리 수준을 네 단계로 정한다. 약한 것부터 READ UNCOMMITTED, READ COMMITTED, REPEATABLE READ, SERIALIZABLE 순이다. 단계가 높을수록 다른 트랜잭션의 영향을 덜 받지만 동시에 처리할 수 있는 양은 줄어든다.

## Dirty Read
Dirty Read는 다른 트랜잭션이 아직 커밋하지 않은 값을 읽는 현상이다. 그 트랜잭션이 롤백하면 존재한 적 없는 값을 읽은 셈이 된다. READ UNCOMMITTED에서만 생길 수 있고, PostgreSQL은 READ UNCOMMITTED를 요청해도 READ COMMITTED처럼 동작해서 Dirty Read가 일어나지 않는다.

## PostgreSQL의 기본값
PostgreSQL의 기본 격리 수준은 READ COMMITTED다. 이 수준에서는 문장(쿼리) 하나가 시작될 때 커밋된 데이터만 보인다. 그래서 같은 트랜잭션 안에서 같은 SELECT를 두 번 해도, 그 사이에 다른 트랜잭션이 커밋했다면 결과가 달라질 수 있다(Non-repeatable Read).

## REPEATABLE READ
REPEATABLE READ에서는 트랜잭션이 시작된 뒤 첫 쿼리 시점의 스냅샷을 끝까지 본다. 같은 행을 다시 읽어도 값이 바뀌지 않는다. PostgreSQL에서는 이 수준에서 다른 트랜잭션과 같은 행을 동시에 고치려 하면 직렬화 오류가 나고, 애플리케이션이 재시도해야 한다.

## 행 잠금으로 해결하기
격리 수준을 올리는 대신 필요한 행만 잠그는 방법도 있다. `SELECT ... FOR UPDATE`로 읽은 행은 트랜잭션이 끝날 때까지 다른 트랜잭션이 고칠 수 없다. 재고 차감처럼 읽고 나서 바로 고치는 흐름에서 두 요청이 같은 값을 읽고 덮어쓰는 문제를 막는다.
