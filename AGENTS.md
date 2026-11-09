# AGENTS.md — 디딤 (Didim)

이 레포의 규칙은 한 곳, [CLAUDE.md](CLAUDE.md)에만 둔다. 어떤 AI 에이전트(Claude Code, Antigravity · Gemini, Codex, Cursor 등)든 작업을 시작하기 전에 아래 순서로 읽고 그대로 따른다.

1. [CLAUDE.md](CLAUDE.md) — 작업 규칙, 리뷰 기준, 설계 원칙 (이름이 CLAUDE지만 모든 에이전트에 적용)
2. [Admin_Docs/START_HERE.md](Admin_Docs/START_HERE.md) — 한 장 요약, 결정 · 기능 목록
3. [Admin_Docs/STATUS.md](Admin_Docs/STATUS.md) — 지금 어디까지 왔나
4. [Admin_Docs/OPEN_QUESTIONS.md](Admin_Docs/OPEN_QUESTIONS.md) — 아직 결정 못 한 것([열림])

- 리뷰 · 문서 절차는 admin-docs-review 스킬을 따른다. 스킬이 없는 에이전트는 [Admin_Docs/_system/rules.md](Admin_Docs/_system/rules.md)와 [Admin_Docs/_system/reviewers/](Admin_Docs/_system/reviewers/)를 따른다. 지정 리뷰어 모델을 쓸 수 없으면 지금 쓰는 모델로 돌리고 SUMMARY에 적는다.
- 프론트 코드는 [frontend/AGENTS.md](frontend/AGENTS.md)(Next.js 16 안내)도 따른다.
- 규칙을 이 파일에 복사하지 않는다. 바꿀 것은 CLAUDE.md에서 바꾼다.
