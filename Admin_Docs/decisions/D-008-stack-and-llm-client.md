# D-008 기술 스택과 LLM 호출 구조

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 스택은 사용자 확인(2026-11-05). LLM 교체 구조는 D-014로 정했고 F-014로 구현했어요(사용자 확인, 2026-11-10).
무엇을: 화면은 Next.js, 서버는 FastAPI, 데이터는 PostgreSQL 하나에 담고, 뜻이 비슷한 글 검색도 같은 DB(pgvector)에서 해요.
왜: 이미 쓰던 스택이라 새로 배울 것이 줄고, DB를 하나로 두면 운영이 단순해요.

## 개발자 상세

### 결정
- Frontend: Next.js · Backend: FastAPI(Python) · DB: PostgreSQL + pgvector
- 추가(사용자 선택, 2026-11-08): Frontend는 TypeScript + Tailwind CSS, 프론트 배포는 Vercel. FastAPI 배포 위치는 Q-012, 레포 구조는 Q-013에서 정해요.
- 세팅된 버전(2026-11-08): Next.js 16.4.5 · React 19.3 · Tailwind 4 · TypeScript 5 / Python 3.13 · FastAPI 0.162 (uv로 관리)
- RAG: 기록을 나누기(청크) → 임베딩 → 검색. 키워드 검색(BM25)과 벡터 검색을 섞는 방향은 2주차에 비교해서 정한다.

### LLM 결정 → [D-014](D-014-llm-exaone-swappable.md) (Q-001 닫힘), 구현은 [F-014](../features/F-014-llm-client/feature.md), 임베딩은 Q-002

### 이전 메모 (AI 제안)
- LLM 클라이언트를 인터페이스 하나로 묶고 환경변수로 mock ↔ real을 바꾸는 구조. 마에스트로에서 헤이유미 API에 썼던 방식과 같아서, 키 없이 1주차부터 개발 · 테스트하고 발표 중 API가 멈춰도 버틸 수 있어요.
- 어떤 LLM · 임베딩 모델을 쓸지.

최종 수정: 2026-11-10 · 관련: F-001, F-003, F-014, D-014
