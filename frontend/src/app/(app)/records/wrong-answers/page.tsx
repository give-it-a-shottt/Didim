import type { Metadata } from "next";
import Link from "next/link";
import { EmptyState, PageBody, PageHeader } from "@/components/page-parts";
import { formatReviewDate, quizKindLabel } from "@/lib/quiz";
import { getWrongAnswers } from "@/lib/quiz-data";
import { CARD, FOCUS_RING, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "오답노트",
  description: "틀린 문제를 다시 풀어요. 2번 연속 맞히면 빠져요.",
};

// REV_03_001 오답노트(Figma 26:971). 목록은 서버 컴포넌트에서 받는다(D-012). 정답 · 해설은 목록에 없다 — 다시 풀어야 보인다.
// Figma의 '내 답 → 정답' · '연속 정답 0 / 2' 배지는 목록 응답에 없어 그리지 않는다(D-019, 목록에서 정답 숨김은 F-004 결정).
export default async function Rev03001Page() {
  const outcome = await getWrongAnswers();
  const hasQuizzes = outcome.status === "ok" && outcome.quizzes.length > 0;

  return (
    <section data-screen-id="REV_03_001" aria-labelledby="wrong-title">
      <PageHeader
        titleId="wrong-title"
        title="오답노트"
        description={`2번 연속 맞히면 빠져요.${outcome.status === "ok" ? ` · ${outcome.total}문제` : ""}`}
        actions={
          hasQuizzes ? (
            <Link href="/quiz/wrong" className={PRIMARY_BUTTON}>
              {outcome.quizzes.length}문제 다시 풀기
            </Link>
          ) : null
        }
      />
      <PageBody>
        {outcome.status !== "ok" ? (
          <p role="alert" className="text-body-2 font-medium text-error-text">
            오답노트를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
          </p>
        ) : outcome.quizzes.length === 0 ? (
          <EmptyState
            title="오답노트가 비어 있어요"
            description="틀린 문제가 생기면 여기에 모여요."
            action={
              <Link href="/records" className={SECONDARY_BUTTON}>
                기록 · 복습으로
              </Link>
            }
          />
        ) : (
          <div className={`${CARD} flex flex-col`}>
            {outcome.total > outcome.quizzes.length ? (
              <p className="text-body-3 text-text-sub">
                틀린 문제 {outcome.total}개 중 최근에 틀린 {outcome.quizzes.length}개를 보여 줘요.
              </p>
            ) : null}
            <ol aria-label="틀린 문제">
              {outcome.quizzes.map((quiz) => (
                <li key={quiz.id} className="flex flex-col gap-1 border-b border-line-light py-4">
                  <span className="text-body-1 font-medium whitespace-pre-wrap text-text-main">{quiz.question}</span>
                  <span className="text-body-3 text-text-sub">
                    {quizKindLabel(quiz.kind)} · 다음 복습 {formatReviewDate(quiz.nextReviewOn)}
                  </span>
                  <span className="text-body-4 text-text-sub">
                    출처 ·{" "}
                    <Link href={`/records/${quiz.noteId}`} className={`underline hover:text-text-main ${FOCUS_RING}`}>
                      {quiz.noteTitle}
                    </Link>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </PageBody>
    </section>
  );
}
