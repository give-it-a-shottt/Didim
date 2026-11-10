# F-001 fix-01-alembic 리뷰 요약

## 한눈에 보기
상태: [통과]
회차: 2차 (2026-11-10)
한 줄 요약: 1차 [주의] 지적(A~G)을 모두 반영했고, PostgreSQL에서도 테스트가 통과하고 개발 DB에 stamp 뒤 서버가 실제로 떴어요. 남은 건 R1의 [제안] 2건(한 줄짜리 정리)뿐이에요.

## 리뷰어별 결과
| 리뷰어 | 모델 | 판정 | 위험 | 주의 | 제안 | 신규 | 추정 | 근거 검토 |
|---|---|---|---|---|---|---|---|---|
| R1 구조·가독성 | Sonnet 5.5 | 지적 2 | 0 | 0 | 2 | 1 | 0 | 타당 |
| R3 예외 처리·테스트 | Sonnet 5.5 | 지적 없음 | 0 | 0 | 0 | 0 | 0 | 타당 |
| R4 설계 의도·API 계약 | Sonnet 5.5 | 지적 없음 | 0 | 0 | 0 | 0 | 0 | 타당 |

범위: 버그 수정(안내 오류 분리) · 리팩터링(파일 이름 · 엔진 함수) · 테스트 보강 · 문서 정정 → R1 · R3 · R4. 패키지 변경 없음 → R2 제외(1차 R2.md는 1차 결과 그대로).

## 신규 지적
- [신규] [제안] [확실] `ensure_db_migrated`의 리스트 컴프리헨션 조건에서 `known_revisions()`를 revision마다 다시 부름(버전 파일을 반복해 읽음) — R1. `backend/app/db/schema_version.py:90`. 시작 때 한 번이고 버전이 몇 개뿐이라 성능 문제는 없음. 고치는 방법: `known = known_revisions()`를 앞에 두고 `revision not in known`.

## 기존 지적(1차에서 이어짐)
- [제안] [확실] `test_server_refuses_to_start_without_database_url`이 session.py의 비공개 변수 `_engine` · `_session_factory`를 직접 비움 — R1. `backend/tests/test_migrations.py:194-195`. 1차 지적 3(테스트 도우미 결합)의 남은 부분. 변수 이름이 바뀌면 바로 실패해 발견은 쉽고 주석이 의도를 설명함. 고치는 방법: session.py에 테스트용 초기화 함수를 두거나 주석 한 줄 추가.

## 1차 지적 해소 확인 (메인 + 리뷰어)
| 1차 | 내용 | 해소 | 확인한 곳 |
|---|---|---|---|
| A [주의] | PostgreSQL 미실행 | 됨 | PostgreSQL didim_test 전체 110 통과, 개발 DB stamp 0001 → current 0001 (head) → lifespan 시작 · /api/health 200 (R3) |
| B [주의] | DB가 코드보다 앞설 때 안내 틀림 | 됨 | `DatabaseAheadOfCodeError` 분리, 테스트 `test_db_newer_than_code_is_reported_separately` (R3) |
| C [주의] | DB 연결 실패 처리 · 테스트 없음 | 됨 | `DatabaseUnavailableError`(OperationalError 변환, 주소 비노출, `__cause__` 보존), 테스트 `test_unreachable_db_is_reported_without_its_address` (R3) |
| D [주의] | D-015 "왜" 미확인 | 됨 | D-015:6 "(사용자 확인)" (R4) |
| E [제안] | stamp 뒤 통과 경로 · DATABASE_URL 없이 lifespan 테스트 | 됨 | `test_create_all_db_passes_after_stamping_first_version`, `test_server_refuses_to_start_without_database_url` (R3) |
| F [제안] | 지연 import · 파일 이름 겹침 · fixture가 비공개 변수 사용 | 대부분 됨 | 맨 위 import, `schema_version.py`, `startup_uses`가 공개 `get_engine` 교체. 남은 부분은 위 기존 지적 1건 (R1) |
| G [제안] | data-model.md embedding · START_HERE "메모리 SQLite" | 됨 | data-model.md:14(사용자 확인), START_HERE.md:62 (R4) |

## 근거 검토 결과 (AI 1차)
- 세 리뷰어 모두 체크 항목마다 위치 · 결과가 있고 위치는 실제 파일 줄 번호. 지정 모델(Sonnet) 그대로, 테스트 재실행 없음. 멈춤 · 재실행 없음.
- 메인이 R1 지적 2건의 위치를 실제 파일과 대조: schema_version.py:90의 `known_revisions()` 호출, test_migrations.py:194-195의 `_engine` · `_session_factory` 패치 — 일치. [확실] 표시 적절.
- 회차 비교: R1 지적 1은 1차 지적 3과 같은 항목(테스트 도우미 결합) → 기존. R1 지적 2는 1차에 없음 → [신규]. R3 · R4는 지적 없음.

## 최종 판정 (사용자 확인 — 문장 정리사 사용, AI가 내용 지어내기 금지)
- (사용자 판정 대기) — 정할 것: R1 [제안] 2건을 지금 고칠지(한 줄씩, 고치면 R1 · R3 3차), 다음 코드 변경 때 함께 고칠지.
