import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { FocusTitle, FocusTopBar } from "@/components/focus-top-bar";
import { QuizRunner } from "@/components/quiz-runner";
import { type QuizSession, parseQuizSession } from "@/lib/quiz";
import { getSessionQuizzes } from "@/lib/quiz-data";
import { SECONDARY_BUTTON } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "퀴즈",
  description: "노트에서 만든 객관식 · OX 문제를 풀어요.",
};

// REV_02_001 퀴즈(집중 모드, Figma 26:804). 주소가 세션 종류다(사용자 확인 2026-11-11):
// /quiz/today 오늘 복습 · /quiz/wrong 오답노트 다시 풀기 · /quiz/note-12 노트 12만.
// 문제 목록은 여기(서버 컴포넌트)서 시작할 때 한 번 받아 고정하고, 풀기 · 답 제출은 QuizRunner(클라이언트)가 한다.
export default async function Rev02001Page(props: PageProps<"/quiz/[sessionId]">) {
  const { sessionId } = await props.params;
  const session = parseQuizSession(sessionId);
  if (session === null) {
    notFound();
  }

  const outcome = await getSessionQuizzes(session);
  if (outcome.status === "not-found") {
    notFound();
  }

  const title = outcome.status === "ok" ? sessionTitle(session, outcome.quizzes[0]?.noteTitle) : sessionTitle(session);

  // 오래 밀린 문제가 상한(100개)보다 많으면 먼저 풀 몫만 받는다는 안내
  const notice =
    outcome.status === "ok" && outcome.total > outcome.quizzes.length
      ? session.kind === "today"
        ? `오늘 차례인 문제 ${outcome.total}개 중 오래 밀린 ${outcome.quizzes.length}개를 먼저 풀어요.`
        : `틀린 문제 ${outcome.total}개 중 최근에 틀린 ${outcome.quizzes.length}개를 풀어요.`
      : null;

  return (
    <section data-screen-id="REV_02_001" aria-labelledby="quiz-title">
      {outcome.status === "ok" && outcome.quizzes.length > 0 ? (
        // 문제 목록이 바뀌면(다시 들어왔을 때 서버 목록이 달라짐) 처음부터 새로 그린다.
        // 위쪽 띠의 "4 / 12" · 진행 막대와 제목은 몇 번째 문제인지 아는 QuizRunner가 그린다.
        <QuizRunner
          key={outcome.quizzes.map((quiz) => quiz.id).join(",")}
          sessionId={sessionId}
          title={title}
          titleId="quiz-title"
          notice={notice}
          quizzes={outcome.quizzes}
        />
      ) : (
        <>
          <FocusTopBar />
          <div className="flex flex-col gap-6 px-5 py-10 lg:px-12">
            <FocusTitle id="quiz-title">{title}</FocusTitle>
            {outcome.status === "error" ? (
              <p role="alert" className="text-body-2 font-medium text-error-text">
                문제를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
              </p>
            ) : (
              <EmptySession session={session} />
            )}
          </div>
        </>
      )}
    </section>
  );
}

function sessionTitle(session: QuizSession, noteTitle?: string): string {
  switch (session.kind) {
    case "today":
      return "오늘 복습";
    case "wrong":
      return "오답노트 다시 풀기";
    case "note":
      return noteTitle ? `${noteTitle} 풀기` : "이 노트 풀기";
  }
}

function EmptySession({ session }: { session: QuizSession }) {
  const message =
    session.kind === "today"
      ? "오늘 복습할 문제가 없어요."
      : session.kind === "wrong"
        ? "오답노트가 비어 있어요. 틀린 문제가 생기면 여기서 다시 풀어요."
        : "이 노트에는 아직 문제가 없어요. 노트 상세에서 [문제 만들기]를 눌러 주세요.";
  const back =
    session.kind === "note"
      ? { href: `/records/${session.noteId}`, label: "노트로 돌아가기" }
      : { href: "/records", label: "기록 · 복습으로" };
  return (
    <div className="flex flex-col gap-3">
      <p role="status" className="text-body-2 text-text-sub">
        {message}
      </p>
      <Link href={back.href} className={`${SECONDARY_BUTTON} self-start`}>
        {back.label}
      </Link>
    </div>
  );
}
