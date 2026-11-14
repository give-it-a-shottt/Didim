# 아키텍처

## 한눈에 보기 (코드 몰라도 OK)
상태: [주의] 계획이에요. 세팅만 끝났고(2026-11-08) 기능 코드는 없어서, 만들면서 실제 모양으로 고쳐요.
무엇을: 화면(Next.js)이 서버(FastAPI)에 요청하면, 서버는 DB 한 곳(PostgreSQL)에서 내 기록과 "뜻이 비슷한 조각"을 함께 찾고, 필요한 조각만 AI에 보내 퀴즈 · 카드 · 자소서를 만들어요. AI가 만든 것은 항상 근거(어느 노트 · 카드의 어디)와 같이 저장돼요.
왜: DB를 하나로 두면 운영이 단순하고, 근거를 같이 저장해야 "지어낸 문장"을 잡아낼 수 있어요.

```
브라우저 ── Next.js (화면)
   │  fetch /api/*  (Next.js가 FastAPI로 넘김 = 같은 주소처럼 보임)
   ▼
FastAPI (서버, 모든 경로가 /api 아래)
   ├─ 가져오기 어댑터: Markdown | Notion  ──▶ 같은 기록 모양
   ├─ RAG: 나누기 → 검색 (처음은 키워드, 임베딩 · 벡터는 평가로 비교한 뒤 — D-016, 사용자 조건 필수)
   ├─ 생성: 퀴즈 · 카드 후보 · 공고 역량 · 자소서 · 면접 질문
   │    └─ 근거 검사 루프: 쓰기 → 검사 → 고치기
   ├─ LLM 클라이언트: mock | exaone | local (D-014, F-014)
   └─ 사용량 제한 · 평가 로그
   ▼
PostgreSQL + pgvector (기록 · 조각 · 임베딩 · 카드 · 공고 · 문장 · 근거)
```

## 개발자 상세

