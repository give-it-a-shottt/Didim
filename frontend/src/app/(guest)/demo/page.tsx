import type { Metadata } from "next";
import Link from "next/link";
import { StartSampleButton } from "@/components/sample-session-buttons";
import { MEMBER_ROBOTS } from "@/lib/site";
import { CARD, TEXT_BUTTON } from "@/lib/ui-classes";

// DEM_01_001 샘플 체험 입구(F-010, D-029). 로그인 없이 들어온다.
// [샘플로 체험하기]를 누르면 샘플 사용자 세션으로 기존 회원 화면을 그대로 둘러본다(쓰기 · AI 호출은 서버가 막음).
// 샘플 화면은 검색에 올리지 않는다(사용자 확인 2026-11-17) — 입구도 같이 noindex, sitemap에도 넣지 않는다.
export const metadata: Metadata = {
  title: "샘플 체험",
  description: "가상 지원자의 기록으로 디딤을 로그인 없이 둘러봐요.",
  robots: MEMBER_ROBOTS,
};

const WHAT_YOU_SEE = [
  "공부 노트와 노트에서 만든 퀴즈",
  "노트에서 뽑은 경험 카드 — 칸마다 원문 인용",
  "가상 공고 10개와 카드 매칭",
  "문장마다 근거가 달린 자소서 초안과 '확인 필요' 표시",
  "카드에서 만든 면접 질문",
] as const;

export default function Dem01001Page() {
  return (
    <section
      data-screen-id="DEM_01_001"
      aria-labelledby="demo-title"
      className="flex min-h-screen items-center justify-center bg-bg-light px-5 py-12 text-text-main"
    >
      <div className={`flex w-full max-w-140 flex-col gap-6 ${CARD}`}>
        <div className="flex flex-col gap-2">
          <h1 id="demo-title" className="text-title-1 font-semibold">
            샘플로 디딤 둘러보기
          </h1>
          <p className="text-body-2 text-text-sub">
            가상 지원자 한 명의 기록이 들어 있어요. 평가 리포트의 수치를 잰 것과 같은 데이터예요.
          </p>
        </div>

        <ul className="flex flex-col gap-2 text-body-2 text-text-main">
          {WHAT_YOU_SEE.map((item) => (
            <li key={item}>· {item}</li>
          ))}
        </ul>

        <div className="flex flex-col gap-1 text-body-3 text-text-sub">
          <p>샘플은 읽기만 할 수 있어요. 고치거나 AI로 새로 만드는 버튼은 동작하지 않아요.</p>
          <p>로그인한 상태라면 체험을 시작할 때 로그아웃돼요.</p>
        </div>

        <StartSampleButton />

        <Link href="/login" className={`self-start ${TEXT_BUTTON}`}>
          내 기록으로 시작하기
        </Link>
      </div>
    </section>
  );
}
