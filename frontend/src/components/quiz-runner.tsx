"use client";

// REV_02_001 퀴즈(집중 모드, Figma 26:804)의 문제 풀기 부분 — 위쪽 띠("4 / 12" · 진행 막대)와 본문 제목까지 그린다. 문제 목록은 서버 컴포넌트가 시작할 때 한 번 받아 넘긴다.
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
import { RequestErrorBlock } from "@/components/request-error";
import {
  type AnswerResult,
  evidenceHref,
  formatReviewDate,
  type QuizCard,
  quizKindLabel,
  submitAnswer,
} from "@/lib/quiz";
import { FocusTitle, FocusTopBar } from "@/components/focus-top-bar";
import { Icon } from "@/components/icon";
import { SourceQuote } from "@/components/page-parts";
import { BADGE_LINE, BADGE_SOFT, CARD, CARD_LABEL, PRIMARY_BUTTON_L } from "@/lib/ui-classes";

type Score = { correct: number; answered: number };

const EMPTY_SCORE: Score = { correct: 0, answered: 0 };

type QuizRunnerProps = {
  sessionId: string;
  title: string;
  titleId: string;
  notice: string | null; // 문제가 상한보다 많아 일부만 푼다는 안내
  quizzes: QuizCard[];
};

export function QuizRunner({ sessionId, title, titleId, notice, quizzes }: QuizRunnerProps) {
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
      <>
        <FocusTopBar />
        <div className="flex flex-col gap-6 px-5 py-10 lg:px-12">
          <FocusTitle id={titleId}>{title}</FocusTitle>
          <p role="status" className="text-body-2 text-text-sub">
            결과 화면으로 가고 있어요…
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      <FocusTopBar counter={`${index + 1} / ${total}`} progress={{ current: index + 1, total }} />
      <div className="flex flex-col gap-6 px-5 py-10 lg:px-12">
        {/* 제목(Figma 59:1478) — 노트 하나면 노트 제목, 오늘 복습 · 오답노트면 세션 이름 */}
        <FocusTitle id={titleId}>{title}</FocusTitle>
        {notice ? <p className="text-body-3 text-text-sub">{notice}</p> : null}
        {/* 문제 7 + 해설 5(didim-design.md 4장 퀴즈 그리드) */}
        <div className="grid items-start gap-6 lg:grid-cols-12">
          <QuestionForm
            key={quiz.id}
            quiz={quiz}
            chosen={chosen}
            onChoose={setChosen}
            result={result}
            isPending={answer.isPending}
            onSubmit={handleSubmit}
            headingRef={questionHeadingRef}
            nextLabel={isLast ? "결과 보기" : "다음 문제"}
            onNext={handleNext}
          />
          <aside aria-label="채점과 해설" className="lg:col-span-5">
            {answer.isPending ? (
              <p role="status" className="text-body-2 text-text-sub">
                채점하고 있어요…
              </p>
            ) : null}
            {answer.error ? (
              <RequestErrorBlock
                error={answer.error}
                hint={<p className="text-body-3 text-text-sub">보기를 다시 고르고 [답 내기]를 눌러 주세요.</p>}
              />
            ) : null}
            {result ? <ResultPanel quiz={quiz} result={result} headingRef={resultHeadingRef} /> : null}
          </aside>
        </div>
      </div>
    </>
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
  nextLabel: string;
  onNext: () => void;
};

// 보기 한 칸(Figma 26:823~): 기본 1px line/regular. 채점 뒤 정답 = 2px success/text + icon/success "정답",
// 내가 고른 오답 = 2px error/text + icon/error "내 답 · 틀림"(색만으로 알리지 않게 글자를 같이 둔다).
const CHOICE_BASE =
  "flex items-center gap-3 rounded-button bg-bg-default p-4 text-body-1 text-text-main has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-primary-default";
const CHOICE_STATE = {
  open: "border border-line-regular hover:bg-bg-hover has-checked:border-primary-default",
  answer: "border-2 border-success-text",
  wrong: "border-2 border-error-text",
  other: "border border-line-regular",
} as const;

