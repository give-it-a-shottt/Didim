import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { LandingDraftPreview } from "@/components/landing-draft-preview";
import { LandingFeatures, LandingHowMeasured } from "@/components/landing-sections";
import { LandingStory } from "@/components/landing-story";
import { getCurrentUserOrNull } from "@/lib/auth";
import { heroDataSize, heroMetrics } from "@/lib/landing";
import { runDate } from "@/lib/report";
import { getReportRuns } from "@/lib/report-data";
import { SITE_NAME } from "@/lib/site";
import { BADGE_LINE, FOCUS_RING, PRIMARY_BUTTON_L, SECONDARY_BUTTON_L, TEXT_BUTTON } from "@/lib/ui-classes";

// LND_01_001 랜딩(F-011, D-007). 배치 · 문구는 Figma 디딤 랜딩(29:1373). 공개 · 검색 노출(sitemap의 "/").
// 위 메뉴 → 첫 화면(채용 담당자 30초 요약: 헤드라인 · CTA · 평가 수치 · 자소서 화면) → 스토리 세 장면 → 기능 → 평가 방법 → 마지막 CTA.
// 정적인 부분은 미리 그려 두고, 요청마다 달라지는 것(로그인 여부 · 평가 수치)만 Suspense 안에서 읽는다
// (cacheComponents — 쿠키 · 백엔드 요청은 Suspense 밖에서 읽을 수 없음).
export const metadata: Metadata = {
  title: { absolute: `${SITE_NAME} — 문장마다 근거가 달린 자소서` },
  description:
    "디딤은 지원자의 공부 기록과 프로젝트 회고에서만 자소서 문장을 만들고, 기록에 없는 문장에는 밑줄을 그어요. 퀴즈 복습 · 경험 카드 · 면접 연습까지 이어져요.",
};

// GNB 메뉴 한 칸(Figma GNB Menu Item: 16 SemiBold, Hover = 글자색 sub)
// 전환은 기본 상태에 둔다 — 올릴 때도 뗄 때도 같은 속도(사용자 규칙 2026-11-17)
const MENU_ITEM = `rounded-tag text-title-4 font-semibold text-text-main transition-colors duration-(--motion-duration) ease-motion hover:text-text-sub ${FOCUS_RING}`;
// 바닥글 링크 한 칸 — 밑줄은 Hover에만
const FOOTER_LINK = `rounded-tag text-body-2 font-medium text-text-sub hover:underline ${FOCUS_RING}`;