### 지금 폴더 구조 (2026-11-12, Q-013 임시)
```
frontend/                 Next.js 16 (App Router, TypeScript, Tailwind 4)
  next.config.ts          /api/* → BACKEND_URL 프록시(rewrites), /applications/[id] → 공고 분석 탭(redirects)
  playwright.config.ts    Playwright 스모크 · 인증 리다이렉트 테스트 설정 (D-013)
  src/app/                화면(라우트) — 19개, 표는 screens.md
    (guest)/ (app)/ (focus)/   레이아웃 3종(URL에 안 나옴, 회원 레이아웃은 MemberAuthGuard로 보호)
  src/components/         공통 컴포넌트(app-sidebar, screen-placeholder, member-auth-guard, logout-button, import-records-dialog, highlighted-text, note-markdown — 노트 원문을 조각 단위로 react-markdown으로 그리고 고른 조각 강조, 200KB 넘으면 글자 그대로, D-017)
  src/lib/site.ts         사이트 이름 · 설명 · 주소 · 공개/회원 경로 (SEO)
  src/lib/auth.ts         서버에서 httpOnly 쿠키로 /api/auth/me 확인 · 비로그인 시 /login 이동
  src/lib/import-records.ts   기록 가져오기 요청 · 응답 모양, 보내기 전 개수 · 용량 확인 (F-002)
  src/lib/backend.ts      서버 컴포넌트 → FastAPI 호출 한 곳(BACKEND_URL · 세션 쿠키 붙이기, `fetchBackendAsUser`). auth.ts · records.ts가 같이 씀 (F-003 1차 리뷰 B)
  src/lib/records.ts      검색 · 노트 상세 API를 부르고 응답 모양 확인 (F-003)
  src/lib/notion.ts · notion-status.ts · notion-data.ts   노션 연결(F-005) — 브라우저 요청(목록 · 가져오기 · 끊기) / 상태 모양 · 안내 문구(서버 · 브라우저 공용, 요청 코드 없음) / 서버 컴포넌트의 상태 요청
  src/components/notion-connection-row.tsx   설정 '연결' 칸의 노션 줄 (F-005)
  src/lib/api-request.ts  브라우저 요청 한 곳(`apiRequest` · `ApiRequestError` — 네트워크 · 401 · 서버 문구 처리). quiz.ts · cards.ts가 같이 씀 (F-006 1차 리뷰 R1)
  src/lib/quiz.ts · cards.ts   퀴즈 · 경험 카드 응답 모양 확인 + 브라우저 요청, quiz-data.ts · cards-data.ts는 서버 컴포넌트용(server-only) (F-004 · F-006)
  src/components/card-*.tsx   경험 카드 화면(card-editor 상세 · card-review-sheet 후보 검토 · card-tile 목록 · note-card-panel 노트 상세 칸 · card-parts 원문 인용 부품) (F-006)
  src/lib/applications.ts · applications-data.ts   지원 · 공고 분석(F-007) 응답 모양 + 브라우저 요청 / 서버 컴포넌트용(server-only, 상세는 React cache — 머리 · 탭이 같이 부름)
  src/lib/drafts.ts · drafts-data.ts   자소서 초안(F-008) 응답 모양 + 브라우저 요청 / 서버 컴포넌트용(server-only)
  src/components/draft-workspace.tsx · draft-questions.tsx · draft-editor.tsx · draft-aside.tsx · card-link-dialog.tsx · card-search-input.tsx   자소서 탭(F-008): 상태 · 요청을 묶는 틀 / 왼쪽 문항 · 문항 고치기 · 경험 카드 / 가운데 문장 + 근거 칩 · 고치는 칸 · 초안 쓰기 · 빈 상태 · 쓰는 중 / 오른쪽 검사 · 근거 / [카드 연결] 창 / 카드 제목 검색 칸(왼쪽 목록 · 카드 연결 창 공용)
  src/components/application-parts.tsx · add-application-dialog.tsx · application-header-actions.tsx · posting-analysis.tsx · posting-requirements.tsx · posting-aside.tsx   지원 화면(F-007): 상태 · D-day 배지 / 공고 추가 모달 / 상세 머리의 탭 · 상태 선택(제목 줄 끝) · 공고 지우기(탭 줄 끝) / 공고 분석 탭(① 뽑기 → ② 매칭, 실패 안내) · 왼쪽 요구 역량 표 · 오른쪽 칸(요약 · 선택한 근거 · 공고 원문)
  src/components/request-error.tsx   요청 실패 문구 + 로그인 링크(`RequestErrorText` 한 줄 · `RequestErrorBlock` 버튼 모양) — 퀴즈 · 카드 화면이 같이 씀 (F-006 2차 리뷰 R1)
  src/app/robots.ts, sitemap.ts   검색 엔진 안내
  tests/                  Playwright E2E · 스모크 테스트 (auth-and-routes · import-records · record-search · quiz-review · experience-cards · notion-import · applications.spec.ts, mock-backend.mjs — 가짜 FastAPI)
backend/                  FastAPI (uv)
  app/main.py             앱 생성, lifespan에서 DB 버전 확인 · 종료 때 연결 닫기, 업로드 크기 미들웨어, 라우터를 /api 아래에 붙임
  app/config.py           환경변수 · 쿠키/상한 상수(가져오기 개수 · 용량, 조각 길이 포함)
  app/api/                라우터 (health.py, auth.py, notes.py, search.py, quizzes.py, cards.py, notion.py, applications.py, drafts.py, deps.py) + schemas.py(여러 라우터가 같이 쓰는 ServiceOut · RAW_INPUT_SLACK, F-008 3차 리뷰 R1) + errors.py(여러 라우터가 같이 쓰는 문구 · AI 오류 → HTTP 상태 변환 — 라우터끼리 서로 가져다 쓰지 않게, F-006 1차 리뷰 R1) + upload_limit.py(가져오기 요청의 로그인 쿠키 · 크기를 본문 받기 전 · 받는 동안 확인하는 ASGI 미들웨어)
  app/importers/          가져오기 어댑터(D-001) — 파일 · 노션 페이지를 같은 기록 모양(ImportedDocument)으로 (base.py, markdown.py, notion.py — 블록 나무 → 마크다운 글, 노션을 부르지 않는 순수 함수). 노션도 입력 모양(파일 바이트 · 블록 나무)이 달라 Protocol 없이 함수 두 개로 둠(F-005)
  app/notion/             노션 REST API 클라이언트(F-005) — 토큰 교환 · 갱신 · 회수 · 검색 · 페이지 · 블록 읽기, 호출 간격 · 429 · 5xx 재시도(토큰 요청은 다시 보내지 않음), 시간 예산(호출 안에서도 마감을 지킴). HTTP만 맡고 DB는 모름
  app/services/           비즈니스 로직 (auth_service.py, note_service.py, import_service.py, chunking.py, search_service.py, quiz_generation.py · quiz_review.py · quiz_evaluation.py, card_generation.py · card_service.py · card_evaluation.py, usage_service.py, notion_service.py — 노션 연결 저장 · 토큰 갱신(줄 잠금) · 페이지 목록 · 가져오기, token_crypto.py — 토큰 암호화, application_service.py — 공고 CRUD · D-day 순 목록, posting_analysis.py — 공고 분석 흐름(선점 · 저장 · 사용량) + posting_extraction.py(① 답 모양 · 검사) · posting_matching.py(② 키워드 후보 · 검사) · posting_checks.py(버린 이유 이름) · posting_mock.py(가짜 답) · posting_evaluation.py(평가 채점), draft_service.py — 자소서 초안 흐름(선점 · 저장 · 사용량) · 고치기 · 완료 + draft_view.py(읽기 — 문항별 초안 · 근거 상태 · 내가 고친 비율) · draft_writing.py(AI 답 모양 · 보내는 내용 · 근거 검사) · draft_mock.py(가짜 답) · draft_evidence.py(근거 다시 검사 — find_in_card → find_in_field)) + note_claim.py(AI를 오래 부르는 기능의 선점 규칙 한 곳 — 대상은 노트 또는 공고(ClaimTable.key) — 기능마다 다른 점은 ClaimTable · ClaimRules로, 사용자당 AI 작업 1개는 ALL_TABLES 전부를 봄(D-020), F-006 1차 리뷰 R1) · text_clean.py(제어 문자 막기 · 지우기 — PostgreSQL은 NUL을 못 받음, F-006 1차 리뷰 R2 / 공백 뺀 글자 수 · 한 줄 정리 · 자르기 — 퀴즈 · 카드 · 공고 분석 공용, F-007 1차 리뷰 R1)
  app/db/                 SQLAlchemy 2.0 모델(사용자 · 노트 · 조각 · 검색 로그 · 퀴즈 · 카드 · 노션 연결 · 지원(Application 외 5개, F-007) · 자소서 초안(Draft · DraftSentence · DraftLog, F-008)) · 세션 · DB 버전 확인 (base.py, models.py, session.py, schema_version.py)
  alembic.ini, migrations/   DB 구조 버전 파일(Alembic, D-015)
  app/llm/                LLM 연결(D-014, F-014) — 인터페이스 · mock · OpenAI 호환 클라이언트 · JSON 검사(complete_json)
  app/search/             기록 검색(F-003, D-016) — 검색 약속(Searcher) · 키워드 방식(pg_trgm) · 낱말 뽑기 · 발췌 · 평가 채점(evaluation.py)
  scripts/                손으로 돌리는 확인 스크립트 (llm_ping.py, search_eval.py — 로컬 평가 세트로 검색 채점, quiz_eval.py · card_eval.py — 가상 노트로 퀴즈 · 카드 평가, posting_eval.py — 가상 공고로 매칭 평가, D-005)
  eval/                   검색 평가 세트 예시(search_eval.example.json, 실제 세트 *.local.json · 결과 results/는 레포에 안 올림), quiz/ · cards/ · postings/(지어낸 가상 노트 · 공고 · 정답지 · 결과 — 레포에 올림)
  tests/                  pytest (test_health.py, test_auth_and_isolation.py, test_db_config.py, test_llm.py, test_migrations.py, test_import_markdown.py, test_search.py, test_search_eval.py, 퀴즈 · 카드 · 노션 테스트, test_applications.py · test_posting_evaluation.py)
```
- 레이어(라우터 → 서비스 → DB)는 `app/api/`(라우터) → `app/services/`(비즈니스 로직) → `app/db/`(모델 · 세션) 한 방향으로만 흐른다. `app/llm/` · `app/importers/` · `app/notion/`은 서비스가 부르는 아래층이고 db · api를 가져다 쓰지 않는다. `app/search/`도 서비스가 부르는 아래층인데, 검색 방식 자체가 "DB에서 어떻게 찾나"라서 db 모델은 읽는다(api · services는 가져다 쓰지 않음).
- 기록 검색(F-003): 라우터(`GET /api/search`)가 `Depends(get_searcher)`로 검색 방식을 받아 서비스에 넘기고 → 서비스가 낱말을 뽑아 검색 → 발췌를 만들고 → 검색 로그를 남긴다. 화면은 서버 컴포넌트가 주소의 `?q=`로 결과를 그리고, 결과를 누르면 노트 상세가 `?chunk=`의 조각 위치를 강조한다.
- 노션 가져오기(F-005): 라우터가 `NotionSession`(토큰 꺼내기 · 미리 갱신 · 401 뒤 한 번 갱신)을 열고 사용자당 가져오기 하나를 선점(`claim_import`, 연결 줄의 `importing_since`)한 뒤 서비스에 넘기고 → 서비스가 페이지마다 블록 나무를 읽어(상한 · 시간 예산) 어댑터로 마크다운 글로 바꾼 뒤 F-002와 같은 나누기 · 저장 함수로 넣는다. 노션을 부르는 동안에는 DB 트랜잭션을 닫아 둔다(연결 풀을 붙잡지 않게). 노션 오류 → HTTP 응답은 라우터의 `_http_error` 한 곳. 연결은 OAuth(설정 화면 → 노션 동의 화면 → 콜백, 비로그인이면 /login), 토큰은 암호화 저장.
- 공고 분석(F-007): 라우터가 ① `prepare_extract` → AI(`request_requirements`) → `save_extract`, ② `prepare_match` → AI(`request_matches`, 후보가 없으면 건너뜀) → `save_match` 순서로 부른다. 공고 선점(`application_claims`)은 퀴즈 · 카드와 같은 `note_claim` 규칙이라 사용자당 AI 작업 1개(D-020). 매칭 후보는 내 저장 카드만 읽어 파이썬에서 키워드 점수로 고른다(D-004). 화면은 ① 성공 뒤 ②를 이어 부르고 `router.refresh()`로 서버 컴포넌트를 새로 받는다.
- 자소서 초안(F-008): 라우터(`api/drafts.py`)가 `prepare_draft` → AI(`request_draft`) → `save_draft` 순서로 부른다(공고 선점 `application_claims`를 공고 분석과 같이 씀). 근거 검사는 `posting_matching.find_in_field` 함수 하나 — AI 초안 저장 · [카드 연결] · 읽을 때 다시 검사(`draft_evidence.find_in_card`)가 모두 이 함수를 부른다(사용자 확인 2026-11-14). 문항 목록 저장은 지울 문항을 화면이 직접 보내고 '보낸 + 지울 = 지금 목록'이 아니면 409(공고 줄 잠금). 지원 상세의 근거 없는 문장 수는 라우터(`api/applications._detail_out`)가 공고 서비스와 `draft_evidence`를 조합해 채운다 — 공고 서비스가 초안을 모르게. 근거 상태는 저장하지 않는다.
- 기록 가져오기(F-002): 라우터가 파일 앞부분(상한 + 1바이트)만 읽어 서비스에 넘기고 → 서비스가 파일마다 어댑터로 읽기 → 내 노트 안에서 중복 확인 → 나누기 → 저장(파일마다 커밋)한다. 조각은 노트 원문의 구간이고 제목 경로 · 원문 위치를 같이 저장한다(설계 원칙 1).

