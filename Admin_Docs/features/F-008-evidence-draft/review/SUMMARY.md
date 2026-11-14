# F-008 근거 달린 자소서 — 리뷰 요약

## 한눈에 보기
상태: [통과]
회차: 4차 (2026-11-14) — 범위 R1 · R3 · R4(3차 반영분: 정렬 새 배열 · 완료 조건부 갱신 · 고른 문장 유지 · 공개 이름 · schemas.py · 라우터가 근거 없는 문장 수 조합 · 상수 테스트). R2는 3차 결과(제안 1 → 반영) 그대로 — 보안 변경이 없어 사용자 선택으로 뺌.
한 줄 요약: [위험] · [주의] 0개예요. R3 · R4 지적 없음, R1 제안 3개(그중 1개는 3차 noqa 지적과 같은 곳).

## 리뷰어별 결과
| 리뷰어 | 모델 | 판정 | 위험 | 주의 | 제안 | 신규 | 추정 | 근거 검토 |
|---|---|---|---|---|---|---|---|---|
| R1 구조·가독성 | Sonnet | 지적 있음 | 0 | 0 | 3 | 2 | 0 | 타당 |
| R2 보안·성능 | Opus | (3차 그대로) | 0 | 0 | 1 | - | 1 | 3차 타당 |
| R3 예외 처리·테스트 | Sonnet | 지적 없음 | 0 | 0 | 0 | 0 | 0 | 타당 |
| R4 설계 의도·API 계약 | Sonnet | 지적 없음 | 0 | 0 | 0 | 0 | 0 | 타당 |

## 신규 지적
- R1 [신규] [제안] `DraftCheckResult.supported`를 안 씀 + `_evidence_problem`이 만든 CheckedSentence를 필드마다 옮겨 적음(`dataclasses.replace`로).
- R1 [신규] [제안] drafts.py의 `_PREPARE_ERRORS` 튜플과 `_prepare_error` 사슬이 같은 예외 7개를 두 곳에 — 딕셔너리 하나로. 서식(빈 줄 3줄 두 곳 · 1줄 한 곳 · 140자 줄).

## 기존 지적
- R1 [제안] draft_service의 `# noqa: F401` 재수출(DraftNotFound · OtherAIWorkInProgress) — 라우터가 원래 모듈에서 바로 가져오게(3차에서 주석만 고쳤던 곳).

## 근거 검토 결과 (AI 1차)
- 세 리뷰어 모두 체크 항목을 위치와 함께 다뤘고(R1 15 · R3 12 · R4 19줄) 확신 표시가 확인 범위와 맞아요. 재실행 없음.

## 최종 판정 (사용자 확인 — 문장 정리사 사용, AI가 내용 지어내기 금지)
- 수용할 지적과 이유: 4차 제안 3개를 모두 고치고 리뷰를 끝낸다. (사용자 확인)
- 거절할 지적과 이유: 없음. (사용자 확인)
- 다음에 고칠 것: 카드 칸 읽기 쿼리 두 벌 합치기(1차에서 넘어옴). (사용자 확인)

## 4차 지적 처리 결과 (2026-11-14, AI 작성)
- `DraftCheckResult.supported` 삭제, 근거 붙은 문장은 `dataclasses.replace(checked, text=text)`.
- drafts.py '부르기 전' 오류를 예외 → HTTP 표(`_PREPARE_ERRORS` 딕셔너리) 한 곳으로, `except tuple(_PREPARE_ERRORS)`.
- 라우터가 `DraftNotFound`는 draft_view, `OtherAIWorkInProgress`는 note_claim에서 직접 가져옴 — draft_service의 noqa 재수출 없앰.
- 새 파일의 빈 줄 · 긴 조건 줄 정리(레포 전체 `ruff format`은 돌리지 않음 — 기존 파일이 바뀌어서). 한국어 문구 줄 길이는 기존 파일과 같은 방식이라 그대로.
- 테스트: 백엔드 SQLite 490 · PostgreSQL 503 통과(프론트는 바뀌지 않음).
- 리뷰 끝(사용자 선택, 5차 없음).

## 3차 (2026-11-14) 요약
- [주의] 위험 0 · 신규 주의 1(카드 목록 정렬이 props 배열을 바꿈 — R1) · 신규 제안 8, R3 지적 없음.
- 최종 판정(사용자 확인):
- 수용할 지적과 이유: 3차 지적을 모두 받아들인다(주의 1 · 제안 8). (사용자 확인)
- 거절할 지적과 이유: 없음. (사용자 확인)
- 다음에 고칠 것: 카드 칸 읽기 쿼리 두 벌 합치기(1차에서 넘어옴). (사용자 확인)

