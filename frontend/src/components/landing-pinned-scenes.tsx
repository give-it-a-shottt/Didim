"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";

// 장면 수 — 이 컴포넌트를 쓰는 쪽(landing-story.tsx Scene · landing-sections.tsx FeatureCard)의 data-scene 1~3과 같아야 한다
const SCENE_COUNT = 3;
// 빠르게 스크롤해 장면을 건너뛰어도 한 칸씩 넘긴다 — 앞 장면이 반쯤 들어온 뒤 다음 장면(--landing-duration 600ms의 절반 남짓)
const STEP_INTERVAL_MS = 350;

/**
 * 랜딩 고정 구간(F-011, D-007 — 스토리 · 기능 두 곳)의 '지금 몇 번째 장면인가'만 정한다. 움직임은 globals.css 전환이 맡는다.
 * 스크롤 위치에 값을 그대로 묶으면 끊겨 보여서(사용자 피드백 2026-11-18), 진행률을 세 칸으로 나눠 목표 장면을 정하고
 * data-step을 목표까지 한 칸씩 옮긴다 — CSS가 장면마다 ease-out으로 넘긴다. 장면 글은 서버에서 그려 children으로 받고,
 * 고정되는 틀(landing-pinned-stage)과 진행 표시(점 SCENE_COUNT개)는 여기서 그려 두 구역이 같이 쓴다.
 * data-motion은 JS가 돈 뒤에만 붙는다 — JS가 없으면 세 장면이 나란히 다 보이는 정지 화면 그대로다.
 */
export function LandingPinnedScenes({
  id,
  labelledBy,
  className = "",
  children,
}: {
  id: string;
  labelledBy: string;
  className?: string;
  children: ReactNode;
}) {
  const sectionRef = useRef<HTMLElement>(null);
  const [step, setStep] = useState(SCENE_COUNT);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;
    // 이 속성이 붙어야 CSS가 250vh 고정 구간을 만든다(넓은 화면 · 움직임 줄이기 꺼짐일 때만). 높이가 바뀐 다음 프레임에 잰다.
    section.dataset.motion = "";
    let frame = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let shown = SCENE_COUNT; // 지금 data-step(타이머 안에서 최신 값을 보려고 따로 든다)
    let target = SCENE_COUNT;

    const advance = () => {
      timer = undefined;
      if (shown === target) return;
      shown += shown < target ? 1 : -1;
      setStep(shown);
      if (shown !== target) timer = setTimeout(advance, STEP_INTERVAL_MS);
    };
    const measure = () => {
      frame = 0;
      const { top, height } = section.getBoundingClientRect();
      const scrollable = height - window.innerHeight;
      // 고정 구간이 아니면(좁은 화면 · 움직임 줄이기 — CSS가 높이를 늘리지 않음) 다 보이는 마지막 장면으로 바로 둔다
      if (scrollable <= 0) {
        if (timer !== undefined) clearTimeout(timer);
        timer = undefined;
        target = shown = SCENE_COUNT;
        setStep(SCENE_COUNT);
        return;
      }
      const progress = Math.min(Math.max(-top / scrollable, 0), 1);
      target = Math.min(SCENE_COUNT, Math.floor(progress * SCENE_COUNT) + 1);
      if (timer === undefined) advance();
    };
    const schedule = () => {
      if (frame === 0) frame = requestAnimationFrame(measure);
    };
    schedule();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame !== 0) cancelAnimationFrame(frame);
      if (timer !== undefined) clearTimeout(timer);
      delete section.dataset.motion;
    };
  }, []);

  return (
    <section ref={sectionRef} id={id} aria-labelledby={labelledBy} data-step={step} className={`landing-pinned ${className}`}>
      <div className="landing-pinned-stage w-full px-5">
        <div className="mx-auto flex w-full max-w-300 flex-col gap-12 py-20 lg:py-0">
          {children}
          {/* 지금 몇 번째 장면인지 — 움직일 때만 앞 장면까지 진하게(globals.css), 정지 화면에서는 다 진하게 */}
          <ol aria-hidden="true" className="hidden justify-center gap-2 lg:flex">
            {Array.from({ length: SCENE_COUNT }, (_, index) => (
              <li key={index} className="pinned-step h-1 w-10 rounded-tag bg-primary-default" />
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