### 상태 관리 지도 (D-012)
기준: 서버 데이터 → 서버 컴포넌트 또는 TanStack Query / 여러 화면이 같이 쓰는 UI 상태 → Zustand / 화면 하나 → useState. 쓸 때마다 한 줄 추가해요.

| 상태 | 어디에 | 왜 | 기능 |
|---|---|---|---|
| 현재 로그인한 사용자 정보(`/settings`, 회원 레이아웃 보호) | 서버 컴포넌트(`requireCurrentUser`) | 첫 화면을 그릴 때 쿠키로 서버에서 바로 확인하고 비로그인이면 `/login`으로 보내기 위해 | F-001 |
| 로그아웃 버튼 진행 중(`isPending`) · 오류 문구(`errorMessage`) | 컴포넌트 안(`useState`, `logout-button.tsx`) | 설정 화면의 로그아웃 버튼 하나에서만 쓰는 일시적인 상태라서 | F-001 |
| 기록 추가 모달 열림 · 단계(올리기 · 처리 중 · 결과 · 오류) · 고른 파일 · 기록 종류 · 가져오기 결과 | 컴포넌트 안(`useState`, `import-records-dialog.tsx`) | 모달 하나에서만 쓰고, 결과는 한 번 보여 주고 버리는 응답이라 캐시할 서버 데이터가 아니라서. 저장 뒤에는 `router.refresh()`로 서버 컴포넌트 화면을 새로 받는다. 노트 목록 화면(서버 데이터)을 만들 때 TanStack Query를 검토 | F-002 |
| 기록 추가에서 파일을 끌어오는 중인지(`isDragging`, 깊이 `dragDepth`) | 컴포넌트 안(`useState` · `useRef`, `import-records-dialog.tsx` SelectStep) | 올리기 단계 하나에서만 쓰는 화면 표시 상태라서 | F-002 |
| 기록 검색어 · 검색 결과(`/records?q=`) | 주소(`?q=`) + 서버 컴포넌트(`records/page.tsx`, `lib/records.ts`) | 서버 데이터라서. 검색어를 주소에 두면 새로 고침 · 뒤로 가기 · 링크 공유에도 같은 결과가 나오고, 화면 쪽 상태가 필요 없다(입력칸은 `next/form`, 사용자 확인: GET) | F-003 |
| 노트 원문 · 강조할 조각(`/records/[noteId]?chunk=`) | 주소(`?chunk=`) + 서버 컴포넌트(`records/[noteId]/page.tsx`) | 서버 데이터라서. 강조할 조각도 주소에 두어 검색 결과 · 나중의 근거 칩이 같은 링크 모양을 쓴다 | F-003 |
| 오늘 복습 N · 노트 목록(`/records`) · 오답노트 목록 · 노트의 문제 수 | 서버 컴포넌트(`records/page.tsx` · `records/wrong-answers/page.tsx` · `records/[noteId]/page.tsx`, `lib/quiz-data.ts` · `lib/records.ts`) | 처음 화면을 그릴 때 필요한 서버 데이터라서. 홈의 두 목록은 서로 기다리지 않게 각자 Suspense | F-004 |
| 퀴즈 세션 종류 · 문제 목록(`/quiz/today` · `/quiz/wrong` · `/quiz/note-N`) | 주소 + 서버 컴포넌트(`(focus)/quiz/[sessionId]/page.tsx`) | 백엔드에 세션 표가 없어 주소가 세션 종류(사용자 확인 2026-11-11). 시작할 때 한 번 받아 고정해서 풀면서 '오늘 복습' 목록이 바뀌어도 세션 문제는 그대로 | F-004 |
| 퀴즈 진행(몇 번째 문제 · 고른 보기 · 점수 · 끝남) | 컴포넌트 안(`useState`, `quiz-runner.tsx`) | 퀴즈 화면 하나에서만 쓰는 값이라서. Next 16이 숨겨 두는 화면(Activity) 덕에 근거 칩 → 노트 → 뒤로 가기에서 풀던 자리가 남고, 다 풀면 숨겨질 때 처음으로 되돌린다. 문제 ID 목록을 key로 줘서 목록이 바뀌면 새로 그린다 | F-004 |
| 퀴즈 답 제출(진행 중 · 채점 결과 · 오류) | TanStack Query `useMutation`(`quiz-runner.tsx`) | 서버 수정이라서(D-012 예시). 진행 · 오류 상태를 직접 짜지 않고, 자동 재시도는 꺼 둔다(다시 보내면 풀이 기록이 두 번 남음 — `query-provider.tsx`) | F-004 |
| [문제 만들기](진행 중 · 만든 결과 · 오류) | TanStack Query `useMutation`(`note-quiz-panel.tsx`) + 성공 뒤 `router.refresh()` | 서버 수정이라서. 새로 받은 서버 컴포넌트가 문제 수를 바꾸고, 만든 결과 문구는 mutation이 갖고 있어 새로 고친 뒤에도 남는다. 자동 재시도 끔(AI를 두 번 부를 수 있음) | F-004 |
| 퀴즈 결과 점수(`/quiz/[sessionId]/result?correct=&total=`) | 주소 | 세션 표가 없어서. 새로 고침해도 같은 점수가 나오고, 답 하나하나는 이미 서버(quiz_attempts)에 있다. 이전 세션과의 점수 변화는 세션 기록이 생긴 뒤 | F-004 |
| 경험 카드 목록 · 탭(`/cards?tab=candidate`) · 노트의 카드 후보 · 찾았는지 · 카드 상세 첫 내용 | 주소(`?tab=`) + 서버 컴포넌트(`cards/page.tsx` · `cards/[cardId]/page.tsx` · `records/[noteId]/page.tsx`, `lib/cards-data.ts`) | 처음 화면을 그릴 때 필요한 서버 데이터라서. 탭을 주소에 두면 새로 고침 · 뒤로 가기에도 같은 탭 | F-006 |
| [카드 후보 찾기](진행 중 · 찾은 결과 · 오류) | TanStack Query `useMutation`(`note-card-panel.tsx`) + 성공 뒤 `router.refresh()` | [문제 만들기]와 같은 이유. 자동 재시도 끔(AI를 두 번 부를 수 있음) | F-006 |
| 후보 검토 시트: 열림 · 몇 번째 후보 · 저장한 후보 · 제목 입력 | 컴포넌트 안(`useState`, `card-review-sheet.tsx`) | 시트 하나에서만 쓰는 값이라서. 닫을 때 바뀐 게 있으면 `router.refresh()` | F-006 |
| 후보 하나의 내용(시트) | TanStack Query `useQuery`(`card-review-sheet.tsx`, 키 `["card", id]`) | 시트를 열 때 브라우저가 받는 서버 데이터라서. 자동 재시도 끔(실패 문구 + [다음 후보 보기]) | F-006 |
| 카드 상세: 받은 카드 · 입력 중인 제목 · 칸 답 | 컴포넌트 안(`useState`, `card-editor.tsx`) | 이 화면 하나에서만 쓰고, 저장 · 인용 빼기 응답(카드 전체)으로 바꿔 끼운다 | F-006 |
| 카드 저장 · 인용 빼기 · 지우기 · 후보 저장 · 버리기 | TanStack Query `useMutation`(`card-editor.tsx` · `card-review-sheet.tsx`) | 서버 수정이라서. 저장은 바뀐 칸만 차례로 보내고(실패하면 거기서 멈춤) 마지막에 제목 저장 | F-006 |
| 노션 연결 상태(설정 '연결' 칸) · 연결 뒤 돌아온 안내(`?notion=connected` · `?notion_error=`) | 서버 컴포넌트(`settings/page.tsx`, `lib/notion-data.ts` · `lib/notion-status.ts`) + 주소 | 처음 화면을 그릴 때 필요한 서버 데이터라서. 연결 결과는 콜백이 주소로 넘긴다. [연결 끊기]는 `useState`(진행 중 · 오류, `notion-connection-row.tsx`) + 성공 뒤 `router.refresh()` | F-005 |
| 기록 추가의 가져올 곳 탭 · 고른 노션 페이지 | 컴포넌트 안(`useState`, `import-records-dialog.tsx`) | 모달 하나에서만 쓰는 값이라서 | F-005 |
| 가져올 노션 페이지 목록 | TanStack Query `useQuery`(`import-records-dialog.tsx` NotionPicker, 키 `["notion", "pages"]`) + 가져온 뒤 무효화 | 모달을 열고 노션 탭을 고를 때 브라우저가 받는 서버 데이터라서. 가져온 뒤 '이미 가져옴'을 새로 받는다. 자동 재시도 끔, 1분은 그대로 쓰고 창 포커스 때 다시 받지 않음(노션 호출 줄이기, 1차 리뷰 R2). 모달이 사이드바에도 있어 QueryProvider를 회원 레이아웃 전체(사이드바 포함)로 올림 | F-005 |
| 지원 목록 · 지원 상세(공고 · 역량 · 매칭) | 서버 컴포넌트(`applications/page.tsx` · `applications/[id]/layout.tsx` · `[id]/analysis/page.tsx`, `lib/applications-data.ts`) | 처음 화면을 그릴 때 필요한 서버 데이터라서. 머리(layout)와 탭(page)이 같은 상세를 쓰므로 React `cache`로 요청 한 번에 한 번만 부른다 | F-007 |
| 공고 추가 모달: 열림 · 입력 칸 · 문항 줄 | 컴포넌트 안(`useState`, `add-application-dialog.tsx`) | 모달 하나에서만 쓰는 입력값이라서. 저장은 `useMutation`, 성공하면 `?analyze=1`로 분석 탭으로 이동 | F-007 |
| 분석 바로 시작 신호(`?analyze=1`) | 주소 | 모달 → 분석 탭으로 '방금 추가했음'을 넘기는 한 번짜리 신호. 시작한 뒤 주소에서 지워 새로 고쳐도 AI를 다시 부르지 않는다 | F-007 |
| ① 역량 뽑기 · ② 매칭(진행 중 · 오류) | TanStack Query `useMutation`(`posting-analysis.tsx`) + 성공 뒤 `router.refresh()` | 서버 수정이라서. ① 성공(역량 1개 이상)이면 ②를 이어서 부른다. ②만 실패하면 ① 결과(서버 컴포넌트가 다시 받음)는 그대로. 자동 재시도 끔 | F-007 |
| 고른 요구 역량(오른쪽 근거 칸) · 공고 원문 펼침 | 컴포넌트 안(`useState`, `posting-analysis.tsx` · `posting-aside.tsx`의 PostingText) | 이 화면 하나에서만 쓰는 표시 상태라서 | F-007 |
| 자소서 탭: 문항 · 초안 · 근거 | 처음은 서버 컴포넌트(`[id]/draft/page.tsx`, `lib/drafts-data.ts` — Suspense 안), 그 뒤 TanStack Query `useQuery`(`draft-workspace.tsx`, `initialData`) | 문장 하나를 적용할 때마다 서버가 version을 올려서, 응답을 바로 캐시에 넣어야(`setQueryData`) 다음 적용이 409가 나지 않는다. `router.refresh()`를 기다리면 그 사이 옛 version으로 보낸다. 다시 받기 실패는 한 번만 다시 시도(`retry: 1`)하고 알림 + [다시 불러오기]. '마지막 검사'는 서버 시각(`checked_at`, 저장 뒤엔 저장 시각) — 브라우저 시각을 쓰면 hydration이 어긋날 수 있어서 | F-008 |
| 초안 쓰기 · 문장 고치기 · 완료 · 문항 저장 · 카드 연결 | TanStack Query `useMutation`(`draft-workspace.tsx`) | 서버 수정이라서. 성공하면 응답을 캐시에 넣거나(고치기 · 완료 · 문항) 다시 받는다(초안 쓰기). 409 · 404면 다시 받는다. 부품에는 `RequestState`(진행 중 · 오류 · 실행 함수)만 내려 TanStack Query를 몰라도 되게 | F-008 |
| 고른 문항 · 고른 문장 · 고치는 문장 · 카드 연결 창 · 문항 고치기 입력 · 카드 검색어 | 컴포넌트 안(`useState`) | 이 화면 하나에서만 쓰는 표시 · 입력 상태라서 | F-008 |
| 머리의 '자동 저장됨 · 시각' | 자소서 탭이 채운 TanStack Query 캐시를 읽기만(`DraftHeaderActions`, `enabled: false`) — 브라우저에서만(hydration 불일치 방지) | 머리(layout)와 탭(page)이 같은 초안 데이터를 보므로 따로 부르지 않는다 | F-008 |
| 사이드바 접힘(자소서 탭) | 상태 없음 — CSS(`globals.css`의 `sidebar-open` 변형, 화면의 `data-collapse-sidebar`를 `:has()`로 봄) | F-008 메모의 Zustand 후보는 필요 없었다. 서버 렌더부터 접혀 깜빡임이 없다. Next 16이 숨겨 둔 앞 화면(`display: none`)은 뺀다 | F-008 |
| 지원 상태 바꾸기 · 공고 지우기 | TanStack Query `useMutation`(`application-header-actions.tsx`의 `ApplicationStatusSelect` · `DeleteApplicationButton` — 자리가 달라 따로, 오류도 각자 옆에) + `router.refresh()` · 목록으로 이동 | 서버 수정이라서 | F-007 |

