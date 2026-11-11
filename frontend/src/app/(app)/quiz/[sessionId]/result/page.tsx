import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { PageBody, PageHeader } from "@/components/page-parts";
import { type QuizSession, parseQuizSession } from "@/lib/quiz";
import { CARD, CARD_LABEL, PRIMARY_BUTTON, SECONDARY_BUTTON, TEXT_BUTTON } from "@/lib/ui-classes";

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

const SESSION_LABEL: Record<QuizSession["kind"], string> = {
  today: "오늘 복습",
  wrong: "오답노트 다시 풀기",
  note: "노트 문제",
};

// REV_02_002 결과(Figma 26:870). 백엔드에 세션 표가 없어서 점수는 주소(?correct=&total=)로 받는다(사용자 확인 2026-11-11).
// 답 하나하나는 이미 서버에 저장됐고(quiz_attempts), 이 화면은 이번 세션 점수만 보여 준다.
// Figma의 '지난번 대비' · 다음 복습 날짜 · 틀린 문제 목록은 세션 기록이 생긴 뒤에 붙인다(D-019 — 데이터 없는 칸은 그리지 않음).
export default async function Rev02002Page(props: PageProps<"/quiz/[sessionId]/result">) {
  const { sessionId } = await props.params;
  const session = parseQuizSession(sessionId);
  if (session === null) {
    notFound();
  }
  const { correct: rawCorrect, total: rawTotal } = await props.searchParams;
  const correct = parseCount(rawCorrect);
  const total = parseCount(rawTotal);
  const valid = correct !== null && total !== null && total >= 1 && total <= MAX_RESULT_TOTAL && correct <= total;

  return (
    <section data-screen-id="REV_02_002" aria-labelledby="result-title">
      <PageHeader
        titleId="result-title"
        title="복습을 마쳤어요"
        description={valid ? `${SESSION_LABEL[session.kind]} · ${total}문제` : SESSION_LABEL[session.kind]}
        actions={
          <nav aria-label="다음에 할 일" className="flex flex-wrap gap-2">
            <Link href="/home" className={SECONDARY_BUTTON}>
              홈으로
            </Link>
            {valid && correct < total ? (
              <Link href="/quiz/wrong" className={PRIMARY_BUTTON}>
                틀린 문제 다시 풀기
              </Link>
            ) : null}
          </nav>
        }
      />
      <PageBody>
        {valid ? (
          <Score correct={correct} total={total} />
        ) : (
          <p role="status" className="text-body-2 text-text-sub">
            보여 줄 점수가 없어요. 푼 답은 이미 저장돼 있어요.
          </p>
        )}
      </PageBody>
    </section>
  );
}

function Score({ correct, total }: { correct: number; total: number }) {
  const wrong = total - correct;
  const percent = Math.round((correct / total) * 100);
  return (
    <section aria-labelledby="score-title" className={`${CARD} flex flex-col items-start gap-2`}>
      <h2 id="score-title" className={CARD_LABEL}>
        이번 점수
      </h2>
      <p className="flex items-end gap-2">
        <span className="text-title-1 font-semibold text-text-main">
          {correct} / {total}
        </span>
        <span className="text-body-1 font-medium text-text-sub">{percent}%</span>
      </p>
      <p className="text-body-2 text-text-sub">
        {wrong > 0
          ? `틀린 ${wrong}개는 오답노트에 넣었고, 오늘 복습에 다시 나와요.`
          : "모두 맞혔어요. 다음 복습일에 다시 나와요."}
      </p>
      <Link href="/records/wrong-answers" className={TEXT_BUTTON}>
        오답노트 보기
      </Link>
    </section>
  );
}
