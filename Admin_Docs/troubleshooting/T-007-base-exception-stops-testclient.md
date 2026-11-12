# T-007 BaseException을 흉내 낸 테스트가 TestClient의 이벤트 루프를 멈춤

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 해결했어요(2026-11-11).
무슨 문제였나: "AI를 기다리다 요청이 취소되면 선점 · 사용량이 제대로 정리되나?"를 확인하려고, 취소 같은 특별한 예외(BaseException)를 일으키는 테스트를 만들었어요. 그런데 이 예외를 테스트용 서버(TestClient)를 거쳐 일으키면, 테스트 서버 자체가 멈춰서 그 뒤 테스트까지 망가졌어요.
어떻게 해결했나: 이 테스트만 테스트 서버를 거치지 않고 API 함수를 직접 불러요. AI를 부르는 자리만 예외를 던지는 가짜로 바꿔 끼워요.

## 개발자 상세
- 상황: 퀴즈 · 카드 API는 동기 엔드포인트이고, AI 호출만 `anyio.from_thread.run`으로 이벤트 루프에서 돌린다(F-004 · F-006). 취소(`CancelledError` 등)는 `Exception`이 아니라 `BaseException`이라 `except Exception`에 안 잡힌다 → 정리 경로를 `except BaseException`으로 두고 테스트로 확인하려 함.
- 증상: TestClient로 요청을 보내 그 안에서 `BaseException` 하위 예외를 던지면, 예외가 TestClient가 띄운 테스트 서버의 이벤트 루프까지 올라가 루프를 멈춤(테스트 docstring에 남긴 기록). [추정] 원인은 anyio 포털이 `Exception`이 아닌 예외를 요청 오류로 바꾸지 않고 그대로 올리는 것 — 라이브러리 소스로는 확인하지 않음.
- 해결: [backend/tests/test_quiz_generation.py](../../backend/tests/test_quiz_generation.py)의 `test_cancel_like_base_exception_also_cleans_up` — `_Cancelled(BaseException)`를 정의하고 `quizzes_api.anyio.from_thread.run`만 monkeypatch로 바꾼 뒤, 엔드포인트 함수 `generate_quizzes(...)`를 직접 부른다. 선점이 지워졌는지 · 사용량 로그가 `error` 1건인지 확인.
- 재발 방지: `BaseException`(취소 · 중단)을 흉내 내는 테스트는 TestClient를 거치지 않고 함수를 직접 부른다. 일반 오류(`Exception`)는 TestClient로 확인해도 된다.

최종 수정: 2026-11-12 · 관련: F-004, F-006
