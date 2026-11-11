"use client";

// REV_02_001 퀴즈(집중 모드)의 문제 풀기 부분. 문제 목록은 서버 컴포넌트가 시작할 때 한 번 받아 넘긴다.
// 상태(몇 번째 문제 · 고른 보기 · 점수)는 이 화면에서만 써서 useState, 답 제출은 서버 수정이라 TanStack Query
// useMutation(D-012, architecture.md 상태 관리 지도).
//
// Next 16 cacheComponents는 다른 화면으로 가도 이 컴포넌트를 숨겨 둔다(Activity). 그래서
// - 근거 칩으로 노트를 보고 뒤로 오면 풀던 자리가 그대로 남는다(일부러 살림).
// - 다 풀고 결과로 넘어가면, 숨겨질 때 처음 상태로 되돌린다(같은 세션에 다시 들어오면 처음부터).
// - 문제 목록이 바뀌면(page.tsx가 key로 문제 ID 목록을 줌) 새로 그린다.

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, type RefObject, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import {
  type AnswerResult,
  evidenceHref,
  formatReviewDate,
  type QuizCard,
  QuizRequestError,
  quizKindLabel,
  submitAnswer,
} from "@/lib/quiz";
import { EVIDENCE_CHIP, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/lib/ui-classes";

type Score = { correct: number; answered: number };

const EMPTY_SCORE: Score = { correct: 0, answered: 0 };

export function QuizRunner({ sessionId, quizzes }: { sessionId: string; quizzes: QuizCard[] }) {
  const router = useRouter();
  const [index, setIndex] = useState(0);
  const [chosen, setChosen] = useState<number | null>(null);
  const [score, setScore] = useState<Score>(EMPTY_SCORE);
  const [finished, setFinished] = useState(false);
  const finishedRef = useRef(false);
  const questionHeadingRef = useRef<HTMLHeadingElement>(null);
  const resultHeadingRef = useRef<HTMLHeadingElement>(null);
  const movedRef = useRef(false); // 첫 문제에서는 제목으로 초점을 옮기지 않는다(화면을 막 연 참이라)

  const answer = useMutation({
    mutationFn: ({ quizId, chosenIndex }: { quizId: number; chosenIndex: number }) =>
      submitAnswer(quizId, chosenIndex),
    onSuccess: (result) => {
      setScore((prev) => ({ correct: prev.correct + (result.correct ? 1 : 0), answered: prev.answered + 1 }));
    },
  });
  const { reset: resetAnswer } = answer;

  // 다 푼 뒤 결과로 넘어가 이 화면이 숨겨질 때 처음 상태로 되돌린다(Next 문서 preserving-ui-state.md의 방식).
  useLayoutEffect(() => {
    return () => {
      if (!finishedRef.current) return;
      finishedRef.current = false;
      setIndex(0);
      setChosen(null);
      setScore(EMPTY_SCORE);
      setFinished(false);
      resetAnswer();
    };
  }, [resetAnswer]);

  // 채점이 오면 결과 제목으로, 다음 문제로 넘어가면 문제 제목으로 초점을 옮긴다(화면 읽기 프로그램 · 키보드).
  useEffect(() => {
    if (answer.data) resultHeadingRef.current?.focus();
  }, [answer.data]);
  useEffect(() => {
    if (movedRef.current) questionHeadingRef.current?.focus();
  }, [index]);

  const quiz = quizzes[index];
  const total = quizzes.length;
  const result = answer.data;
  const isLast = index === total - 1;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (chosen === null || answer.isPending || result) return; // 두 번 보내지 않게
    answer.mutate({ quizId: quiz.id, chosenIndex: chosen });
  }

  function handleNext() {
    if (!result) return;
    if (isLast) {
      finishedRef.current = true;
      setFinished(true);
      const params = new URLSearchParams({ correct: String(score.correct), total: String(score.answered) });
      router.push(`/quiz/${sessionId}/result?${params.toString()}`);
      return;
    }
    movedRef.current = true;
    resetAnswer();
    setChosen(null);
    setIndex((prev) => prev + 1);
  }

  if (finished) {
    return (
      <p role="status" className="text-body-2 text-text-sub">
        결과 화면으로 가고 있어요…
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <ProgressBar current={index + 1} total={total} />
      <div className="grid gap-6 lg:grid-cols-12">
        <QuestionForm
          key={quiz.id}
          quiz={quiz}
          chosen={chosen}
          onChoose={setChosen}
          result={result}
          isPending={answer.isPending}
          onSubmit={handleSubmit}
          headingRef={questionHeadingRef}
        />
        <aside aria-label="채점과 해설" className="lg:col-span-5">
          {answer.isPending ? (
            <p role="status" className="text-body-2 text-text-sub">
              채점하고 있어요…
            </p>
          ) : null}
          {answer.error ? <AnswerError error={answer.error} /> : null}
          {result ? (
            <ResultPanel
              quiz={quiz}
              result={result}
              headingRef={resultHeadingRef}
              nextLabel={isLast ? "결과 보기" : "다음 문제"}
              onNext={handleNext}
            />
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function ProgressBar({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-3">
      <div
        role="progressbar"
        aria-label="퀴즈 진행"
        aria-valuemin={1}
        aria-valuemax={total}
        aria-valuenow={current}
        aria-valuetext={`${total}문제 중 ${current}번째`}
        className="h-2 flex-1 overflow-hidden rounded-tag bg-bg-regular"
      >
        <div className="h-full bg-primary-default" style={{ width: `${(current / total) * 100}%` }} />
      </div>
      <span className="text-body-3 text-text-sub">
        {current} / {total}
      </span>
    </div>
  );
}

type QuestionFormProps = {
  quiz: QuizCard;
  chosen: number | null;
  onChoose: (index: number) => void;
  result: AnswerResult | undefined;
  isPending: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
};

function QuestionForm({ quiz, chosen, onChoose, result, isPending, onSubmit, headingRef }: QuestionFormProps) {
  const groupName = useId();
  const locked = isPending || result !== undefined;

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4 lg:col-span-7">
      <p className="text-body-3 text-text-sub">
        {quizKindLabel(quiz.kind)} · {quiz.noteTitle}
        {quiz.inWrongNotes ? " · 오답노트" : ""}
      </p>
      <h2 ref={headingRef} tabIndex={-1} className="text-title-2 font-semibold whitespace-pre-wrap outline-none">
        {quiz.question}
      </h2>
      <fieldset className="flex flex-col gap-2" disabled={locked}>
        <legend className="sr-only">보기</legend>
        {quiz.choices.map((choice, choiceIndex) => {
          const mark = result ? choiceMark(choiceIndex, chosen, result.answerIndex) : null;
          return (
            <label
              key={choiceIndex}
              className={`flex min-h-12 items-center gap-3 rounded-card border bg-bg-default px-4 py-3 text-body-1 has-checked:border-primary-default has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-primary-default ${
                mark === "answer"
                  ? "border-success-base"
                  : mark === "wrong"
                    ? "border-error-base"
                    : "border-line-regular hover:bg-bg-hover"
              }`}
            >
              <input
                type="radio"
                name={groupName}
                value={choiceIndex}
                checked={chosen === choiceIndex}
                onChange={() => onChoose(choiceIndex)}
                className="size-4 accent-primary-default"
              />
              <span className="flex-1 whitespace-pre-wrap">{choice}</span>
              {mark === "answer" ? <span className="text-body-3 font-medium text-success-text">✓ 정답</span> : null}
              {mark === "wrong" ? <span className="text-body-3 font-medium text-error-text">✗ 내 답</span> : null}
            </label>
          );
        })}
      </fieldset>
      {result ? null : (
        <button type="submit" disabled={chosen === null || isPending} className={`${PRIMARY_BUTTON} self-start`}>
          답 내기
        </button>
      )}
    </form>
  );
}

function choiceMark(choiceIndex: number, chosen: number | null, answerIndex: number): "answer" | "wrong" | null {
  if (choiceIndex === answerIndex) return "answer";
  if (choiceIndex === chosen) return "wrong";
  return null;
}

function AnswerError({ error }: { error: Error }) {
  const needsLogin = error instanceof QuizRequestError && error.needsLogin;
  return (
    <div role="alert" className="flex flex-col gap-2">
      <p className="text-body-2 font-medium text-error-text">{error.message}</p>
      {needsLogin ? (
        <Link href="/login" className={`${SECONDARY_BUTTON} self-start`}>
          로그인하러 가기
        </Link>
      ) : (
        <p className="text-body-3 text-text-sub">보기를 다시 고르고 [답 내기]를 눌러 주세요.</p>
      )}
    </div>
  );
}

type ResultPanelProps = {
  quiz: QuizCard;
  result: AnswerResult;
  headingRef: RefObject<HTMLHeadingElement | null>;
  nextLabel: string;
  onNext: () => void;
};

function ResultPanel({ quiz, result, headingRef, nextLabel, onNext }: ResultPanelProps) {
  const answerText = quiz.choices[result.answerIndex] ?? "";
  return (
    <section
      aria-labelledby="quiz-result-title"
      className="flex flex-col gap-4 rounded-card border border-line-regular bg-bg-default p-6"
    >
      <h2
        id="quiz-result-title"
        ref={headingRef}
        tabIndex={-1}
        className={`text-title-3 font-semibold outline-none ${result.correct ? "text-success-text" : "text-error-text"}`}
      >
        {result.correct ? "✓ 맞았어요" : "✗ 틀렸어요"}
      </h2>
      <p className="text-body-2">
        <span className="font-medium">정답</span> {answerText}
      </p>
      <div className="flex flex-col gap-1">
        <h3 className="text-body-2 font-semibold">해설</h3>
        <p className="text-body-2 whitespace-pre-wrap text-text-main">{result.explanation}</p>
      </div>
      <div className="flex flex-col gap-2">
        <h3 className="text-body-2 font-semibold">근거 — 내 기록 원문</h3>
        {/* 내 기록 원문 인용. 명조 글꼴은 Q-018(글꼴 넣기)을 정한 뒤 적용한다. */}
        <blockquote className="border-l-2 border-line-strong pl-3 text-body-2 whitespace-pre-wrap text-text-sub">
          {result.quote}
        </blockquote>
        <Link
          href={evidenceHref(result.noteId, result.chunkId)}
          aria-label={`근거 원문 보기: ${result.noteTitle}`}
          className={`${EVIDENCE_CHIP} self-start`}
        >
          근거 · {result.noteTitle}
        </Link>
      </div>
      <p className="text-body-3 text-text-sub">다음 복습: {formatReviewDate(result.nextReviewOn)}</p>
      <WrongNotesStatus wasInWrongNotes={quiz.inWrongNotes} result={result} />
      <button type="button" onClick={onNext} className={`${PRIMARY_BUTTON} self-start`}>
        {nextLabel}
      </button>
    </section>
  );
}

function WrongNotesStatus({ wasInWrongNotes, result }: { wasInWrongNotes: boolean; result: AnswerResult }) {
  if (!result.correct) {
    return <p className="text-body-3 text-text-sub">오답노트에 넣었어요. 2번 연속 맞히면 빠져요.</p>;
  }
  if (wasInWrongNotes && !result.inWrongNotes) {
    return <p className="text-body-3 text-success-text">2번 연속 맞혀서 오답노트에서 빠졌어요.</p>;
  }
  if (wasInWrongNotes && result.inWrongNotes) {
    return <p className="text-body-3 text-text-sub">복습일에 한 번 더 맞히면 오답노트에서 빠져요.</p>;
  }
  return null;
}
