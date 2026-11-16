// 사이드바 접기 · 펴기(사용자 요청 2026-11-16). 상태는 <html data-sidebar-collapsed> 속성 하나 — CSS(globals.css의
// sidebar-open 변형)가 이 속성을 보고 접는다. 같은 브라우저에서 기억하려고 localStorage에 남긴다(사용자 선택).
// 서버는 localStorage를 못 읽으므로 루트 레이아웃 <head>의 인라인 스크립트가 첫 화면 전에 속성을 붙인다(깜빡임 없음 —
// Next 16 문서 'Preventing Flash'). 서버 컴포넌트(layout.tsx)도 가져다 쓰므로 이 파일에는 클라이언트 전용 코드를 두지 않는다.

export const SIDEBAR_STORAGE_KEY = "didim:sidebar";
export const SIDEBAR_COLLAPSED_VALUE = "collapsed";
export const SIDEBAR_COLLAPSED_ATTR = "data-sidebar-collapsed";
/** 버튼이 바꿀 때 알리는 이벤트 — 버튼의 이름(접기/펼치기)이 속성을 따라가게 */
export const SIDEBAR_CHANGE_EVENT = "didim:sidebar-change";

export const SIDEBAR_INIT_SCRIPT = `(function(){try{if(localStorage.getItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)})===${JSON.stringify(SIDEBAR_COLLAPSED_VALUE)})document.documentElement.setAttribute(${JSON.stringify(SIDEBAR_COLLAPSED_ATTR)},"")}catch(e){}})()`;
