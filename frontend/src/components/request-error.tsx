// 브라우저 요청(lib/api-request.ts) 실패를 보여 주는 부품. 퀴즈 · 경험 카드 화면이 같이 쓴다
// (F-006 2차 리뷰 R1 — 같은 블록이 화면마다 있던 것을 모음). 로그인이 풀렸으면 로그인 링크를 같이 둔다.
import Link from "next/link";
import type { ReactNode } from "react";
import { ApiRequestError } from "@/lib/api-request";
import { SECONDARY_BUTTON } from "@/lib/ui-classes";

function needsLogin(error: Error): boolean {
  return error instanceof ApiRequestError && error.needsLogin;
}

/** 한 줄 문구 + 글자 링크(카드 상세 · 후보 검토 시트). */
export function RequestErrorText({ error }: { error: Error }) {
  return (
    <p role="alert" className="text-body-2 font-medium text-error-text">
      {error.message}
      {needsLogin(error) ? (
        <>
          {" "}
          <Link href="/login" className="underline">
            로그인하러 가기
          </Link>
        </>
      ) : null}
    </p>
  );
}

/** 문구 + 버튼 모양 링크(노트 상세의 [문제 만들기] · [카드 후보 찾기], 퀴즈 [답 내기]). 로그인 문제가 아니면 hint를 보여 준다. */
export function RequestErrorBlock({ error, hint }: { error: Error; hint?: ReactNode }) {
  return (
    <div role="alert" className="flex flex-col gap-2">
      <p className="text-body-2 font-medium text-error-text">{error.message}</p>
      {needsLogin(error) ? (
        <Link href="/login" className={`${SECONDARY_BUTTON} self-start`}>
          로그인하러 가기
        </Link>
      ) : (
        (hint ?? null)
      )}
    </div>
  );
}
