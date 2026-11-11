import "server-only";

import { fetchBackendAsUser } from "@/lib/backend";
import { readJson } from "@/lib/json";
import { type QuizCard, type QuizSession, toQuizCards } from "@/lib/quiz";

// 퀴즈 목록을 서버 컴포넌트에서 FastAPI로 부른다(F-004). 처음 화면을 그릴 때 필요한 서버 데이터라 서버 컴포넌트(D-012).
// 퀴즈를 시작할 때 한 번 받아 고정한다 — 풀면서 '오늘 복습' 목록이 바뀌어도 세션 문제는 그대로다.

export type QuizListOutcome =
  | { status: "ok"; quizzes: QuizCard[]; total: number }
  | { status: "not-found" } // 내 노트가 아님(노트 세션)
  | { status: "error" };

async function fetchQuizList(path: string): Promise<QuizListOutcome> {
  const response = await fetchBackendAsUser(path);
  if (response === null) {
    return { status: "error" };
  }
  if (response.status === 404) {
    return { status: "not-found" };
  }
  const body = response.ok ? await readJson(response) : null;
  const quizzes = toQuizCards(body);
  if (quizzes === null) {
    return { status: "error" };
  }
  // 오늘 복습 · 오답노트는 전체 개수(total)를 따로 준다(목록은 서버 상한 MAX_REVIEW_SESSION_QUIZZES까지). 노트 문제는 목록 길이가 전체다.
  const total =
    typeof body === "object" && body !== null && "total" in body && typeof body.total === "number"
      ? body.total
      : quizzes.length;
  return { status: "ok", quizzes, total };
}

export function getTodayReviews(): Promise<QuizListOutcome> {
  return fetchQuizList("/api/reviews/today");
}

export function getWrongAnswers(): Promise<QuizListOutcome> {
  return fetchQuizList("/api/wrong-answers");
}

export function getNoteQuizzes(noteId: number): Promise<QuizListOutcome> {
  return fetchQuizList(`/api/notes/${noteId}/quizzes`);
}

export function getSessionQuizzes(session: QuizSession): Promise<QuizListOutcome> {
  switch (session.kind) {
    case "today":
      return getTodayReviews();
    case "wrong":
      return getWrongAnswers();
    case "note":
      return getNoteQuizzes(session.noteId);
  }
}