function QuestionForm({
  quiz,
  chosen,
  onChoose,
  result,
  isPending,
  onSubmit,
  headingRef,
  nextLabel,
  onNext,
}: QuestionFormProps) {
  const groupName = useId();
  const locked = isPending || result !== undefined;

  return (
    <form onSubmit={onSubmit} className={`${CARD} flex flex-col gap-5 lg:col-span-7 lg:p-8`}>
      <div className="flex flex-wrap items-center gap-1">
        <span className={BADGE_SOFT}>{quizKindLabel(quiz.kind)}</span>
        {quiz.inWrongNotes ? <span className={BADGE_LINE}>오답노트</span> : null}
        {/* 여러 노트가 섞인 세션(오늘 복습 · 오답노트)에서 이 문제가 어느 노트에서 왔는지(근거 우선, 원칙 1) */}
        <span className="ml-1 truncate text-body-4 text-text-sub">{quiz.noteTitle}</span>
      </div>
      <h2
        ref={headingRef}
        tabIndex={-1}
        className="text-title-2 font-semibold whitespace-pre-wrap text-text-main outline-none"
      >
        {quiz.question}
      </h2>
      <fieldset className="flex flex-col gap-5" disabled={locked}>
        <legend className="sr-only">보기</legend>
        {quiz.choices.map((choice, choiceIndex) => {
          const mark = result ? choiceMark(choiceIndex, chosen, result.answerIndex) : null;
          const state = result ? (mark ?? "other") : "open";
          return (
            <label key={choiceIndex} className={`${CHOICE_BASE} ${CHOICE_STATE[state]}`}>
              <input
                type="radio"
                name={groupName}
                value={choiceIndex}
                checked={chosen === choiceIndex}
                onChange={() => onChoose(choiceIndex)}
                // Figma Radio M 20: 빈 원 = line/input 테두리, 고른 원 = primary/default 굵은 테두리(가운데 흰 점).
                // 브라우저 기본 모양을 끄고 직접 그린다 — 채점 뒤 보기가 잠겨도(disabled) 회색으로 바뀌지 않게
                className="size-5 shrink-0 appearance-none rounded-full border-2 border-line-input bg-bg-default checked:border-6 checked:border-primary-default"
              />
              <span className="flex-1 whitespace-pre-wrap">{choice}</span>
              {mark === "answer" ? (
                <span className="flex shrink-0 items-center gap-1 text-body-3 font-semibold text-success-text">
                  <Icon name="success" size={20} />
                  정답
                </span>
              ) : null}
              {mark === "wrong" ? (
                <span className="flex shrink-0 items-center gap-1 text-body-3 font-semibold text-error-text">
                  <Icon name="error" size={20} />내 답 · 틀림
                </span>
              ) : null}
            </label>
          );
        })}
      </fieldset>
      <div className="flex justify-end">
        {result ? (
          <button type="button" onClick={onNext} className={PRIMARY_BUTTON_L}>
            {nextLabel}
          </button>
        ) : (
          <button type="submit" disabled={chosen === null || isPending} className={PRIMARY_BUTTON_L}>
            답 내기
          </button>
        )}
      </div>
    </form>
  );
}

function choiceMark(choiceIndex: number, chosen: number | null, answerIndex: number): "answer" | "wrong" | null {
  if (choiceIndex === answerIndex) return "answer";
  if (choiceIndex === chosen) return "wrong";
  return null;
}

type ResultPanelProps = {
  quiz: QuizCard;
  result: AnswerResult;
  headingRef: RefObject<HTMLHeadingElement | null>;
};

// 해설 칸(Figma 26:863): 해설 → 내 기록 원문 인용(명조) + 출처 링크 → 다음 복습 · 오답노트 안내.
// 맞았는지는 보기 칸이 보여 주고, 제목에는 화면 읽기 프로그램용으로만 붙인다(채점 뒤 초점이 이 제목으로 온다).
function ResultPanel({ quiz, result, headingRef }: ResultPanelProps) {
  return (
    <section aria-labelledby="quiz-result-title" className={`${CARD} flex flex-col gap-4`}>
      <h2 id="quiz-result-title" ref={headingRef} tabIndex={-1} className={`${CARD_LABEL} outline-none`}>
        <span className="sr-only">{result.correct ? "맞았어요 · " : "틀렸어요 · "}</span>
        해설
      </h2>
      <p className="text-body-1 whitespace-pre-wrap text-text-main">{result.explanation}</p>
      <SourceQuote
        quote={result.quote}
        source={
          <Link
            href={evidenceHref(result.noteId, result.chunkId)}
            aria-label={`근거 원문 보기: ${result.noteTitle}`}
            className="underline-offset-2 hover:text-text-main hover:underline"
          >
            내 노트 · {result.noteTitle}
          </Link>
        }
      />
      <div className="flex flex-col gap-1">
        <p className="text-body-3 text-text-sub">다음 복습: {formatReviewDate(result.nextReviewOn)}</p>
        <WrongNotesStatus wasInWrongNotes={quiz.inWrongNotes} result={result} />
      </div>
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
