# API 목록

## 한눈에 보기 (코드 몰라도 OK)
상태: [주의] 서버 확인 · 로그인(F-001) · 기록 가져오기(F-002)까지 있어요. 기능마다 설계 의도(feature.md)를 받은 뒤 여기에 한 줄씩 추가해요.
무엇을: 화면이 서버에 보내는 요청 목록이에요.
왜: 화면과 서버가 같은 약속을 보도록 한곳에 모아 둬요.

## 개발자 상세

| 메서드 | 경로 | 하는 일 | 기능 | 상태 |
|---|---|---|---|---|
| GET | /api/health | 서버가 살아 있는지 확인. 로그인 없이 `{"status": "ok"}` | 세팅 | 테스트 통과(2026-11-08) |
| GET | /api/auth/google/login | 구글 로그인 화면으로 이동(위조 방지 `state` 함께 저장) | F-001 | 테스트 통과(2026-11-09) |
| GET | /api/auth/google/callback | 구글 로그인 콜백 처리, 계정 확인·생성 후 `httpOnly` 세션 쿠키 발급 → 성공 `/home`, 실패 `/login?error=...` | F-001 | 테스트 통과(2026-11-09) |
| GET | /api/auth/me | 로그인한 내 정보(`{ id, email, name }`) 반환(200), 비로그인 `401` | F-001 | 테스트 통과(2026-11-09) |
| POST | /api/auth/logout | 세션 쿠키 삭제(`204`) | F-001 | 테스트 통과(2026-11-09) |
| POST | /api/notes/import | 마크다운 파일 가져오기. 요청: multipart `files`(여러 개, 최대 20 · 파일당 1MB · 합계 20MB) + `kind`(`study` 기본 · `project`). 응답 200: `{ summary: { notes, chunks, duplicates, failed }, imported: [{ filename, note_id, title, chunk_count }], duplicates: [{ filename, existing_note_id, existing_title }], failed: [{ filename, reason }] }` — 일부 실패해도 200(실패 이유: 확장자 · 1MB 초과 · UTF-8 아님 · 빈 파일 · 제목만 있음 · 조각 2,000개 초과 · 저장 실패). 오류: 400 파일 없음 · 개수 초과 · 주소에 제어 문자, 401 비로그인 · 쿠키 위조 · 만료(본문을 받기 전), 413 요청 21MB · 파일 합계 20MB 초과(본문을 받기 전 · 받는 중), 422 `kind` 값 틀림 | F-002 | 테스트 통과 · 프록시 거쳐 직접 실행(2026-11-10) |

규칙
- 모든 서버 경로는 `/api`로 시작한다. 브라우저는 Next.js 주소의 `/api/*`로 부르고, Next.js가 FastAPI로 넘긴다(D-010, Q-012).
- 모든 회원 API는 로그인 사용자 기준으로만 데이터를 돌려준다(D-004).
- AI를 부르는 API는 사용량 한도를 먼저 확인하고, 한도에 걸리면 부분 결과를 보존한다.

최종 수정: 2026-11-10 · 관련: F-000, F-001, F-002, D-004, D-010
