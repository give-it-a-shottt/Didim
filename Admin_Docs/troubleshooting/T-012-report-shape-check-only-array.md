# T-012 평가 리포트 응답의 회차 안쪽 모양이 틀리면 랜딩 · /report 화면 전체가 오류가 됐다

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 해결했어요(2026-11-19). 테스트가 찾아 줬어요.
무슨 문제였나: 화면은 백엔드가 준 평가 리포트를 '회차 목록이 배열인가'만 보고 믿었어요. 그래서 회차 안에 꼭 있어야 할 칸(평가 목록 · 데이터 규모)이 빠진 응답이 오면, 화면을 그리다가 서버에서 오류가 나 랜딩과 리포트 페이지가 통째로 깨졌어요. 수치 칸만 숨겨야 하는 상황이었어요(F-011 완료 기준 2).
어떻게 해결했나: 화면이 읽는 칸(회차 · 평가 · 수치)의 모양까지 검사하고, 하나라도 틀리면 응답 전체를 '못 읽음'으로 처리해요. 그러면 랜딩은 수치 칸만 숨고 리포트는 '불러오지 못했어요'를 보여요.

## 개발자 상세
- 증상: 고장 난 가짜 백엔드가 `/api/report`에 `200 {"runs":[{"run_id":"20261119-000000"}]}`를 주자, 화면 서버 로그에
  ```
  ⨯ TypeError: Cannot read properties of undefined (reading 'find')        ← 랜딩 heroMetrics: run.evals.find
  ⨯ TypeError: Cannot read properties of undefined (reading 'quiz_notes')  ← /report dataSizeItems(run.data)
  ```
  e2e `report-unavailable.spec.ts`의 '회차 안쪽 모양이 틀림' 2개 실패(첫 화면 링크 · 알림을 못 찾음).
- 원인: `frontend/src/lib/report.ts`의 `isReportRuns`가 `Array.isArray(value.runs)`만 확인하는 타입 가드였다. 타입 가드는 TypeScript에 '이 모양이다'라고 약속만 할 뿐이라, 안쪽이 틀린 값도 `ReportRun[]`로 통과해 렌더 중에 터졌다. `getReportRuns`의 try/catch는 `response.json()`만 감싸서 렌더 오류는 못 막는다.
- 왜 지금까지 안 보였나: 백엔드(`backend/app/api/report.py`)가 요약 파일마다 pydantic `RunOut`으로 검사해 틀린 회차를 빼서, 정상 운영에서는 이런 응답이 오지 않는다. 백엔드 · 화면 버전이 어긋나거나(배포 순서) 프록시가 다른 본문을 줄 때만 생긴다.
- 해결: `isReportRuns` → `isReportRun` · `isReportEval` · `isReportMetric`로 백엔드 `RunOut` · `EvalOut` · `MetricOut` 칸을 그대로 검사(null 가능 칸은 null · undefined 허용, 수치 값은 null 또는 유한 숫자). 회차 하나라도 틀리면 전체를 null(D-030 덧붙임 — 틀린 회차만 건너뛰면 옛 회차가 '최근 회차'처럼 보여서, 사용자 선택). 실제 `read_report()` 응답 → true, `{runs:[]}` → true 확인.
- 테스트: 고장 백엔드(8101)에 응답 종류 스위치(`POST /__test/report-mode/<mode>` — fail · empty · not-json · bad-run · bad-metric)를 두고, 같은 빌드의 두 번째 `next start`(3101)로 랜딩 · /report를 연다. 파일 안 테스트는 차례로 돌리고 beforeEach로 fail로 되돌린다. 수치 값 검사를 끄면 bad-metric 2개만 실패하는 것 확인. Playwright 전체 123 통과.
- 재발 방지: 서버에서 받은 JSON을 화면이 믿고 쓰기 전에, 화면이 실제로 읽는 칸까지 검사한다(배열 · 객체인지만 보는 타입 가드는 렌더 중 오류를 못 막는다). 응답 타입을 바꾸면 검사 함수도 같이 고친다. '못 읽을 때' e2e에는 연결 실패 · 500뿐 아니라 '200인데 모양이 틀림'도 넣는다.

최종 수정: 2026-11-19 · 관련: F-011(6차 리뷰), F-010, D-030
