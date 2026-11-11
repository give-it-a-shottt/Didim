# Python asyncio

## 이벤트 루프
asyncio는 스레드 하나에서 이벤트 루프가 여러 코루틴을 번갈아 실행하는 방식이다. 코루틴이 `await`에서 기다리는 동안 이벤트 루프는 다른 코루틴을 실행한다. 그래서 동시에 많은 네트워크 요청을 기다리는 작업에 잘 맞는다.

## async def와 await
`async def`로 정의한 함수를 호출하면 바로 실행되지 않고 코루틴 객체만 만들어진다. 실제로 실행하려면 `await`로 기다리거나 `asyncio.run()`으로 이벤트 루프에서 돌려야 한다. `await`를 빼먹으면 "coroutine was never awaited" 경고가 나온다.

## 블로킹 호출의 위험
코루틴 안에서 `time.sleep()`이나 동기 DB 드라이버처럼 블로킹하는 함수를 부르면, 그동안 이벤트 루프 전체가 멈춰서 다른 코루틴도 실행되지 않는다. 기다릴 때는 `asyncio.sleep()`을 쓰고, 어쩔 수 없는 블로킹 함수는 `asyncio.to_thread()`로 별도 스레드에서 실행한다.

## gather로 동시에 기다리기
`asyncio.gather()`에 코루틴 여러 개를 넘기면 동시에 실행하고 모두 끝날 때까지 기다린다. 1초 걸리는 요청 세 개를 하나씩 await하면 3초가 걸리지만 gather로 함께 기다리면 약 1초에 끝난다. 결과는 넘긴 순서대로 리스트로 돌아온다.

## 시간 제한
오래 걸릴 수 있는 작업에는 `asyncio.wait_for(코루틴, timeout=5)`처럼 시간 제한을 건다. 제한 시간이 지나면 작업을 취소하고 TimeoutError를 일으킨다. 파이썬 3.11부터는 `async with asyncio.timeout(5):` 형태로 블록 전체에 시간 제한을 걸 수도 있다.
