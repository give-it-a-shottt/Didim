"use client";

import { type CSSProperties, type ReactNode, useEffect, useRef } from "react";

/**
 * 랜딩 아래 구역의 제목 · 목록 한 칸을 화면에 들어올 때 떠오르게 한다(F-011, didim-design.md 5장 '아래 섹션':
 * opacity + translateY 16px). 움직임은 globals.css 전환(transition)이 맡고, 여기서는 data-reveal만 바꾼다
 * — React 상태가 아니라 DOM 속성이라 다시 그리지 않는다. index만큼 늦게 떠올라 칸이 차례로 들어온다.
 * JS가 없으면 속성이 붙지 않아 처음부터 보이고, 움직임 줄이기면 CSS가 전환을 끈다.
 */
export function LandingReveal({
  as: Tag = "div",
  index = 0,
  className,
  children,
}: {
  as?: "div" | "li";
  index?: number;
  className?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement & HTMLLIElement>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    element.dataset.reveal = "pending";
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          element.dataset.reveal = "shown";
          observer.disconnect(); // 한 번 떠오르면 끝 — 위로 되돌아가도 다시 숨기지 않는다
        }
      },
      // 칸이 화면 아래 끝에 걸리자마자가 아니라, 화면 아래 15%를 넘어 들어와 눈에 보일 때 시작한다
      { threshold: 0.2, rootMargin: "0px 0px -15% 0px" },
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      delete element.dataset.reveal;
    };
  }, []);

  return (
    <Tag ref={ref} className={className} style={{ "--reveal-index": index } as CSSProperties}>
      {children}
    </Tag>
  );
}
