import type { Metadata } from "next";
import Link from "next/link";
import { formatReviewDate, quizKindLabel } from "@/lib/quiz";
import { getWrongAnswers } from "@/lib/quiz-data";
import { FOCUS_RING, PRIMARY_BUTTON } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "오답노트",
  description: "틀린 문제를 다시 풀어요. 2번 연속 맞히면 빠져요.",
};

// REV_03_001 오답노트. 목록은 서버 컴포넌트에서 받는다(D-012). 정답 · 해설은 목록에 없다 — 다시 풀어야 보인다.
export default async function Rev03001Page() {
  const outcome = await getWrongAnswers();

  return (
    <section data-screen-id="REV_03_001" aria-labelledby="wrong-title" className="flex flex-col gap-6 p-8">
      <header className="flex flex-col gap-1">
        <Link href="/records" className="text-body-3 text-text-sub hover:underline">
          ← 기록 · 복습
        </Link>
        <h1 id="wrong-title" className="text-title-1 font-semibold">
          오답노트
        </h1>
        <p className="text-body-2 text-text-sub">틀린 문제가 모여요. 2번 연속 맞히면 빠져요.</p>
      </header>

      {outcome.status !== "ok" ? (
        <p role="alert" className="text-body-2 font-medium text-error-text">
          오답노트를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      ) : outcome.quizzes.length === 0 ? (
        <p role="status" className="text-body-2 text-text-sub">
          오답노트가 비어 있어요. 틀린 문제가 생기면 여기에 모여요.
        </p>
      ) : (
        <>
          <Link href="/quiz/wrong" className={`${PRIMARY_BUTTON} self-start`}>
            {outcome.quizzes.length}문제 다시 풀기
          </Link>
          {outcome.total > outcome.quizzes.length ? (
            <p className="text-body-3 text-text-sub">
              틀린 문제 {outcome.total}개 중 최근에 틀린 {outcome.quizzes.length}개를 보여 줘요.
            </p>
          ) : null}
          <ol className="flex flex-col gap-2" aria-label="틀린 문제">
            {outcome.quizzes.map((quiz) => (
              <li
                key={quiz.id}
                className="flex flex-col gap-1 rounded-card border border-line-regular bg-bg-default p-4"
              >
                <span className="text-body-1 whitespace-pre-wrap text-text-main">{quiz.question}</span>
                <span className="text-body-4 text-text-sub">
                  {quizKindLabel(quiz.kind)} · 다음 복습 {formatReviewDate(quiz.nextReviewOn)} ·{" "}
                  <Link href={`/records/${quiz.noteId}`} className={`underline hover:text-text-main ${FOCUS_RING}`}>
                    {quiz.noteTitle}
                  </Link>
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
