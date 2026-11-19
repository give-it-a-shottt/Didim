# F-015 로그인 허용 목록

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 구현 · 리뷰 4차 [통과](2026-11-19).
언제: 8주차, 배포 전(D-031)
무엇을: 구글 로그인을 서버가 허용한 이메일(본인)만 받게 해요. 그 밖의 사람은 샘플 체험으로 안내해요.
왜: 공개 배포를 하면 누구나 가입해 AI 기능을 쓸 수 있고, 그 사람의 기록이 체험판 AI로 넘어가요(D-031).

## 설계 의도 (사용자 확인 — 코드 작성 전에 채움, 문장 정리사 사용)
- 이 기능이 해결하는 문제 (사용자 확인 2026-11-19): 공개 배포를 하면 구글 계정이 있는 누구나 가입해 AI 기능을 쓸 수 있고, 그 사람의 기록이 체험판 AI로 넘어간다(D-031).
- 완료 기준 (사용자 확인 2026-11-19):
  1. 환경변수 `ALLOWED_LOGIN_EMAILS`(쉼표로 여러 개)에 있는 이메일만 구글 로그인이 된다. 목록에 없는 사람은 계정을 만들지 않는다.
  2. 막힌 사람은 로그인 화면으로 돌아가 "지금은 샘플 체험만 열려 있어요" 안내와 [샘플로 체험하기]를 본다.
  3. 이미 로그인한 사람도 목록에서 빠지면 다음 요청부터 401 — 세션이 남아 있어도(최대 7일) 바로 막힌다.
  4. 목록이 비어 있으면 로컬에서만 누구나 로그인된다. 운영에서 비어 있으면 서버가 시작하지 않는다(사용자 확인 2026-11-19, 1차 리뷰 R2 — 처음 문장: '목록이 비어 있으면 지금처럼 누구나(로컬 개발용). 운영에서 빠뜨리지 않게 Q-012 배포 체크리스트에 적는다.').
  5. 샘플 체험(`/demo`)은 목록과 상관없이 열린다.
- 정한 기준 (사용자 확인 2026-11-19): 이메일은 대소문자를 무시하고 비교한다. 구글이 확인한 이메일(`email_verified`)만 인정한다.
  - ASCII가 아닌 이메일은 받지 않고, 목록에 적어도 뺀다(유니코드를 소문자로 바꾸면 다른 주소가 같아질 수 있어서). (사용자 확인 2026-11-19, 1차 리뷰 R2)
  - '운영'은 COOKIE_SECURE=true이거나, 화면 주소(FRONTEND_URL) · 구글 로그인 돌아올 주소(GOOGLE_REDIRECT_URI) 중 하나라도 https · localhost가 아닌 경우다. (사용자 선택 2026-11-19, 2 · 3차 리뷰 R2)

## 결과 (AI 작성 — 구현 후)
- 설정: `ALLOWED_LOGIN_EMAILS`(쉼표) → `config.parse_email_list`(앞뒤 빈칸 제거 · ASCII만 · 소문자) → `Settings.allowed_login_emails`. `config.is_production`(COOKIE_SECURE=true, 또는 FRONTEND_URL · GOOGLE_REDIRECT_URI 중 하나라도 https · localhost 아님), `check_login_allowlist_at_startup`을 `main.py`가 앱을 불러올 때(처음엔 lifespan — F-016 1차 리뷰 R2로 옮김, D-032) — 운영인데 목록이 비면 `LoginConfigError`로 시작하지 않음, 버린 항목은 개수만 · 운영인데 COOKIE_SECURE 꺼짐은 경고 로그.
- 판단: `auth_service.is_login_allowed(settings, email, *, email_verified)` 한 곳 — 목록이 비면 누구나, 있으면 구글이 확인한 ASCII 이메일만 대소문자 무시. `GoogleProfile.email_verified`는 userinfo의 `email_verified is True`, 기본값은 닫는 쪽(False).
- 막는 곳: 구글 콜백(`api/auth.py`)이 계정을 만들기 전에 → `/login?error=not_allowed`(state 쿠키 삭제). `deps.get_current_user`가 매 요청(샘플 계정 제외) → 401 `지금은 샘플 체험만 열려 있어요.` + 머리말 `X-Didim-Login-Error: not_allowed`.
- 화면: 로그인 화면 `ERROR_MESSAGES.not_allowed`(아래 '로그인 없이 샘플로 둘러보기'로 이어짐), `lib/auth.ts` `checkCurrentUser`(cache)가 머리말을 읽어 `requireCurrentUser`가 `/login?error=not_allowed`로(랜딩의 `getCurrentUserOrNull`은 그대로 null — 리다이렉트 안 함).
- 테스트: backend `tests/test_login_allowlist.py` 19(파싱 · 판단 · 켈빈 기호 · 콜백 차단 · 미확인 이메일 · 대소문자 · 세션 중 빠짐 → /me · /notes · import 401 + 머리말 · 샘플 · 운영 판단 4갈래 · 로컬 · lifespan 연결 · 경고 로그 · exchange 변환), conftest `client`가 운영 환경변수를 비움. frontend `auth-and-routes.spec.ts`(not_allowed 안내 · 막힌 세션으로 /home · /records → 안내 있는 로그인 화면), 가짜 백엔드 `-blocked` 세션. 백엔드 SQLite 682 · PostgreSQL 695, Playwright 124 통과(2026-11-19). 실제 구글 로그인 · 운영 배포로는 확인 안 함(Q-012 배포 확인 항목).
- 설계 의도와 다른 점: 완료 기준 2의 [샘플로 체험하기]는 로그인 화면에 이미 있던 '로그인 없이 샘플로 둘러보기' 링크를 씀. 완료 기준 4와 정한 기준은 리뷰에서 사용자 승인으로 고침(위).

## 리뷰
- [review/SUMMARY.md](review/SUMMARY.md) — 4차(2026-11-19) [통과]. 1차 [주의] 주의 4 → 2차 [주의] 주의 1 → 3차 [주의] 주의 1(남은 틈) → 4차 [통과]. 다음에 고칠 것: 운영 Secure 쿠키 강제 여부(Q-012).

## 열린 질문
- 없음

## 면접 예상 질문
1. 공개 배포에서 AI 기능을 왜 막았고, 왜 화면이 아니라 서버에서 막았나요? 막힌 사람에게는 무엇을 보여 주나요?
2. 허용 목록을 운영에서 빠뜨리면 어떻게 되나요? '운영인지'는 어떻게 판단하고, 그 판단이 놓칠 수 있는 경우는?
3. 이메일을 소문자로 바꿔 비교하는데 ASCII가 아닌 이메일을 막은 이유는? (켈빈 기호 예와 테스트가 잡은 버그)
- 답 (사용자 확인 — 문장 정리사 사용)

최종 수정: 2026-11-19 · 관련: D-031, D-027, D-029, D-010, F-001
