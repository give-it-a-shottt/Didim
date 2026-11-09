# T-001 끈 줄 알았던 서버가 남아서 예전 빌드로 확인할 뻔함

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 해결했어요(2026-11-09).
무슨 문제였나: 확인용으로 띄운 화면 서버(next start)를 끈 줄 알았는데 실제로는 살아 있었어요. 새로 빌드한 뒤 확인했더니, 남은 서버가 예전 결과(고치기 전 robots.txt)를 보여 줘서 "안 고쳐졌다"로 잘못 볼 뻔했어요.
어떻게 해결했나: 그 포트를 잡고 있는 프로세스를 찾아 직접 끄고, 새 서버로 다시 확인했어요. 이제 서버를 끌 때는 남은 프로세스까지 확인해요.

## 개발자 상세
- 증상: 새 `next start --port 3002`가 `EADDRINUSE: address already in use :::3002`로 실패. 그런데 `curl localhost:3002/robots.txt`는 응답했고 내용이 수정 전 그대로였음.
- 원인: Claude Code에서 백그라운드로 띄운 `npx next start`를 작업 중지(TaskStop)로 멈추면 바깥 셸만 끝나고, Windows에서는 자식 `node.exe`(next start)가 남아 포트를 계속 잡고 있었음. 남은 서버는 이전 빌드를 메모리에 들고 응답.
- 해결: `netstat -ano`로 3002 포트의 PID 확인 → PowerShell `Get-CimInstance Win32_Process`로 명령줄이 `...Didim\frontend\...next start --port 3002`인지 확인 → `Stop-Process`로 종료 → 다시 `next start` 후 확인.
- 재발 방지:
  - 확인용 서버를 끈 뒤 `Get-CimInstance Win32_Process -Filter "Name='node.exe'"`에서 명령줄에 `Didim`과 `next start`가 들어간 프로세스가 없는지 확인한다.
  - 서버를 띄울 때 "포트 사용 중(EADDRINUSE)" 실패가 나면, 그 뒤의 확인 결과는 믿지 않는다(다른 서버가 응답한 것일 수 있음).
  - 확인 전에 바뀐 내용(예: robots.txt)을 하나 골라 새 빌드가 응답하는지 먼저 본다.
- 관련: F-013 3차 확인

최종 수정: 2026-11-09 · 관련: F-013
