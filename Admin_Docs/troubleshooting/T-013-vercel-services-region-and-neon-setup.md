# T-013 첫 배포: vercel.json의 지역 설정이 Services에서 먹지 않아 함수가 미국에 있었다 (+ Neon 연결 때 겪은 함정)

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 해결했어요(2026-11-19). 운영 주소 `https://didim-gamma.vercel.app`.
무슨 문제였나: 레포 맨 위 `vercel.json`에 함수 지역을 싱가포르(`sin1`)로 적었는데, Vercel Services 방식에서는 이 값이 적용되지 않았어요. 그래서 함수는 미국에서 돌고 DB(Neon)는 싱가포르에 있어, DB에 물어볼 때마다 태평양을 오갔어요. 첫 화면 평가 수치가 늦게 뜨는 것으로 처음 드러났어요.
어떻게 해결했나: Vercel 대시보드 Settings → Functions에서 Function Region을 Singapore(sin1)로 고르고 다시 배포했어요. 응답 머리말 `x-vercel-id`가 `icn1::sin1::…`(서울 입구 → 싱가포르 함수)로 바뀐 것으로 확인했어요.
같이 겪은 함정: ① Neon 지역을 Singapore로 적었는데 미국(Ohio)으로 만들어짐 ② 연결 때 환경변수 이름 앞부분(Prefix) ③ 환경변수를 넣기 전 배포를 보고 "DATABASE_URL이 비어 있어요" ④ 직접 주소를 복사할 때 따옴표까지 들어감 — 모두 아래에 적어요.

## 개발자 상세
- 증상(지역): 배포는 성공했고 기능도 됐지만 첫 화면 평가 수치 칸(백엔드 `/api/report`를 부름)이 늦게 떴다. 대시보드 Settings → Functions의 Function Region이 미국으로 되어 있었다(`vercel.json`의 `"regions": ["sin1"]`과 다름).
- 원인(지역): Services(Beta) 방식에서는 맨 위 `vercel.json`의 `regions`가 함수 지역에 반영되지 않았다(D-033에서 '배포 때 확인'으로 남겨 둔 항목). 운영은 NullPool이라 요청마다 DB에 새로 연결해서, 함수 · DB 지역이 다르면 연결 · 쿼리마다 왕복이 붙는다(D-034).
- 해결(지역): 대시보드 Function Region = Singapore(sin1) → Redeploy. 확인: `curl -sD - https://didim-gamma.vercel.app/api/health` → `X-Vercel-Id: icn1::sin1::…`. 앞(`icn1`)은 요청이 들어온 입구(서울), 가운데(`sin1`)가 함수가 돈 곳이다. 화면(`/`)은 미리 그려 둔 쪽이라 `icn1::…`만 보인다.
- `vercel.json`의 `regions`는 그대로 둔다(테스트 `test_deploy_config.py`가 sin1을 고정 — 의도 기록용). 실제 값은 대시보드가 정한다는 것을 체크리스트 4에 적었다.

### 같이 겪은 함정
1. **Neon이 미국(Ohio)에 만들어짐** — Vercel Storage → Neon 설치 화면의 Region 칸에 'Singapore (Southeast)'가 보였는데, 만든 DB의 Region은 'AWS US East 2 (Ohio)'였다. 칸에 검색어만 들어가고 목록 항목을 고르지 않은 것으로 보인다. → DB를 지우고 다시 만들 때 ▾를 눌러 목록에서 Singapore를 직접 클릭, 만든 직후 Storage → DB → Region이 'AWS Asia Pacific 1 (Singapore)'인지 확인.
2. **Prefix 칸** — 연결 화면의 Custom Prefix 칸에는 회색 예시 `STORAGE`가 보이고 뒤에 `_URL`이 붙는다. 디딤은 `DATABASE_URL`을 읽으므로 `DATABASE`를 직접 입력했다(비워 두면 어떤 이름이 되는지는 확인하지 않음). Environments는 Production만.
3. **`DatabaseConfigError: 환경변수 DATABASE_URL이 비어 있어요` → 500 `FUNCTION_INVOCATION_FAILED`** — 변수는 Production에 있었는데, 오류는 환경변수를 넣기 전 첫 배포(운영 설정이 없어 허용 목록 검사를 지나쳐 DB 확인에서 멈춤)에서 난 것이었다. Redeploy가 끝나 Ready · Current가 된 뒤 `/api/health` → `{"status":"ok"}`. 환경변수는 새 배포부터 반영되고, 주소가 어느 배포를 가리키는지(Current)를 먼저 본다.
4. **직접 주소 형식 오류** — 마이그레이션 전 호스트 확인 명령이 `sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL from given URL string`. Storage의 `.env.local` 탭은 `DATABASE_URL_UNPOOLED="postgresql://…"`처럼 이름 · 따옴표가 붙어 있어서, 값만(따옴표 안쪽, `postgresql://`부터) 복사해야 한다.
5. **비밀값 노출** — 확인하다 직접 주소 전체(비밀번호 포함)가 대화에 붙여 넣어졌다. 그 DB(위 1의 Ohio DB)를 지워 비밀번호를 무효로 하고 싱가포르로 새로 만들었다. 체크리스트의 확인은 '호스트만 출력'하는 명령으로 하고, 주소 전체는 어디에도 붙여 넣지 않는다.

### 재발 방지
- 설정 파일에 적은 값이 실제로 먹었는지는 배포 결과(대시보드 · 응답 머리말)로 확인한다. 함수 지역은 `x-vercel-id`의 가운데 값.
- 외부 콘솔에서 고른 값(지역 · Prefix)은 만든 직후 결과 화면에서 다시 본다.
- 체크리스트 1 · 4에 위 내용을 넣었다([overview/deployment.md](../overview/deployment.md)).

최종 수정: 2026-11-19 · 관련: F-016, D-033, D-034