export default function Lnd01001Page() {
  return (
    <div data-screen-id="LND_01_001" className="flex flex-col bg-bg-default break-keep text-text-main">
      {/* 높이는 globals.css 토큰 하나(--landing-gnb-height) — 스토리 구간의 sticky 위치 · 높이 계산도 같은 값을 쓴다 */}
      <header className="sticky top-0 z-10 h-(--landing-gnb-height) border-b border-line-light bg-bg-default px-5">
        <nav aria-label="사이트" className="mx-auto flex h-full max-w-300 items-center gap-8 lg:gap-14">
          <Link href="/" className={`rounded-tag text-headline-3 font-extrabold ${FOCUS_RING}`}>
            {SITE_NAME}
          </Link>
          <ul className="flex items-center gap-5 lg:gap-8">
            <li className="hidden sm:block">
              <a href="#features" className={MENU_ITEM}>
                기능
              </a>
            </li>
            <li className="hidden sm:block">
              <a href="#how-measured" className={MENU_ITEM}>
                평가 방법
              </a>
            </li>
            <li>
              <Link href="/demo" className={MENU_ITEM}>
                샘플 보기
              </Link>
            </li>
            <li>
              <Suspense fallback={<HomeOrLoginLink signedIn={false} guestLabel="로그인" className={MENU_ITEM} />}>
                <CurrentHomeOrLoginLink guestLabel="로그인" className={MENU_ITEM} />
              </Suspense>
            </li>
          </ul>
        </nav>
      </header>

      <main className="flex flex-col">
        <section aria-labelledby="landing-title" className="landing-hero flex items-center px-5">
          <div className="mx-auto flex w-full max-w-300 flex-col gap-12 py-12 lg:flex-row lg:items-center">
            <div className="flex flex-col gap-6 lg:w-117 lg:shrink-0">
              <span className={`self-start ${BADGE_LINE}`}>채용 담당자를 위한 30초 요약</span>
              <h1 id="landing-title" className="text-headline-1 font-semibold lg:text-display-2">
                문장마다
                <br />
                근거가 달린 자소서
              </h1>
              <p className="text-title-2 font-normal text-text-sub">
                디딤은 지원자의 공부 기록과 프로젝트 회고에서만 문장을 만들고, 기록에 없는 문장에는 밑줄을 그어요.
              </p>
              <div className="flex flex-wrap gap-3">
                <Suspense
                  fallback={<HomeOrLoginLink signedIn={false} guestLabel="내 기록으로 시작하기" className={PRIMARY_BUTTON_L} />}
                >
                  <CurrentHomeOrLoginLink guestLabel="내 기록으로 시작하기" className={PRIMARY_BUTTON_L} />
                </Suspense>
                <Link href="/demo" className={SECONDARY_BUTTON_L}>
                  샘플 보기
                </Link>
              </div>
              <section aria-labelledby="hero-metrics-title" className="flex flex-col gap-3">
                <h2 id="hero-metrics-title" className="sr-only">
                  평가 수치
                </h2>
                <Suspense fallback={<p className="text-body-4 text-text-sub-weak">수치를 불러오고 있어요…</p>}>
                  <HeroMetrics />
                </Suspense>
                <Link href="/report" className={`self-start ${TEXT_BUTTON}`}>
                  평가 리포트 전체 보기
                </Link>
              </section>
            </div>
            <div className="min-w-0 flex-1">
              <LandingDraftPreview />
            </div>
          </div>
        </section>

        <LandingStory />
        <LandingFeatures />
        <LandingHowMeasured />

        <section aria-labelledby="final-cta-title" className="flex flex-col items-center gap-12 px-5 py-20 text-center">
          <div className="flex flex-col items-center gap-3">
            <h2 id="final-cta-title" className="text-headline-1 font-semibold text-text-main">
              내 기록으로 시작해 보세요
            </h2>
            <p className="text-title-4 font-normal text-text-sub">가입하고 마크다운 노트 하나만 올리면 돼요.</p>
          </div>
          <Suspense fallback={<HomeOrLoginLink signedIn={false} guestLabel="내 기록으로 시작하기" className={PRIMARY_BUTTON_L} />}>
            <CurrentHomeOrLoginLink guestLabel="내 기록으로 시작하기" className={PRIMARY_BUTTON_L} />
          </Suspense>
        </section>
      </main>

      {/* Figma Footer PC Simple(Theme Light). 소개 · 이용약관 · 개인정보 처리방침 · 문의는 아직 페이지가 없어 있는 링크로 둔다 */}
      <footer className="bg-bg-regular px-5 py-10">
        <div className="mx-auto flex max-w-300 flex-col gap-5">
          <div className="flex flex-wrap items-center gap-x-12 gap-y-3">
            <p className="text-title-1 font-extrabold text-text-main">{SITE_NAME}</p>
            <nav aria-label="바닥글" className="flex gap-6">
              <Link href="/report" className={FOOTER_LINK}>
                평가 리포트
              </Link>
              <Link href="/demo" className={FOOTER_LINK}>
                샘플 체험
              </Link>
            </nav>
          </div>
          <hr className="border-line-regular" />
          <div className="flex flex-col gap-0.5 text-body-4 text-text-sub">
            <p>{SITE_NAME} · 공부 기록을 근거로 자소서와 면접을 준비하는 서비스 · 혼자 2주 동안 만든 포트폴리오 프로젝트</p>
            <p>© 2026 {SITE_NAME}</p>
          </div>
        </div>
      </footer>
    </div>
  );
}

// 로그인한 사람에게도 랜딩을 그대로 보이고 [로그인] · [내 기록으로 시작하기] 대신 [홈으로](사용자 확인 2026-11-18).
// 읽는 동안(fallback)은 로그인 안 한 모양으로 둔다. 세 곳이 불러도 getCurrentUserOrNull은 cache()라 /api/auth/me는 요청당 한 번이다.
type HomeOrLoginProps = { guestLabel: string; className: string };

async function CurrentHomeOrLoginLink(props: HomeOrLoginProps) {
  return <HomeOrLoginLink signedIn={(await getCurrentUserOrNull()) !== null} {...props} />;
}

function HomeOrLoginLink({ signedIn, guestLabel, className }: HomeOrLoginProps & { signedIn: boolean }) {
  return (
    <Link href={signedIn ? "/home" : "/login"} className={className}>
      {signedIn ? "홈으로" : guestLabel}
    </Link>
  );
}

// 평가 수치는 리포트와 같은 GET /api/report 최근 회차에서 읽는다(사용자 확인 2026-11-18).
// 못 읽거나 고를 수치가 없으면 수치 칸만 숨긴다 — [평가 리포트 전체 보기]는 Suspense 밖이라 남는다.
async function HeroMetrics() {
  const latest = (await getReportRuns())?.[0];
  const metrics = latest ? heroMetrics(latest) : [];
  if (!latest || metrics.length === 0) return null;
  const size = heroDataSize(latest);
  return (
    <>
      <dl className="flex flex-wrap gap-6">
        {metrics.map((metric) => (
          <div key={metric.key} className="flex min-w-28 flex-1 flex-col-reverse gap-1">
            <dt className="text-body-4 text-text-sub">{metric.label}</dt>
            <dd className="text-title-2 font-semibold text-text-main">{metric.value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-body-4 text-text-sub">
        * {runDate(latest)} 회차{latest.model ? ` · 모델 ${latest.model}` : ""} — 정답을 미리 심어 둔 가상 데이터
        {size ? `(${size})` : ""}로 쟀어요.
      </p>
    </>
  );
}
