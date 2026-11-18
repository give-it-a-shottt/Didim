import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { LandingPinnedScenes } from "@/components/landing-pinned-scenes";
import { LandingReveal } from "@/components/landing-reveal";
import { SourceQuote } from "@/components/page-parts";
import { CARD_SLOTS, SLOT_LABELS } from "@/lib/card-slots";
import { COUPON_ACTION_SENTENCE, REVIEW_QUOTE } from "@/lib/landing";
import { CARD, CHIP, LANDING_SKIP_LINK } from "@/lib/ui-classes";

// 랜딩 아래쪽 두 구역(F-011, Figma 29:1739 '기능' · 29:1757 '평가 방법'). 위 메뉴의 [기능] · [평가 방법]이 id로 옮겨 온다.
// 예시 인용 · 문장은 샘플 계정의 실제 결과(lib/landing.ts) — Figma의 Accio 예시는 디자인용이라 쓰지 않는다.
// 기능 카드는 스토리와 같은 고정 구간 — 화면에 붙은 채 스크롤하면 한 장씩 들어온다(사용자 요청 2026-11-18).
// 평가 방법의 제목 · 줄은 화면에 들어올 때 차례로 떠오른다(LandingReveal). 둘 다 움직임 줄이기 · 좁은 화면이면 그대로 보임.

/** '기록 하나가 세 번 쓰여요' — 복습 · 경험 카드 · 근거 달린 자소서. */
export function LandingFeatures() {
  return (
    <>
      <LandingPinnedScenes id="features" labelledBy="features-title">
        <header className="flex flex-col items-start gap-3">
          <h2 id="features-title" className="text-headline-1 font-semibold text-text-main">
            기록 하나가 세 번 쓰여요
          </h2>
          <a href="#features-end" className={LANDING_SKIP_LINK}>
            건너뛰기
          </a>
        </header>
        <ul className="grid gap-6 lg:grid-cols-3">
          <FeatureCard scene={1} title="복습" body="올린 노트에서 객관식 · OX 문제를 만들고, 틀린 개념은 간격을 좁혀 다시 내요.">
            <SourceQuote quote={REVIEW_QUOTE.quote} source={`해설의 근거 · 노트 · ${REVIEW_QUOTE.note}`} />
          </FeatureCard>
          <FeatureCard
            scene={2}
            title="경험 카드"
            body="회고 노트에서 상황 · 과제 · 행동 · 결과 후보를 찾고, 빈칸은 질문으로만 채우게 도와요."
          >
            {/* 칸 네 개 — 기록에 없는 칸(예: 결과)은 AI가 채우지 않고 빈칸으로 남겨 경고색으로 보인다(D-003) */}
            <ul aria-label="경험 카드 칸 — 결과 칸은 빈칸" className="flex gap-1">
              {CARD_SLOTS.map((slot) => (
                <li
                  key={slot}
                  className={`rounded-button border px-2 py-1 text-body-4 ${
                    slot === "result" ? "border-warning-text text-warning-text" : "border-line-light bg-bg-regular text-text-sub"
                  }`}
                >
                  {SLOT_LABELS[slot]}
                </li>
              ))}
            </ul>
          </FeatureCard>
          <FeatureCard
            scene={3}
            title="근거 달린 자소서"
            body="공고의 요구 역량에 맞는 카드를 고르고, 문장마다 근거 칩을 붙여요. 근거 없는 문장은 표시해요."
          >
            <p className="text-body-2 text-text-main">
              {COUPON_ACTION_SENTENCE.text}
              <span className={CHIP}>{COUPON_ACTION_SENTENCE.card}</span>
            </p>
          </FeatureCard>
        </ul>
      </LandingPinnedScenes>
      <div id="features-end" />
    </>
  );
}

/** 카드 한 칸: 제목 → 설명 → 예시(사용자 지정 2026-11-18). scene = 고정 구간에서 들어오는 차례(1~3). */
function FeatureCard({ scene, title, body, children }: { scene: number; title: string; body: string; children: ReactNode }) {
  return (
    <li data-scene={scene} className={`pinned-scene flex flex-col gap-3 ${CARD}`}>
      <h3 className="text-title-3 font-semibold text-text-main">{title}</h3>
      <p className="text-body-1 text-text-sub">{body}</p>
      <div className="mt-1">{children}</div>
    </li>
  );
}

// 평가 방법(Figma 29:1757). 숫자는 실제 평가 세트와 같다 — 심은 경험(카드) 20 · 공고 10(backend/eval, F-010).
const HOW_MEASURED = [
  "가상 카드 20장 · 공고 10개 — 공고마다 맞는 카드를 먼저 정해 둠",
  "초안에 지어낸 문장을 일부러 섞고, 검사기가 몇 개를 잡는지 셈",
  "고칠 때마다 같은 시험지로 다시 채점해 리포트에 기록",
] as const;

/** '수치는 어떻게 쟀나요'. */
export function LandingHowMeasured() {
  return (
    <section id="how-measured" aria-labelledby="how-measured-title" className="bg-bg-light px-5 py-20 lg:py-24">
      <div className="mx-auto grid max-w-300 gap-8 lg:grid-cols-2 lg:gap-12">
        <LandingReveal className="flex flex-col gap-3">
          <h2 id="how-measured-title" className="text-headline-1 font-semibold text-text-main">
            수치는 어떻게 쟀나요
          </h2>
          <p className="text-title-4 font-normal text-text-sub">
            정답을 미리 심어 둔 가상 지원자 데이터로 재요. 사람이 판정해야 하는 수치는 판정이 끝날 때까지 ‘판정 대기’로 보여요.
          </p>
        </LandingReveal>
        <ul className="flex flex-col gap-3">
          {HOW_MEASURED.map((item, index) => (
            <LandingReveal as="li" key={item} index={index} className="flex items-start gap-2 text-body-1 text-text-main">
              <Icon name="check" size={20} className="shrink-0 text-primary-default" />
              {item}
            </LandingReveal>
          ))}
        </ul>
      </div>
    </section>
  );
}