### DB (D-008)
- 운영 · 개발 DB는 PostgreSQL(+ pgvector). 로컬은 레포 루트 `docker-compose.yml`의 `db` — PostgreSQL 17(pgvector/pgvector:pg17), `127.0.0.1:5432`(내 컴퓨터에서만), 계정은 루트 `.env`(커밋 안 함). 배포 DB 버전은 Q-012와 함께 맞춘다.
- 서버는 `DATABASE_URL`이 없으면 이유를 적은 오류로 시작하지 않는다(조용히 다른 DB로 넘어가지 않음).
- 테스트 DB는 `backend/tests/conftest.py` 한 곳에서 정한다: 기본은 테스트마다 임시 SQLite, `TEST_DATABASE_URL`을 주면 PostgreSQL **테스트 전용 DB**(`didim_test`, 컨테이너를 처음 만들 때 `docker/postgres-init`이 생성). 테스트가 테이블을 지웠다 만들기 때문에 DB 이름이 `_test`로 끝나지 않으면 멈춘다. 셸의 `DATABASE_URL`은 테스트에서 항상 덮어쓴다.
- 테이블 구조는 Alembic 버전 파일(`backend/migrations/versions/`)로만 바꾼다(D-015). 적용은 `alembic upgrade head`. 서버는 테이블을 만들지 않고, 시작할 때 DB 버전이 최신인지 확인해 아니면 실행할 명령을 적은 오류로 멈춘다(`app/db/schema_version.py` — DB 연결 안 됨 · 뒤처짐 · 코드보다 앞섬을 다른 오류로 안내). 테스트만 `create_all`을 쓰고, 버전 파일과 모델이 같은지는 `tests/test_migrations.py`가 확인한다.

