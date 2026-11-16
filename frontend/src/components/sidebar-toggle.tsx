"use client";

// 사이드바 접기 · 펴기 버튼. 상태는 <html data-sidebar-collapsed>(lib/sidebar-state.ts) — 여기서는 그 속성과 localStorage만 바꾼다.
// 넓은 화면(lg 이상)에서만 보이고, 자소서 탭처럼 늘 접히는 화면에서는 숨긴다(globals.css의 sidebar-togglable 변형, 사용자 선택).
import { useLayoutEffect, useSyncExternalStore } from "react";
import { Icon } from "@/components/icon";
import { SidebarTooltip } from "@/components/sidebar-nav";
import {
  SIDEBAR_CHANGE_EVENT,
  SIDEBAR_COLLAPSED_ATTR,
  SIDEBAR_COLLAPSED_VALUE,
  SIDEBAR_STORAGE_KEY,
} from "@/lib/sidebar-state";
import { FOCUS_RING } from "@/lib/ui-classes";

function subscribe(onChange: () => void) {
  window.addEventListener(SIDEBAR_CHANGE_EVENT, onChange);
  return () => window.removeEventListener(SIDEBAR_CHANGE_EVENT, onChange);
}

const isCollapsed = () => document.documentElement.hasAttribute(SIDEBAR_COLLAPSED_ATTR);

/** 저장한 값. 저장소를 못 읽으면 null — '값 없음(펼침)'과 구분해야 지금 화면의 접힘을 되돌리지 않는다(F-013 5차 리뷰 R3). */
function storedCollapsed(): boolean | null {
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === SIDEBAR_COLLAPSED_VALUE;
  } catch {
    return null;
  }
}

function applyCollapsed(collapsed: boolean) {
  document.documentElement.toggleAttribute(SIDEBAR_COLLAPSED_ATTR, collapsed);
  window.dispatchEvent(new Event(SIDEBAR_CHANGE_EVENT));
}

export function SidebarToggle() {
  // 서버는 펼침으로 그리고, 브라우저에서는 <html> 속성을 따른다(서버 · 브라우저가 다른 값 — useSyncExternalStore)
  const collapsed = useSyncExternalStore(subscribe, isCollapsed, () => false);

  // 개발 모드(Strict Mode)는 다시 마운트할 때 <html> 속성을 JSX 것만 남기고 지운다 — 저장한 값으로 다시 붙인다(운영에서는 변화 없음).
  // 저장소를 못 읽으면(null) 건드리지 않는다 — 이번 방문에서 접은 상태를 그대로 둔다.
  useLayoutEffect(() => {
    const stored = storedCollapsed();
    if (stored !== null && stored !== isCollapsed()) applyCollapsed(stored);
  }, []);

  const toggle = () => {
    const next = !isCollapsed();
    applyCollapsed(next);
    try {
      if (next) localStorage.setItem(SIDEBAR_STORAGE_KEY, SIDEBAR_COLLAPSED_VALUE);
      else localStorage.removeItem(SIDEBAR_STORAGE_KEY);
    } catch {
      // 기억만 못 할 뿐 접기 · 펴기는 된다
    }
  };

  const label = collapsed ? "사이드바 펼치기" : "사이드바 접기";
  return (
    <div className="group relative hidden sidebar-togglable:block">
      <button
        type="button"
        onClick={toggle}
        aria-label={label}
        aria-expanded={!collapsed}
        className={`flex size-8 items-center justify-center rounded-button text-icon-sub hover:bg-bg-hover ${FOCUS_RING}`}
      >
        {/* 방향은 CSS가 <html> 속성을 직접 본다 — 접힌 채 새로 고침해도 하이드레이션 전부터 맞는 방향(5차 리뷰 R2) */}
        <Icon name="caret-left" size={20} className="sidebar-collapsed:rotate-180" />
      </button>
      <SidebarTooltip label={label} />
    </div>
  );
}
