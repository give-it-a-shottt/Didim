# F-009 면접 연습 — 리뷰 요약

## 한눈에 보기
상태: [주의]
회차: 4차 (2026-11-16) — 범위 R1~R4(기능 추가 · 변경: F-009 평가 코드 + F-014 NVIDIA 제공자(D-027) + 프론트 lib/json.ts 정리). 앞 회차와 범위(코드)가 달라 지적은 모두 신규.
한 줄 요약: [위험] 0 · [주의] 3 · 제안 10(겹침: 안내 문구 nvidia 누락 — R1 · R3 · R4). 평가 방법 · 완료 기준 4는 충족(R4), 키 취급 · 평가용 임시 DB · 결과 파일 · 429는 이상 없음(R2).

## 리뷰어별 결과
| 리뷰어 | 모델 | 판정 | 위험 | 주의 | 제안 | 신규 | 추정 | 근거 검토 |
|---|---|---|---|---|---|---|---|---|
| R1 구조·가독성 | Sonnet 5.5 | 지적 있음 | 0 | 1 | 4 | 5 | 1 | 타당 |
| R2 보안·성능 | Opus 5.5 | 지적 있음 | 0 | 1 | 0 | 1 | 0 | 타당 |
| R3 예외 처리·테스트 | Sonnet 5.5 | 지적 있음 | 0 | 1 | 3 | 4 | 1 | 타당 |
| R4 설계 의도·API 계약 | Sonnet 5.5 | 지적 있음 | 0 | 0 | 3 | 3 | 0 | 타당 |

## 신규 지적
- R2 [주의] [확실] `LLM_BASE_URL` 하나를 exaone · nvidia · local이 같이 써서, provider를 넘겨 부르는 실행(`llm_ping exaone` · `interview_eval exaone`)에서 한 회사의 키가 다른 회사 주소로 갈 수 있음 — `app/llm/settings.py`. 지금 `.env.example`에선 주석이라 기본 설정에선 안 일어남. 고치는 방법: local일 때만 읽기 또는 제공자별 주소 변수 — **사용자 선택 필요**.
- R3 [주의] [확실] NVIDIA 모델 종료(410)가 일반 4xx(LLMRequestError — '보낸 내용 문제'로 읽힘)로 떨어지고, 404 안내가 `NVIDIA_MODEL` 대신 `LLM_MODEL`을 가리킴 — `openai_compat.py`. 410도 설정 오류로, 안내는 제공자별 변수 이름으로.
- R1 [주의] [확실] `llm_ping.py` 안내가 nvidia 모델을 `LLM_MODEL`로 적음(실제 `NVIDIA_MODEL`). (R3 제안 · R4 제안과 같은 줄기: `interview_eval.py` provider 도움말에 nvidia 없음)
- R1 [제안] `draft_eval.py`의 `_write_json` 별칭이 남음(테스트가 그 이름을 부름) — 호출을 `write_json_atomic`으로, 테스트는 `eval_files` 쪽으로.
- R1 [제안] [추정] `_saved_by_text`가 질문 글을 키로 써서 AI가 같은 글을 두 번 내면 하나로 셈 — 키를 `view.id`로.
- R1 [제안] `planted_questions`의 긴 한 줄 · `applications.ts` 빈 줄 2개.
- R3 [제안] `--score`가 모양이 틀린 파일(AttributeError)과 쓰기 실패(OSError — 편집기가 파일을 잡고 있을 때)를 트레이스백으로 끝냄.
- R3 [제안] 테스트 빈틈: `--score` 정상 경로, `write_json_atomic` 실패 보호(새 모듈), `_run` 설정 오류 종료 코드, 심은 질문 상한 · 짝 오류, nvidia 404 · 410.
- R4 [제안] feature.md 맨 위 상태 줄이 옛 상태, 평가 방법 문구의 '실제 AI(EXAONE)'에 D-027 뒤 메인이 바뀐 것을 주석으로.

## 추정 지적
- R1 `_saved_by_text` 중복 글 — `save_interview`가 같은 질문 글을 둘 다 저장하는지 보면 확실해짐.

## 근거 검토 결과 (AI 1차)
- 네 리뷰어 모두 체크 항목을 위치와 함께 다뤘고 확신 표시가 확인 범위와 맞아요. 재실행 없음. 리뷰 뒤 PostgreSQL 566 passed · 1 skipped(Docker 켠 뒤 메인이 실행).

