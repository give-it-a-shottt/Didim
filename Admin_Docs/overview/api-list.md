# API 목록

## 한눈에 보기 (코드 몰라도 OK)
상태: [주의] 서버 확인 · 로그인(F-001) · 기록 가져오기(F-002) · 검색(F-003) · 퀴즈 · 복습(F-004)까지 있어요. 기능마다 설계 의도(feature.md)를 받은 뒤 여기에 한 줄씩 추가해요.
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
| GET | /api/notes | 내 노트 목록(기록 · 복습 홈). 응답 200: `{ total, notes: [{ id, title, kind, created_at, chunk_count, quiz_count }] }` — 최근 올린 것부터 최대 200개(`total`은 전체 개수), 원문은 넣지 않음. 오류: 401 비로그인 | F-004 | 테스트 통과 · 직접 실행(사용자 확인, 2026-11-11) |
| GET | /api/notes/{note_id} | 노트 상세. 응답 200: `{ id, title, kind, source, created_at, content, chunks: [{ id, position, heading_path, start_offset, end_offset }] }` — 위치는 원문의 파이썬 글자(코드 포인트) 단위. 오류: 401 비로그인, 404 없거나 다른 사용자의 노트 · 번호가 1~2,147,483,647 밖, 422 `note_id`가 숫자 아님 | F-003 | 테스트 통과 · 프록시 거쳐 직접 실행(2026-11-10) |
| GET | /api/search?q=…&limit=5 | 내 기록 조각 검색(키워드, D-016). `q` 1~200자, `limit` 1~5(기본 5). 응답 200: `{ query, terms, method, results: [{ chunk_id, note_id, note_title, heading_path, start_offset, end_offset, excerpt, matched_terms, score }] }` — `excerpt`는 마크다운 기호를 뺀 160자 안팎 글자, 점수 높은 순, 맞는 게 없으면 `results: []`. 검색마다 `search_logs`에 기록. 오류: 400 공백뿐, 401 비로그인, 422 길이 · `limit` 범위 밖, 503 이 DB에서 검색 불가(SQLite) · 검색이 3초 시간 상한을 넘음(`detail`에 이유, 화면이 그대로 보여 줌, 로그 안 남김) | F-003 | 테스트 통과(PostgreSQL) · 프록시 거쳐 직접 실행(2026-11-10) |
| POST | /api/notes/{note_id}/quizzes | 문제 만들기(AI 1번, 요청 한 번에 처리). 긴 조각(공백 뺀 80자 이상) 최대 10개를 보내 조각마다 객관식 · OX 1개, 근거 인용이 조각 안에 글자 그대로 없으면 버림. 응답 201: `{ note_id, created, dropped, drop_reasons, remaining_today }`. 오류: 401, 404 내 노트 아님, 409 이미 문제 있음 · 이 노트를 다른 요청이 만드는 중 · 같은 사용자가 다른 노트를 만드는 중(사용자당 동시에 1개), 422 긴 조각 없음, 429 오늘 AI 사용량(30회) 다 씀, 502 AI 답 형식 오류(재시도 후), 503 AI 연결 안 됨 · AI 서버 한도, 500 서버 AI 설정 오류 · 만든 문제 저장 실패 — 화면은 `detail`을 그대로 보여 줌 | F-004 | 테스트 통과 · 직접 실행 mock(사용자 확인, 2026-11-11) |
| GET | /api/notes/{note_id}/quizzes | 그 노트의 문제([이 노트 풀기]). 응답 200: `{ quizzes: [{ id, note_id, note_title, kind, question, choices, next_review_on, in_wrong_notes }] }` — 정답 · 해설 · 인용은 넣지 않음. 오류: 401, 404 | F-004 | 테스트 통과(2026-11-11) |
| GET | /api/reviews/today | 오늘 복습(한국 날짜 기준 복습일이 된 문제, 오래 밀린 것부터 최대 100개). 응답 200: `{ total, quizzes: [위와 같은 모양] }`. 오류: 401 | F-004 | 테스트 통과(2026-11-11) |
| POST | /api/quizzes/{quiz_id}/answer | 답 제출. 요청 `{ chosen_index }`. 응답 200: `{ correct, answer_index, explanation, note_id, note_title, chunk_id, quote, quote_start, quote_end, next_review_on, in_wrong_notes }`. 오류: 401, 404 내 문제 아님, 422 보기 범위 밖 | F-004 | 테스트 통과 · 직접 실행 mock(사용자 확인, 2026-11-11) |
| GET | /api/wrong-answers | 오답노트(최근에 틀린 것부터 최대 100개). 응답 200: `{ total, quizzes: [위와 같은 모양] }`. 오류: 401 | F-004 | 테스트 통과(2026-11-11) |

규칙
- 모든 서버 경로는 `/api`로 시작한다. 브라우저는 Next.js 주소의 `/api/*`로 부르고, Next.js가 FastAPI로 넘긴다(D-010, Q-012).
- 모든 회원 API는 로그인 사용자 기준으로만 데이터를 돌려준다(D-004).
- AI를 부르는 API는 사용량 한도를 먼저 확인하고, 한도에 걸리면 부분 결과를 보존한다.

최종 수정: 2026-11-11 · 관련: F-000, F-001, F-002, F-003, F-004, D-004, D-010, D-016
