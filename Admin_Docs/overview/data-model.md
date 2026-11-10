# 데이터 모델

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 전체 테이블 계획과 1주차 생성 범위(`users`, `notes`, `chunks`)를 사용자가 확인했어요(2026-11-09).
무엇을: 핵심은 "AI가 만든 모든 것에 근거가 따라붙는" 구조예요. 자소서는 문장 목록이고, 문장마다 근거 표를 따로 둬요.
왜: 근거를 문장 단위로 저장해야 근거 없는 문장을 세고, 노트가 지워졌을 때 끊긴 근거를 표시할 수 있어요.

## 개발자 상세 (계획 · 주차별 생성)

| 테이블 | 담는 것 | 메모 |
|---|---|---|
| users | 계정 | `id`, `google_sub`(UNIQUE), `email`, `name`, 하루 사용량 상한(`daily_limit`), `created_at` (1주차 생성) |
| notes | 가져온 기록(원문) | `user_id`(FK `ON DELETE CASCADE`), source(markdown · notion), kind(학습 노트 · 프로젝트 경험), 원문 해시(중복 확인), 수정일 (1주차 생성) |
| chunks | 기록 조각 | `user_id`(FK `ON DELETE CASCADE`), `note_id`(FK `ON DELETE CASCADE`), 순서(`position`), 제목 경로(`heading_path`, 예: `# React > ## useEffect`, 제목 한 단계는 200자까지 · 넘으면 '…'), 원문 위치(`start_offset` · `end_offset`, 조각 내용 == 노트 원문[시작:끝], 파이썬 문자 단위) (1주차 생성, 위치 컬럼은 F-002 · 버전 0002). 키워드 검색 색인 `ix_chunks_user_content_trgm` — GIN (`user_id`, `content` gin_trgm_ops), pg_trgm + btree_gin 확장(버전 0003, F-003). 사용자 조건과 본문 비슷함을 한 색인으로 같이 거른다(따로 두면 내 조각을 전부 읽는 계획이 나옴 — 1차 리뷰 뒤 실측 · 사용자 확인). embedding(vector)은 평가로 비교한 뒤 붙임(D-016) — 지금 모델에는 없음 |
| search_logs | 검색 로그 | `user_id`(FK `ON DELETE CASCADE`), `query`(검색어), `method`(검색 방식, 지금 `keyword`), `results`(JSON — 순위 순서 `[{chunk_id, score}]`), `created_at`. 평가 채점용(D-005) (2주차 생성, F-003 · 버전 0003) |
| quizzes | 문제 | note_id · chunk_id 근거, 유형(객관식 · OX, D-006), 정답 · 해설 |
| review_logs | 풀이 기록 | 맞음 · 틀림, 다음 복습일(당일 → 1 → 3 → 7 → 14), 연속 정답 수(오답노트 2번) |
| cards | 경험 카드 | 상황 · 과제 · 행동 · 결과(사용자 답만), 상태(후보 · 완성) |
| card_evidence | 카드 근거 | card_id ↔ note · chunk, 원문 수정됨 · 원문 없음 |
| postings | 공고 | 붙여 넣은 본문 · URL, 기업 · 직무, 마감일, 상태(준비 · 작성 중 · 제출) |
| requirements | 요구 역량 | posting_id, 매칭된 card_id 목록 · 점수 |
| drafts | 자소서 | posting_id, 문항, 상태, 내가 고친 비율 |
| sentences | 문장 | draft_id, 순서, 본문, AI 작성 여부 · 사용자 수정 여부 |
| sentence_evidence | 문장 근거 | sentence_id ↔ card · note, 없으면 경고 |
| interview_questions | 면접 질문 | card_id 근거, 내 답 메모 |
| eval_runs | 평가 실행 기록 | 데이터 세트 버전, 지표 3개, 날짜 |

- 모든 사용자 데이터 테이블에 `user_id`(외래키 `ON DELETE CASCADE`)를 두고, 조회할 때 항상 `user_id` 조건을 건다.
- 전체 테이블 계획은 위 표대로 유지하되, 실제 DB 마이그레이션은 주차별로 쓰는 테이블부터 만든다(1주차: `users`, `notes`, `chunks` / 2주차: `search_logs`, 조각 검색 색인).
- 검색 평가 세트와 결과는 DB가 아니라 로컬 파일(`backend/eval/`, 레포 밖)에 둔다(F-003, 사용자 확인). `eval_runs`는 F-010 평가 리포트 때 정한다.
- 샘플 체험 데이터는 읽기 전용 별도 표시(같은 테이블에 플래그 vs 별도 스키마 — Q-004).

최종 수정: 2026-11-10 · 관련: D-003, D-004, D-005, D-016, F-001, F-003
