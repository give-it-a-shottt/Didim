# T-003 스크립트 출력이 Windows 기본 인코딩(cp949)에서 깨지거나 멈춤

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 해결했어요(2026-11-10).
무슨 문제였나: AI 연결 확인 스크립트(`llm_ping`)가 결과를 화면에 찍다가 오류로 멈췄어요. Windows는 출력을 다른 프로그램으로 넘길 때(파이프) 글자를 옛 한글 방식(cp949)으로 바꾸는데, 이 방식에 없는 글자(`—`)가 섞여 있었어요. 같은 이유로, 한글이 든 코드를 명령 줄에 직접 붙여 넣어 파일을 고치려다 글자가 깨져서 수정이 적용되지 않은 일도 있었어요.
어떻게 해결했나: 스크립트가 시작할 때 출력 방식을 UTF-8로 고정하고, 출력 문구에서 특수 문자를 뺐어요.

## 개발자 상세
- 증상:
  - `uv run --env-file .env python -m scripts.llm_ping mock` → `UnicodeEncodeError: 'cp949' codec can't encode character '—'` (print 줄에서 멈춤). 한글 오류 문구도 깨져 보임.
  - 셸 heredoc(`python - <<'EOF'`)에 한글이 든 파이썬 코드를 넣어 파일을 고치려 하자, 한글 문자열이 깨져 `assert old in s`가 실패하고 수정이 적용되지 않음.
- 원인:
  - Windows에서 파이썬은 stdout · stdin이 터미널이 아니라 파이프일 때 시스템 기본 인코딩(한국어 Windows는 cp949)을 쓴다. cp949에 없는 글자(`—`, `×` 등)는 인코딩 오류가 난다.
  - heredoc으로 넘긴 소스도 stdin이라 cp949로 읽혀서, UTF-8로 쓴 한글이 다른 글자가 된다.
  - 테스트(pytest)는 출력을 직접 찍지 않아 드러나지 않았고, 손으로 돌리는 스크립트에서 처음 드러남.
- 해결:
  - `backend/scripts/llm_ping.py`의 `main()` 시작에서 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.
  - 출력 문구의 `—`를 `:`로 바꿈.
- 재발 방지:
  - 손으로 돌리는 스크립트는 시작할 때 stdout을 UTF-8로 고정한다.
  - 셸에서 한 줄짜리 파이썬을 돌릴 때는 `python -X utf8` 또는 `PYTHONIOENCODING=utf-8`을 붙인다.
  - 한글이 든 코드 수정은 heredoc 스크립트가 아니라 편집 도구로 한다(파일은 항상 `encoding="utf-8"`로 읽고 쓴다).
  - 오류 문구가 깨져 보이면 내용 문제가 아니라 인코딩 문제부터 의심한다.
- 관련: F-014 구현 중 발견, [backend/scripts/llm_ping.py](../../backend/scripts/llm_ping.py)

최종 수정: 2026-11-10 · 관련: F-014
