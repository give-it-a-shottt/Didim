import { Suspense } from "react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "로그인",
  description: "구글 계정으로 디딤을 시작해요. 올린 노트는 나만 볼 수 있어요.",
};

const CHECK_ITEMS = [
  "공부한 노트로 복습하고",
  "노트에서 경험 카드를 뽑고",
  "공고에 맞춰 문장마다 근거가 달린 초안을 만들어요",
] as const;

const DATA_PRINCIPLES = [
  "· 올린 노트는 나만 볼 수 있어요",
  "· AI에는 필요한 조각만 보내요",
  "· 설정에서 언제든 모두 지울 수 있어요",
] as const;

const ERROR_MESSAGES: Record<string, string> = {
  oauth_access_denied: "구글 로그인이 취소되었어요. 다시 시도해 주세요.",
  oauth_not_configured: "구글 로그인 환경 설정이 아직 완료되지 않았어요.",
  invalid_oauth_state: "로그인 요청이 만료되었거나 유효하지 않아요. 다시 시도해 주세요.",
};

async function LoginErrorBanner({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  if (!error) {
    return null;
  }

  const message =
    ERROR_MESSAGES[error] ?? "구글 로그인을 완료하지 못했어요. 잠시 후 다시 시도해 주세요.";

  return (
    <div
      role="alert"
      className="rounded-[8px] border border-[#B3262B] bg-[#FFF2F2] px-4 py-3 text-[13px] text-[#B3262B]"
    >
      {message}
    </div>
  );
}

export default function Aut01001Page({
  searchParams,
}: PageProps<"/login">) {
  return (
    <section
      data-screen-id="AUT_01_001"
      className="grid min-h-screen grid-cols-1 bg-white text-[#111111] md:grid-cols-2"
    >
      {/* 왼쪽 소개 영역 (피그마 AUT_01_001 '소개' 프레임) */}
      <div className="flex flex-col justify-center gap-6 bg-[#FAFAFA] px-6 py-12 md:px-16">
        <div className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-6 w-6 rounded-[6px] bg-[#00A6B4]"
          />
          <span className="text-[20px] font-semibold tracking-[-0.025em] text-[#111111]">
            디딤
          </span>
        </div>

        <p className="text-[24px] font-semibold leading-[1.42] tracking-[-0.025em] text-[#111111]">
          내 기록이 근거가 되는 자소서
        </p>

        <ul className="flex flex-col gap-3">
          {CHECK_ITEMS.map((item) => (
            <li key={item} className="flex items-center gap-2 text-[16px] text-[#111111]">
              <span aria-hidden="true" className="font-semibold text-[#01757F]">
                ✓
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* 오른쪽 로그인 영역 (피그마 AUT_01_001 '로그인' 프레임) */}
      <div className="flex flex-col justify-center gap-5 bg-white px-6 py-12 md:px-16">
        <div className="mx-auto flex w-full max-w-[400px] flex-col gap-5">
          <h1 className="text-[20px] font-semibold tracking-[-0.025em] text-[#111111]">
            디딤 시작하기
          </h1>

          <Suspense fallback={null}>
            <LoginErrorBanner searchParams={searchParams} />
          </Suspense>

          <a
            href="/api/auth/google/login"
            className="inline-flex h-12 w-full items-center justify-center rounded-[8px] border border-[#111111] bg-white px-5 text-[16px] font-semibold text-[#111111] transition-colors hover:bg-[#F5F5F5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#01808B]"
          >
            Google로 계속하기
          </a>

          <div className="flex flex-col gap-2 rounded-[16px] border border-[#EEEEEE] bg-[#FAFAFA] p-4">
            <h2 className="text-[14px] font-semibold text-[#111111]">
              내 데이터는 이렇게 다뤄요
            </h2>
            <ul className="flex flex-col gap-1 text-[13px] text-[#424242]">
              {DATA_PRINCIPLES.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>

          <div className="flex items-center gap-3 text-[13px] font-medium text-[#757575]">
            <span>이용약관</span>
            <span>개인정보 처리방침</span>
          </div>
        </div>
      </div>
    </section>
  );
}