### 디자인 토큰 (설계 원칙 7)
- `frontend/src/app/globals.css`의 `@theme`: 색(text · line · bg · primary · sub1 · status), 글자 크기(Pretendard 스케일), 라운드(Radius Default). 값은 디자인 원본에서 옮긴 것이고, 바꿀 때는 디자인 원본을 먼저 고친다.

### SEO (설계 원칙 8)
- 공통 정보: `frontend/src/lib/site.ts`(사이트 이름 · 설명 · 주소 · 공개/회원 경로)
- 제목: 루트 레이아웃의 템플릿 `%s | 디딤`, 페이지마다 `metadata.title` · `description`
- 검색 노출: 공개 페이지(`/`, `/login`)만. 회원 레이아웃 `(app)` · `(focus)`는 `noindex`(`MEMBER_ROBOTS`), `sitemap.xml`엔 공개 페이지만
- `robots.txt`는 `/api/`만 막는다. 회원 화면을 robots.txt로 막으면 검색 로봇이 페이지를 열지 않아 `noindex`를 못 읽고, 외부 링크가 있으면 주소만 색인될 수 있어서다. robots.txt는 누구나 볼 수 있는 파일이라 회원 경로를 적지 않는 것이 구조 노출 면에서도 낫다.
- robots.txt · noindex는 검색 노출 조절이지 접근 차단이 아니다. 회원 화면 접근 차단은 로그인(F-001)이 한다.
- 시맨틱: 레이아웃마다 `<main>` 하나, 화면마다 `<h1>` 하나(탭 화면은 `<h2>`), `<html lang="ko">`
- 서버 렌더링: App Router 서버 컴포넌트가 기본이라 HTML에 내용이 담겨 내려가요. 클라이언트 컴포넌트("use client")는 필요한 부분에만 써요.

### 원칙
- 데이터 분리: 모든 조회 · 벡터 검색에 사용자 ID 조건(D-004).
- AI 출력: 정해진 스키마로 받고, 형식이 틀리면 재시도 · 실패 처리.
- LLM에 보내는 범위 최소화: 필요한 조각만, 무엇을 보내는지 안내.
- 평가 가능하게: 매칭 · 근거 검사 결과를 로그로 남겨 평가 세트로 채점(D-005).
- 브라우저 → `/api/*` → Next rewrites → FastAPI 프록시는 기본 30초에 끊긴다. [문제 만들기]가 AI를 최대 180초 기다리므로 `next.config.ts`의 `experimental.proxyTimeout`을 200초로 둔다(F-004, 리뷰 때 확인).
- 오래 걸리는 처리(가져오기 · 초안 생성)는 진행 상태를 저장해서 나갔다 와도 이어 보기(IMP_01_002). 1주차 가져오기는 AI 호출이 없어 요청 한 번에 처리하고, 이어 보기 방식(백그라운드 작업 · 폴링 · 스트리밍)은 AI 단계를 붙일 때 정해요(F-002 설계 의도, Q-008).

최종 수정: 2026-11-11 · 관련: D-001, D-003, D-004, D-008, D-010
