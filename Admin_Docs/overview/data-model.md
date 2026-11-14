# 데이터 모델

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 전체 테이블 계획과 1주차 생성 범위(`users`, `notes`, `chunks`)를 사용자가 확인했어요(2026-11-09).
무엇을: 핵심은 "AI가 만든 모든 것에 근거가 따라붙는" 구조예요. 자소서는 문장 목록이고, 문장마다 근거 표를 따로 둬요.
왜: 근거를 문장 단위로 저장해야 근거 없는 문장을 세고, 노트가 지워졌을 때 끊긴 근거를 표시할 수 있어요.

## 개발자 상세 (계획 · 주차별 생성)

| 테이블 | 담는 것 | 메모 |
|---|---|---|
| users | 계정 | `id`, `google_sub`(UNIQUE), `email`, `name`, 하루 사용량 상한(`daily_limit`), `created_at` (1주차 생성) |
| notes | 가져온 기록(원문) | `user_id`(FK `ON DELETE CASCADE`), source(markdown · notion), kind(학습 노트 · 프로젝트 경험), 원문 해시(중복 확인), 수정일 (1주차 생성). `notion_page_id`(노션에서 가져온 페이지 번호, 마크다운은 NULL) + 유니크 색인 `uq_notes_user_notion_page`(`user_id`, `notion_page_id`) — 같은 페이지는 한 번만(F-005, 버전 0006). 제약이 아니라 색인인 이유: SQLite에서 제약을 더하면 notes를 다시 만들며 CASCADE로 조각이 지워짐 |
| chunks | 기록 조각 | `user_id`(FK `ON DELETE CASCADE`), `note_id`(FK `ON DELETE CASCADE`), 순서(`position`), 제목 경로(`heading_path`, 예: `# React > ## useEffect`, 제목 한 단계는 200자까지 · 넘으면 '…'), 원문 위치(`start_offset` · `end_offset`, 조각 내용 == 노트 원문[시작:끝], 파이썬 문자 단위) (1주차 생성, 위치 컬럼은 F-002 · 버전 0002). 키워드 검색 색인 `ix_chunks_user_content_trgm` — GIN (`user_id`, `content` gin_trgm_ops), pg_trgm + btree_gin 확장(버전 0003, F-003). 사용자 조건과 본문 비슷함을 한 색인으로 같이 거른다(따로 두면 내 조각을 전부 읽는 계획이 나옴 — 1차 리뷰 뒤 실측 · 사용자 확인). embedding(vector)은 평가로 비교한 뒤 붙임(D-016) — 지금 모델에는 없음 |
| search_logs | 검색 로그 | `user_id`(FK `ON DELETE CASCADE`), `query`(검색어), `method`(검색 방식, 지금 `keyword`), `results`(JSON — 순위 순서 `[{chunk_id, score}]`), `created_at`. 평가 채점용(D-005) (2주차 생성, F-003 · 버전 0003) |
| ai_usage_logs | AI 사용량 | `user_id`(FK `ON DELETE CASCADE`), `feature`, `calls`, `prompt_tokens`, `completion_tokens`, `outcome`, `created_at`, 색인 (`user_id`, `created_at`). 모든 AI 기능이 같이 쓰고 하루 상한(`users.daily_limit`)을 이 표의 호출 수 합계로 센다. `outcome`: ok · invalid_output · rate_limited · unavailable · config_error · request_error · error · save_failed (D-018, 3주차 · 버전 0004) |
| note_quiz_claims | 문제 만들기 선점 | `user_id` · `note_id`(FK `ON DELETE CASCADE`, note_id 유니크), `claimed_at`. 동시 클릭에도 AI를 한 번만 부르게 함, 5분 넘으면 새 요청이 가져감. 사용자당 진행 중인 선점(5분 안 됐고 그 노트에 아직 문제가 없음)은 하나만 — 사용자 줄을 잠그고 확인(F-004 1차 리뷰, 버전 0004) |
| quizzes | 문제 | `user_id` · `note_id` · `chunk_id`(FK `ON DELETE CASCADE`, **chunk_id 유니크** — 조각마다 1개), `kind`(mcq · ox, D-006), `question`, `choices`(JSON — OX는 ["O", "X"]), `answer_index`, `explanation`, 근거 인용 `quote` · `quote_start` · `quote_end`(노트 원문 글자 위치, `quote == notes.content[start:end]`, D-003), `created_at`(F-004, 버전 0004) |
| quiz_reviews | 복습 상태 | `user_id` · `quiz_id`(FK `ON DELETE CASCADE`, quiz_id 유니크 — 문제마다 하나), `next_review_on`(한국 날짜), `interval_step`(0~4 → 당일 · 1 · 3 · 7 · 14일), `correct_streak`, `in_wrong_notes`, `updated_at`, 색인 (`user_id`, `next_review_on`). 오답노트는 복습일이 다른 날 두 번 연속 맞히면 빠짐(F-004, 버전 0004) |
| quiz_attempts | 푼 기록 | `user_id` · `quiz_id`(FK `ON DELETE CASCADE`), `chosen_index`, `is_correct`, `created_at`. 미리 풀어 복습 상태가 그대로여도 남김(F-004, 버전 0004) |
| quiz_generation_logs | 문제 만들기 평가 로그 | `user_id`(FK `ON DELETE CASCADE`), `note_id`(외래키 아님 — 노트가 지워져도 평가 로그는 남김), `chunks_sent`, `kept`, `dropped`, `drop_reasons`(JSON — 이유별 버린 수), `outcome`, `created_at`. 버려진 문제 비율 채점용(D-005, F-004, 버전 0004) |
| cards | 경험 카드 | `user_id`(FK `ON DELETE CASCADE`), `note_id`(후보를 찾은 노트, `SET NULL` — 노트가 지워져도 카드는 남음), `title`(AI 제안 → 저장 때 사용자 확인, 근거로 안 씀), `status`(candidate · saved), `created_at` · `updated_at` (F-006, 버전 0005) |
| card_fields | 카드 칸 + 근거 | `user_id` · `card_id`(FK `ON DELETE CASCADE`), `slot`(situation · task · action · result, 카드+칸 유니크), 원문 인용 `quote` · `quote_start` · `quote_end` · `chunk_id`(`SET NULL`), AI 빈칸 질문 `question`, 사용자 답 `answer`, `updated_at`. 빈칸 = 인용도 답도 없음, 근거 수 = 인용 있는 칸 수. 처음 계획한 `card_evidence`를 합침(근거가 칸 단위, D-003). 네 칸 모두 인용을 빼서 근거가 0개인 카드도 허용(Q-022 → feature.md, 사용자 확인 2026-11-11) (F-006, 버전 0005) |
| note_card_claims | 카드 후보 찾기 선점 | `note_quiz_claims` 구조(note_id 유니크) + `finished_at`(비어 있음 = 찾는 중, 있음 = 이미 찾은 노트 → 409, 후보를 모두 버려도 남음). AI 실패 · 후보 0개 · 저장 실패면 지워서 다시 누를 수 있음 (F-006, 버전 0005, 사용자 확인 2026-11-11) |
| card_generation_logs | 카드 후보 찾기 평가 로그 | `user_id`(FK `ON DELETE CASCADE`), `note_id`(외래키 아님), `chunks_sent`, `candidates`, `quoted_fields`, `emptied_fields`(인용 검사로 빈칸이 된 칸 수), `drop_reasons`(JSON — 이유별 수), `outcome`, `created_at`. 평가 세트 채점은 `scripts/card_eval.py`(D-005) (F-006, 버전 0005) |
| notion_connections | 노션 연결 | `user_id`(FK `ON DELETE CASCADE`, UNIQUE — 사용자당 1줄), `workspace_id`, `workspace_name`, `bot_id`, `access_token_enc` · `refresh_token_enc`(Fernet 암호화, 키는 환경변수 `NOTION_TOKEN_KEY`), `expires_at`(노션이 주면), `status`(connected · broken — 갱신 실패면 broken + 토큰 지움), `importing_since`(가져오기 시작 시각 — 사용자당 하나, 5분 지나면 새 요청이 가져감, 1차 리뷰 D), `created_at`, `updated_at` (F-005, 버전 0006) |
| applications | 지원(공고) | `user_id`(FK `ON DELETE CASCADE`), `company` · `role`(100자), `deadline`(한국 날짜, NULL 가능), `url`(링크만 — 서버가 읽지 않음, D-002), `posting_text`(붙여 넣은 본문, 만든 뒤 못 고침 — 인용 위치 기준), `status`(ready · writing · submitted), `extracted_at`(① 역량 뽑기 끝남 — 있으면 다시 안 뽑음), `matched_at`(② 매칭을 마지막으로 끝낸 시각), `created_at` · `updated_at`, 색인 (`user_id`, `deadline`). 처음 계획의 `postings` (F-007, 버전 0007) |
| application_questions | 자소서 문항 | `user_id` · `application_id`(FK `ON DELETE CASCADE`), `position`(공고+순서 유니크), `text`, `char_limit`(NULL = 제한 없음). F-008이 씀 (F-007, 버전 0007) |
| posting_requirements | 요구 역량 | `user_id` · `application_id`(FK `ON DELETE CASCADE`), `position`(공고+순서 유니크, 공고에 나온 순서), `name`(AI 이름표, 50자), `kind`(required · preferred), 공고 인용 `quote` · `quote_start` · `quote_end`(`quote == posting_text[start:end]`, 서버가 확인한 것만). 처음 계획의 `requirements` (F-007, 버전 0007) |
| requirement_matches | 역량 ↔ 내 카드 | `user_id` · `requirement_id`(FK `ON DELETE CASCADE`), `card_id`(FK `ON DELETE CASCADE` — 카드를 지우면 매칭도 지워져 '근거 없음'으로 돌아감, 역량+카드 유니크), `slot`, 카드 칸 인용 `quote` + `quote_source`(quote · answer) + 그 글 안의 위치, `reason`(AI가 쓴 맞는 이유 — 카드 내용 아님, D-003), `created_at`. [매칭 다시]면 그 공고의 매칭을 모두 지우고 새로 넣음 (F-007, 버전 0007) |
| application_claims | 공고 분석 선점 | `note_quiz_claims` 구조인데 대상이 공고(`application_id` 유니크, FK `ON DELETE CASCADE`), `claimed_at`. ① · ②가 같은 줄을 써서 같은 공고에서 동시에 돌지 않고, 사용자당 AI 작업 1개(D-020)에 같이 셈. 성공 · 실패 모두 끝나면 지움, 5분 지나면 새 요청이 가져감 (F-007, 버전 0007) |
| posting_analysis_logs | 공고 분석 평가 로그 | `user_id`(FK `ON DELETE CASCADE`), `application_id`(외래키 아님 — 공고를 지워도 남김), `step`(extract · match), `items_sent`(① 보낸 글자 수 / ② 보낸 역량 수), `cards_sent`, `kept`, `drop_reasons`(JSON), `outcome`(ok · none_found · no_candidates · AI 오류 종류), `created_at`. 평가 세트 채점은 `scripts/posting_eval.py`(D-005) (F-007, 버전 0007) |
| drafts | 자소서 초안 | `user_id` · `application_id` · `question_id`(FK `ON DELETE CASCADE`, 문항당 하나 — `question_id` 유니크), `ai_text`(AI가 쓴 원문 — '내가 고친 비율' 계산용, 고쳐도 안 바뀜), `version`(저장마다 +1 — '화면이 읽은 값일 때만' 올리는 조건부 갱신이라 두 탭이 동시에 저장해도 한쪽은 409, F-008 1차 리뷰), `completed_at`([이 문항 완료], 고치면 비움), `created_at` · `updated_at`. 다시 쓰면 지우고 새로 넣음(version은 이어서 +1) (F-008, 버전 0008) |
| draft_sentences | 초안 문장 + 근거 | `user_id` · `draft_id`(FK `ON DELETE CASCADE`), `position`(초안+순서 유니크), `text`, `origin`(ai · edited · user), `original_text`(AI 원래 문장), 근거 `card_id`(FK `ON DELETE SET NULL` — 카드를 지워도 인용은 남아 '카드 없음'), `slot` · `quote` · `quote_source` · `quote_start` · `quote_end`, `evidence_origin`(ai · user — [카드 연결]). 근거 상태는 저장하지 않고 읽을 때 지금 카드 칸과 비교 (F-008, 버전 0008) |
| draft_logs | 초안 쓰기 평가 로그 | `user_id`(FK `ON DELETE CASCADE`), `application_id` · `question_id`(외래키 아님 — 지워도 남김), `cards_sent`, `sentences`, `supported`, `drop_reasons`(JSON — no_evidence · card_not_sent · quote_not_found 등), `chars` · `char_limit`, `outcome`(ok · no_sentences · AI 오류 종류), `created_at`. 선점은 `application_claims`를 같이 씀(분석과 초안 쓰기가 같은 공고에서 동시에 돌지 않음) (F-008, 버전 0008) |
| interview_questions | 면접 질문 | card_id 근거, 내 답 메모 |
| eval_runs | 평가 실행 기록 | 데이터 세트 버전, 지표 3개, 날짜 |

- 모든 사용자 데이터 테이블에 `user_id`(외래키 `ON DELETE CASCADE`)를 두고, 조회할 때 항상 `user_id` 조건을 건다.
- 전체 테이블 계획은 위 표대로 유지하되, 실제 DB 마이그레이션은 주차별로 쓰는 테이블부터 만든다(1주차: `users`, `notes`, `chunks` / 2주차: `search_logs`, 조각 검색 색인 / 3주차: `ai_usage_logs`, `quizzes`, `quiz_reviews`, `quiz_attempts`, `quiz_generation_logs`, `note_quiz_claims` / 4주차: `cards`, `card_fields`, `note_card_claims`, `card_generation_logs`, `notion_connections`, `notes.notion_page_id`).
- 검색 평가 세트와 결과는 DB가 아니라 로컬 파일(`backend/eval/`, 레포 밖)에 둔다(F-003, 사용자 확인). `eval_runs`는 F-010 평가 리포트 때 정한다.
- 샘플 체험 데이터는 읽기 전용 별도 표시(같은 테이블에 플래그 vs 별도 스키마 — Q-004).

최종 수정: 2026-11-11 · 관련: D-003, D-004, D-005, D-016, D-018, F-001, F-003, F-004, F-006
