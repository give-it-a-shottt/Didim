"use client";

// 노트 상세(REV_01_002)의 오른쪽 문제 칸(F-004, Figma 26:575 자리). 문제가 없으면 [문제 만들기], 있으면 개수와 안내.
// [이 노트 풀기]는 페이지 머리(서버 컴포넌트)에 있다 — 만든 뒤 router.refresh()로 머리에 나타난다.
// 문제 수는 서버 컴포넌트가 넘기고(quizCount), 만들기는 서버 수정이라 TanStack Query useMutation(D-012).
// 만든 뒤 router.refresh()로 서버 컴포넌트를 새로 받으면 quizCount가 바뀐다. 만든 결과 문구는 mutation이 갖고 있어서
// 새로 고친 뒤에도 남는다(같은 컴포넌트가 계속 그려지므로).

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { RequestErrorBlock } from "@/components/request-error";
import { ApiRequestError } from "@/lib/api-request";
import {
  type GenerateResult,
  generateQuizzes,
  MAX_QUIZZES_PER_NOTE,
} from "@/lib/quiz";
import { CARD, CARD_LABEL, PRIMARY_BUTTON } from "@/lib/ui-classes";

const CONFLICT = 409;

export function NoteQuizPanel({ noteId, quizCount }: { noteId: number; quizCount: number | null }) {
  const router = useRouter();
  const generate = useMutation({
    mutationFn: () => generateQuizzes(noteId),
    onSuccess: () => router.refresh(),
    onError: (error) => {
      // 409 "이미 문제가 있어요"(다른 탭에서 먼저 만듦) — 새로 받아 [이 노트 풀기]를 보여 준다
      if (error instanceof ApiRequestError && error.status === CONFLICT) router.refresh();
    },
  });

  return (
    <section
      aria-labelledby="note-quiz-title"
      className={`${CARD} flex flex-col gap-3`}
    >
      <h2 id="note-quiz-title" className={CARD_LABEL}>
        문제{quizCount !== null && quizCount > 0 ? ` ${quizCount}개` : ""}
      </h2>

      {quizCount === null ? (
        <p role="alert" className="text-body-2 font-medium text-error-text">
          문제를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      ) : quizCount > 0 ? (
        <p className="text-body-2 text-text-sub">
          위 [이 노트 풀기]로 풀어요. 복습일 전에 풀어도 돼요. 틀린 문제는 오답노트로 가요.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {/* 설계 원칙 6: AI에 무엇을 보내는지 누르기 전에 알린다 */}
          <p className="text-body-2 text-text-sub">
            이 노트에서 내용이 충분히 긴 부분을 최대 {MAX_QUIZZES_PER_NOTE}곳 골라 AI에 보내고, 곳마다 객관식 · OX 문제를 하나씩 만들어요.
            AI가 든 근거 문장이 원문에 글자 그대로 없으면 그 문제는 버려요. 오늘 AI 사용량 1회를 써요.
          </p>
          <button
            type="button"
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
            className={`${PRIMARY_BUTTON} self-start`}
          >
            {generate.isPending ? "만드는 중…" : "문제 만들기"}
          </button>
          {generate.isPending ? (
            <p role="status" className="text-body-2 text-text-sub">
              문제를 만들고 있어요. AI 답을 기다리느라 1~2분 걸릴 수 있어요.
            </p>
          ) : null}
        </div>
      )}

      {generate.data ? <GenerateSummary result={generate.data} /> : null}
      {generate.error ? <RequestErrorBlock error={generate.error} /> : null}
    </section>
  );
}

function GenerateSummary({ result }: { result: GenerateResult }) {
  return (
    <div role="status" className="flex flex-col gap-1 text-body-2">
      <p className={result.created > 0 ? "font-medium text-success-text" : "font-medium text-text-main"}>
        {result.created > 0
          ? `✓ 문제 ${result.created}개를 만들었어요.`
          : "근거를 확인한 문제가 없어 하나도 만들지 못했어요. 다시 시도할 수 있어요."}
      </p>
      {result.dropped > 0 ? (
        <p className="text-text-sub">원문에서 근거를 확인하지 못한 {result.dropped}개는 버렸어요.</p>
      ) : null}
      <p className="text-text-sub">오늘 남은 AI 사용: {result.remainingToday}회</p>
    </div>
  );
}
