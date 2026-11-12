# 트러블슈팅 목록

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과]
무엇을: 문제가 생기고 해결할 때마다 T-00X 파일을 하나 만들고, 여기에 한 줄을 추가해요.
왜: 같은 문제가 다시 나면 바로 찾고, 면접에서 "어려웠던 점"을 근거와 함께 말하려고요.

## 개발자 상세
| 번호 | 제목 | 상태 | 날짜 |
|---|---|---|---|
| [T-001](T-001-stale-dev-server.md) | 끈 줄 알았던 서버가 남아서 예전 빌드로 확인할 뻔함 | [통과] | 2026-11-09 |
| [T-002](T-002-postgres-connect-hang-localhost.md) | PostgreSQL 테스트가 연결 단계에서 끝없이 멈춤 (Windows · localhost · IPv6) | [통과] | 2026-11-09 |
| [T-003](T-003-windows-cp949-console-output.md) | 스크립트 출력이 Windows 기본 인코딩(cp949)에서 깨지거나 멈춤 | [통과] | 2026-11-10 |
| [T-004](T-004-proxy-413-and-stale-servers.md) | 큰 업로드의 413이 Next 프록시를 거치면 연결 끊김으로 보임 (+ 확인 서버 함정 2가지) | [통과] | 2026-11-10 |
| [T-005](T-005-next-proxy-30s-timeout.md) | 오래 걸리는 AI 요청이 Next 프록시의 30초 상한에서 끊김 | [통과] | 2026-11-11 |
| [T-006](T-006-exaone-free-api-limits-in-eval.md) | EXAONE 무료 API로 평가를 돌리면 500 · 429 · 하루 한도 · 180초 상한에 걸림 | [통과] | 2026-11-12 |
| [T-007](T-007-base-exception-stops-testclient.md) | BaseException을 흉내 낸 테스트가 TestClient의 이벤트 루프를 멈춤 | [통과] | 2026-11-11 |
| [T-008](T-008-postgres17-planner-search-index.md) | PostgreSQL 17에서 검색 쿼리 최적화가 의도대로 안 됨 (OFFSET 0 · 색인 선택) | [통과] | 2026-11-10 |

최종 수정: 2026-11-12