## 최종 판정 (사용자 확인 — 문장 정리사 사용, AI가 내용 지어내기 금지)
- 수용할 지적과 이유: 4차 지적을 모두 받아들인다. 주소 설정은 키를 보내지 않는 local일 때만 읽게 한다. (사용자 확인, 2026-11-16)
- 거절할 지적과 이유: 없음. (사용자 확인)
- 다음에 고칠 것: 없음. 5차 확인 리뷰는 건너뛰고 커밋한다. (사용자 확인)

## 4차 지적 처리 결과 (2026-11-16, AI 작성)
- R2 주소 공유: `LLM_BASE_URL`은 local일 때만 읽고, 키를 보내는 exaone · nvidia는 코드의 공식 https 주소 고정(사용자 선택). 쓰이지 않게 된 https 강제 검사는 지움. 테스트 `test_keyed_providers_ignore_llm_base_url`.
- R3 404 · 410: 410(모델 종료)도 설정 오류로, 안내는 제공자별 변수(`_model_hint` — nvidia면 NVIDIA_MODEL). 테스트 `test_missing_or_retired_model_points_to_the_right_setting`.
- 안내 문구(R1 · R3 · R4): `llm_ping` 주석 NVIDIA_MODEL, 평가 스크립트 도움말은 제공자 목록에서 만듦(`eval_files.PROVIDER_HELP`).
- R1: `draft_eval._write_json` 별칭 지우고 `write_json_atomic` 직접, 쓰기 테스트는 `tests/test_eval_files.py`로. AI 질문은 저장된 줄을 그대로 셈(글로 묶지 않음). `planted_questions` 긴 줄 풀어 씀, `applications.ts` 빈 줄.
- R3: `--score`가 모양이 틀린 파일(TypeError) · 쓰기 실패(OSError)를 메시지로 알림. 테스트 +5(다시 채점 정상 · 모양 오류 · 잠긴 파일, 설정 오류 · mock 종료 코드, 심은 질문 상한 · 짝).
- R4: feature.md 상태 줄, 평가 방법 문구에 D-027 주(AI 작성 칸).
- 테스트: 백엔드 SQLite 561 · PostgreSQL 574 passed, 프론트 tsc · eslint · Playwright 90 passed.

## 이전 회차 (요약 — 자세한 기록은 git)
- 3차 (2026-11-16, R1 · R2 · R3): [통과] 위험 0 · 주의 0 · 제안 9(겹침 2쌍 — 실제 7, 1건은 리뷰 뒤 해소). 최종 판정(사용자 확인): 3차 제안을 모두 받아들인다. 선점 뒤 DB 오류 처리는 공통화를 기다리지 않고 지금 고친다. 거절 · 다음에 고칠 것 없음, 4차는 건너뛰고 화면 확인으로.
- 1차 (2026-11-15, R1~R4): [주의] 위험 0 · 주의 4 · 제안 11. 최종 판정(사용자 확인): 1차 지적을 모두 받아들인다(주의 4 · 제안 11). 3개 미만 질문은 저장하고 끝내고, 같은 글 질문은 서버에서 하나로 합친다. 거절 없음. 다음에 고칠 것: F-008과 같은 모양의 저장 · 실패 처리 공통화(세 번째 AI 쓰기 기능 전에).
- 2차 (2026-11-16, R1~R4): [주의] 위험 0 · 주의 2(신규 — R2 트랜잭션 연 채 AI 호출, R4 합쳐진 카드가 '질문 없는 카드') · 제안 8. 최종 판정: 2차 지적을 모두 받아들인다. 합쳐진 카드는 '질문 없는 카드'에서 빼고, 메모는 카드마다 따로 둔다. 3차는 R1 · R2 · R3로 한다. (사용자 확인, 2026-11-16) 카드 삭제 확인 문구(사용자 확인) '이 카드를 지울까요? 내가 쓴 답과 면접 질문 · 메모도 같이 지워져요.'
- 2차 처리 결과(AI 작성): `prepare_interview`가 다시 확인 뒤 `db.rollback()`, `has_questions`(합치기 전 질문 유무), 삭제 확인 문구, `MakeState`로 버튼 · 안내 조건 한 곳, `isNullableString`을 `lib/json.ts`로(interview.ts만), 서버 수 · 화면 수 관계 주석, 테스트 주제별 구역 · 이름 고침, 선점을 잃은 저장 · AI 중 카드 삭제 404 · 다른 탭 409 화면 테스트.
