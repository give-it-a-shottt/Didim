# T-011 React의 onTransitionCancel은 propertyName이 비어 있고, 펼치는 중 접으면 '펼치기 취소' 신호가 온다

## 한눈에 보기 (코드 몰라도 OK)
상태: [통과] 해결했어요(2026-11-17). 테스트가 찾아 줬어요.
무슨 문제였나: 공고 원문을 부드럽게 접으려고 "접는 움직임이 끝나면 짧은 글로 바꾸기"를 넣었어요. 움직임이 중간에 끊길 때도 끝내려고 '취소 신호'도 받게 했는데, 그 신호 처리가 한 번도 동작하지 않았어요. 고치고 나니 이번엔 펼치는 도중에 접으면 바로 짧은 글이 돼 버렸어요.
어떻게 해결했나: 취소 신호는 어느 움직임이 끊긴 건지 구별하기 어려워 쓰지 않기로 했어요. "끝 신호 + 안전 타이머(움직임 시간 + 0.1초)" 두 가지로만 마무리해요.

## 개발자 상세
- 증상 1: `onTransitionCancel={(event) => { if (event.propertyName === "max-height" && …) … }}`가 실행되지 않음. 테스트에서 `transitioncancel`(propertyName max-height)을 보내도 `data-state`가 150ms 안에 안 바뀜. tsc는 통과(@types/react는 `onTransitionCancel`에 TransitionEvent 타입을 줌).
- 원인 1: Next 16에 묶인 react-dom 19.3(`next/dist/compiled/react-dom/cjs/react-dom-client.production.js`)은 `transitioncancel`을 등록(`registerSimpleEvent(TRANSITION_CANCEL, "onTransitionCancel")`)하지만, 합성 이벤트를 만들 때 `TRANSITION_END`만 `SyntheticTransitionEvent`로 감싸고 나머지는 일반 `SyntheticEvent`로 넘김 → `event.propertyName`이 undefined. `event.nativeEvent.propertyName`에는 값이 있다.
- 증상 2: nativeEvent로 고치자, 펼친 직후(펼치는 전환이 아직 진행 중) [원문 접기]를 누르면 곧바로 짧은 글이 됨(테스트 ① 간헐 실패).
- 원인 2: 진행 중인 전환의 값을 바꾸면 브라우저는 그 전환(펼치기)을 취소하고 `transitioncancel`을 보낸다. 같은 속성(max-height)이라 '접기 끝'과 구별이 안 됨. 또 펼치는 도중 접으면 브라우저가 진행된 만큼만 짧게 되돌려 끝 신호가 금방 온다(정상).
- 해결: `onTransitionCancel`을 없애고 `onTransitionEnd`(max-height) + 안전 타이머(`getComputedStyle`로 읽은 전환 시간 + `COLLAPSE_FALLBACK_SLACK_MS` 100ms)로 마무리. 다시 펼치거나 화면을 떠나면 타이머를 지운다. 전환 시간이 0(움직임 줄이기)이면 바로 바꾼다. 원문 요소에 `data-state`(full · short)를 달아 테스트가 직접 확인 — `frontend/src/components/posting-aside.tsx` PostingText, `frontend/tests/applications.spec.ts` '공고 원문' 테스트(8회 반복 통과).
- 재발 방지: React에서 `onTransitionEnd` 말고 다른 전환 · 애니메이션 이벤트의 필드를 읽을 때는 `event.nativeEvent`에서 읽는다. 취소 신호로 상태를 바꾸지 않는다(어느 전환이 끊겼는지 모름) — 끝 신호 + 안전 타이머로. 전환 테스트는 클래스가 아니라 상태 표시(data-state)를 보고, 실제 전환을 끄고(`transitionProperty: none`) 신호만 보내 갈래를 따로 증명한다.

최종 수정: 2026-11-17 · 관련: F-007, F-008(11 · 12차 리뷰)
