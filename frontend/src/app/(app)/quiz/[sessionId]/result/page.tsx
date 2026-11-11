import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { parseQuizSession } from "@/lib/quiz";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "퀴즈 결과",
  description: "이번에 푼 문제의 점수를 보고, 틀린 문제를 다시 풀어요.",
};

// 한 세션 문제 수 상한보다 넉넉한 값. 주소를 손으로 고친 터무니없는 숫자를 거르려는 것(서버 상한 100개)
const MAX_RESULT_TOTAL = 1000;

function parseCount(value: unknown): number | null {
  if (typeof value !== "string" || !/^\d{1,4}$/.test(value)) {
    return null;
  }
  return Number(value);
}

// REV_02_002 결과. 백엔드에 세션 표가 없어서 점수는 주소(?correct=&total=)로 받는다(사용자 확인 2026-11-11).
// 답 하나하나는 이미 서버에 저장됐고(quiz_attempts), 이 화면은 이번 세션 점수만 보여 준다.
// 이전 세션과의 '점수 변화'는 세션 기록이 생긴 뒤에 붙인다.
export default async function Rev02002Page(props: PageProps<"/quiz/[sessionId]/result">) {
  const { sessionId } = await props.params;
  if (parseQuizSession(sessionId) === null) {
    notFound();
  }
  const { correct: rawCorrect, total: rawTotal } = await props.searchParams;
  const correct = parseCount(rawCorrect);
  const total = parseCount(rawTotal);
  const valid = correct !== null && total !== null && total >= 1 && total <= MAX_RESULT_TOTAL && correct <= total;

  return (
    <section data-screen-id="REV_02_002" aria-labelledby="result-title" className="flex flex-col gap-6 p-8">
      <h1 id="result-title" className="text-title-1 font-semibold">
        퀴즈 결과
      </h1>
      {valid ? (
        <Score correct={correct} total={total} />
      ) : (
        <p role="status" className="text-body-2 text-text-sub">
          보여 줄 점수가 없어요. 푼 답은 이미 저장돼 있어요.
        </p>
      )}
      <nav aria-label="다음에 할 일" className="flex flex-wrap gap-2">
        {valid && correct < total ? (
          <Link href="/quiz/wrong" className={PRIMARY_BUTTON}>
            틀린 문제 다시 풀기
          </Link>
        ) : null}
        <Link href="/records/wrong-answers" className={SECONDARY_BUTTON}>
          오답노트 보기
        </Link>
        <Link href="/records" className={SECONDARY_BUTTON}>
          기록 · 복습으로
        </Link>
      </nav>
    </section>
  );
}

function Score({ correct, total }: { correct: number; total: number }) {
  const wrong = total - correct;
  const percent = Math.round((correct / total) * 100);
  return (
    <div className="flex flex-col gap-2 rounded-card border border-line-regular bg-bg-default p-6">
      <p className="text-headline-2 font-semibold">
        {total}문제 중 {correct}개 맞혔어요 <span className="text-text-sub">({percent}%)</span>
      </p>
      <p className="text-body-2 text-text-sub">
        {wrong > 0
          ? `틀린 ${wrong}개는 오답노트에 넣었고, 오늘 복습에 다시 나와요.`
          : "모두 맞혔어요. 다음 복습일에 다시 나와요."}
      </p>
    </div>
  );
}