- 처리 결과:
- 정렬(R1 주의): `filterCardsByTitle`이 항상 새 배열을 돌려줌.
- 완료 경합(R2): `set_draft_completed`를 조건부 UPDATE로, 0줄이면 404. 테스트 `test_complete_after_the_draft_was_replaced_is_not_found`.
- 고른 문장(R1): 저장 뒤 편집 목록의 같은 자리 새 번호로 다시 고름. 화면 테스트에 한 줄.
- 이름 · 주석(R1): `build_draft_view` · `load_draft_with_question` · `sentences_of_drafts`, noqa 주석을 실제대로.
- 구조(R1): `app/api/schemas.py`(ServiceOut · RAW_INPUT_SLACK), 지원 상세의 근거 없는 문장 수는 라우터 `_detail_out`이 조합(공고 서비스 → 초안 의존 없앰), 프론트 · 백엔드 상수 같은지 테스트.
- 문서(R4): feature.md 리뷰 칸 · 최종 수정, api-list 날짜.
- 테스트: 백엔드 SQLite 490 · PostgreSQL 503, 프론트 Playwright 76(record-search 200KB 1개는 시간 상한 경계 — 따로 2번 통과, 사이드바 CSS를 빼도 같은 시간이라 관계없음 확인).


## 2차 (2026-11-14) 요약
- [주의] 위험 0 · 신규 주의 2(문항 저장 '먼저 바뀜' — R2, '마지막 검사' 시각 — R1) · 신규 제안 13 · 기존 제안 1.
- 최종 판정(사용자 확인):
- 수용할 지적과 이유: 2차 지적을 모두 받아들인다(주의 2 · 제안 14). 근거 검사는 코드를 find_in_field 함수 하나로 맞춘다. (사용자 확인)
- 거절할 지적과 이유: 없음. (사용자 확인)
- 다음에 고칠 것: 카드 칸 읽기 쿼리 두 벌 합치기(1차에서 넘어옴). (사용자 확인)

- 처리 결과:
- 문항 '먼저 바뀜'(R2 주의 · R3): 화면이 지울 문항을 `removed_ids`로 보내고, '보낸 + 지울 = 지금 목록'이 아니면 409. 공고 줄 잠금(FOR UPDATE), 커밋의 IntegrityError · StaleDataError도 409. 화면은 409면 새 목록을 받음.
- '마지막 검사'(R1 주의): 서버 `checked_at`(저장 뒤엔 저장 시각)을 씀.
- 근거 검사(R1, 사용자 결정): 다시 검사 · [카드 연결]도 `draft_evidence.find_in_card` → `find_in_field`.
- R2: 프롬프트 방어 문장을 회사 · 직무 · 역량 이름까지, `EDITED_PERCENT_EXACT_LIMIT` 50,000.
- R1 구조: `draft_view.py`(읽기) 분리, `update_draft`에서 `_origin_after_edit` · `_row_for_edit` 분리, `editsOf` 재사용 · `saveOne`, `EvidenceLink` · `QuoteSource` · `RequestState` 타입, `CardSearchInput` · `filterCardsByTitle` 공용, DraftEditor props 묶음(selection · write · save · complete), import 정렬.
- R3 테스트: 백엔드 6개(문항 409 · 문항 422 · 문장 제어 문자 · AI 중 삭제 · 엔드포인트 abandon · 401), 화면 4개(목록 실패 · 404, 완료 실패, 쓰기 404 뒤 다시 받기 실패 알림, 문항 422 · 409). 다시 받기 실패 알림이 늦던 것(기본 재시도 3번)을 `retry: 1`로.
- R4: feature.md 결과 칸 · STATUS 테스트 개수.
- 테스트: 백엔드 SQLite 488 · PostgreSQL 501, 프론트 Playwright 76 · tsc · eslint 통과.


## 1차 (2026-11-14) 요약
- [주의] 위험 0 · 주의 3(동시 저장 500 — R2 · R3, 카드 번호 범위 — R2, data-model.md 옛 줄 — R1) · 제안 14.
- 최종 판정(사용자 확인): 1차 지적을 모두 받아들인다(주의 3 · 제안 14). '근거 떼기'는 둔다. 거절 없음. 다음에 고칠 것: 카드 칸 읽기 쿼리 두 벌(load_saved_cards · load_cards_now) 합치기.
- 처리: 조건부 version 갱신 · 번호 범위(DbId) · 매칭 카드만 읽기 · 긴 글 근사 · 실패 경로 테스트 7개 + 화면 409 · 422 · 다시 받기 실패 안내 · 404 새로 받기 · draft_mock.py · _replace_draft · 작은 props · 문서. 테스트 백엔드 SQLite 482 · PostgreSQL 495, Playwright 72 통과.
