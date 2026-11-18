import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { LandingPinnedScenes } from "@/components/landing-pinned-scenes";
import { SourceQuote } from "@/components/page-parts";
import { SLOT_LABELS } from "@/lib/card-slots";
import { STORY_SCENE } from "@/lib/landing";
import { CARD, CHIP, CHIP_WARNING, LANDING_SKIP_LINK } from "@/lib/ui-classes";

// 랜딩 스토리 '잡아내는 순간'(F-011 완료 기준 3 · 4, D-007, Figma 29:1658). 같은 초안의 두 문장(근거 있음 1 · 근거 없음 1)을
// ① 완성된 초안 → ② 근거 없는 문장에 ⚠ 밑줄 → ③ 원문 각주가 붙고 근거 없는 문장은 빠짐, 세 장면으로 보인다.
// 장면 글은 서버에서 그리고, 장면을 넘기는 것만 LandingPinnedScenes(클라이언트)가 한다.
export function LandingStory() {
  const { kept, dropped } = STORY_SCENE;
  return (
    <>
      <LandingPinnedScenes id="story" labelledBy="story-title" className="bg-bg-light">
        <header className="flex flex-col items-center gap-3 text-center">
          <h2 id="story-title" className="text-headline-1 font-semibold text-text-main">
            AI가 쓴 문장, 어디까지가 내 이야기일까요?
          </h2>
          <p className="text-title-4 text-text-sub">AI 초안에서 기록에 없는 문장을 잡아내는 과정을 세 장면으로 보여 드려요.</p>
          <a href="#story-end" className={LANDING_SKIP_LINK}>
            건너뛰기
          </a>
        </header>

        <ol className="grid gap-6 lg:grid-cols-3">
          <Scene number={1} title="완성된 AI 초안">
            <p className="text-title-4 font-normal text-text-main">
              {kept.text} {dropped.text}
            </p>
          </Scene>
          <Scene number={2} title="기록에 없는 문장에 밑줄">
            <p className="text-title-4 font-normal text-text-main">
              {kept.text} <span className="story-mark box-decoration-clone">{dropped.text}</span>
              <span className="ml-1 inline-flex items-center gap-1 align-middle">
                <Icon name="warning" size={16} className="text-warning-text" />
                <span className={CHIP_WARNING}>근거 없음</span>
              </span>
            </p>
          </Scene>
          <Scene number={3} title="원문 각주가 붙거나 빠짐">
            <p className="text-title-4 font-normal text-text-main">
              {kept.text}
              <span className={CHIP}>{kept.card}</span>
            </p>
            <p className="text-body-4 text-text-sub">근거 없는 문장 1개를 뺐어요</p>
            <SourceQuote quote={kept.quote} source={`카드 · ${kept.card} · ${SLOT_LABELS[kept.slot]} 칸`} />
          </Scene>
        </ol>
      </LandingPinnedScenes>
      <div id="story-end" />
    </>
  );
}

function Scene({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return (
    <li data-scene={number} className={`pinned-scene flex flex-col gap-4 ${CARD}`}>
      <h3 className="flex items-center gap-2 font-semibold">
        <span className="text-title-3 text-primary-text">{number}</span>
        <span className="text-title-4 text-text-main">{title}</span>
      </h3>
      {children}
    </li>
  );
}
