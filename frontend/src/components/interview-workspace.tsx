"use client";

// APL_02_004 면접 연습 탭(Figma 27:1586): 왼쪽 '예상 질문 N' — 질문 한 줄 목록(질문마다 카드 제목 태그 + 내 답 메모 칸) |
// 오른쪽 '연습 방법' · '선택한 질문의 근거'(카드 칸 글 — 인용 모양).
// Figma에 없지만 완료 기준이라 얹은 것(사용자 선택 2026-11-15): 머리 줄 '답함 N/M', 근거 패널의 '이 카드가 맞는 역량',
// 목록 아래 '질문 없는 카드 N장'(카드 상세로 잇기 — 질문은 카드 상세에서만 만든다, D-006).
// 데이터: 처음은 서버 컴포넌트가 받은 값. 메모를 저장하면 응답으로 그 질문만 바꿔 끼운다(useState — 이 화면에서만 씀, D-012).
// 고른 질문도 이 화면만 쓰는 상태라 useState. 같은 글의 질문은 서버가 합쳐 보내므로(답한 질문 우선) 질문 수 · 답한 수를
// 목록에서 세도 서버 question_count · answered_count와 같은 기준이다 — 메모를 저장할 때마다 바로 바뀌게 목록에서 센다.

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useId, useRef, useState } from "react";
import { SourceQuote } from "@/components/page-parts";
import { RequestErrorText } from "@/components/request-error";
import { cardHref, SLOT_LABELS } from "@/lib/cards";
import {
  type ApplicationInterview,
  INTERVIEW_MEMO_MAX_CHARS,
  type InterviewQuestion,
  type InterviewRow,
  interviewRows,
  updateInterviewMemo,
} from "@/lib/interview";
import { BADGE_LINE, CARD, CARD_LABEL, FOCUS_RING, TEXT_BUTTON } from "@/lib/ui-classes";

export function InterviewWorkspace({ initial }: { initial: ApplicationInterview }) {
  const [data, setData] = useState(initial);
  const rows = interviewRows(data);
  const [selectedId, setSelectedId] = useState<number | null>(rows[0]?.question.id ?? null);
  const selected = rows.find((row) => row.question.id === selectedId) ?? rows[0] ?? null;
  const answered = rows.filter((row) => row.question.answeredAt !== null).length;
  // 합치기 전에도 질문이 없던 카드만 — 다른 카드 쪽으로 모두 합쳐진 카드는 질문이 이미 있어 만들 수 없다(사용자 확인 2026-11-16)
  const cardsWithoutQuestions = data.cards.filter((card) => !card.hasQuestions);
  const cardsWithQuestions = new Set(rows.map((row) => row.card.cardId)).size; // 목록에 실제로 나온 카드 수(1차 리뷰 R4)

  const putQuestion = (saved: InterviewQuestion) =>
    setData((current) => ({
      ...current,
      cards: current.cards.map((card) =>
        card.cardId === saved.cardId
          ? { ...card, questions: card.questions.map((question) => (question.id === saved.id ? saved : question)) }
          : card,
      ),
    }));

  return (
    <div className="grid items-start gap-6 px-5 py-6 lg:grid-cols-12 lg:px-12">
      <section aria-labelledby="interview-title" className={`${CARD} flex flex-col gap-5 lg:col-span-8`}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="interview-title" className="text-title-4 font-semibold text-text-main">
            예상 질문 {rows.length}
            {rows.length > 0 ? (
              <span className="ml-2 text-body-2 font-medium text-text-sub">
                답함 {answered}/{rows.length}
              </span>
            ) : null}
          </h2>
          {rows.length > 0 ? (
            <p className="text-body-3 text-text-sub">
              이 공고에 매칭된 카드 {cardsWithQuestions}장에서 모았어요 · 겹치는 질문은 하나로
            </p>
          ) : null}
        </div>

        {rows.length === 0 ? <EmptyRows data={data} /> : null}

        <ol className="flex flex-col gap-5">
          {rows.map((row) => (
            <QuestionRow
              key={row.question.id}
              row={row}
              selected={selected?.question.id === row.question.id}
              onSelect={() => setSelectedId(row.question.id)}
              onSaved={putQuestion}
            />
          ))}
        </ol>

        {rows.length > 0 && cardsWithoutQuestions.length > 0 ? (
          <div className="flex flex-col gap-2 border-t border-line-light pt-4">
            <p className="text-body-2 font-semibold text-text-main">질문 없는 카드 {cardsWithoutQuestions.length}장</p>
            <p className="text-body-3 text-text-sub">면접 질문은 카드 상세에서 만들어요.</p>
            <CardLinks cards={cardsWithoutQuestions} />
          </div>
        ) : null}
      </section>

      <div className="flex flex-col gap-4 lg:col-span-4">
        <section aria-labelledby="interview-howto" className={`${CARD} flex flex-col gap-3`}>
          <h2 id="interview-howto" className={CARD_LABEL}>
            연습 방법
          </h2>
          <p className="text-body-2 text-text-main">
            질문마다 카드의 상황 · 행동 · 결과 순서로 1분 안에 말해 보세요. 답 메모는 나만 봐요.
          </p>
        </section>
        {selected ? <EvidencePanel row={selected} /> : null}
      </div>
    </div>
  );
}

function EmptyRows({ data }: { data: ApplicationInterview }) {
  if (!data.analysisDone) {
    return (
      <div role="status" className="flex flex-col gap-2">
        <p className="text-body-2 text-text-main">공고 분석에서 내 카드를 매칭하면, 그 카드의 면접 질문을 여기에 모아 보여 줘요.</p>
        <Link href={`/applications/${data.applicationId}/analysis`} className={`${TEXT_BUTTON} self-start underline`}>
          공고 분석으로
        </Link>
      </div>
    );
  }
  if (data.cards.length === 0) {
    return (
      <p role="status" className="text-body-2 text-text-main">
        이 공고에 매칭된 경험 카드가 없어요. 카드를 만든 뒤 공고 분석에서 [매칭 다시]를 눌러 주세요.
      </p>
    );
  }
  return (
    <div role="status" className="flex flex-col gap-2">
      <p className="text-body-2 text-text-main">
        매칭된 카드 {data.cards.length}장에 아직 면접 질문이 없어요. 카드 상세에서 [면접 질문 만들기]를 눌러 주세요.
      </p>
      <CardLinks cards={data.cards} />
    </div>
  );
}

function CardLinks({ cards }: { cards: ApplicationInterview["cards"] }) {
  return (
    <ul className="flex flex-wrap gap-2">
      {cards.map((card) => (
        <li key={card.cardId}>
          <Link href={cardHref(card.cardId)} className={`${BADGE_LINE} hover:underline ${FOCUS_RING}`}>
            {card.cardTitle}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function QuestionRow({
  row,
  selected,
  onSelect,
  onSaved,
}: {
  row: InterviewRow;
  selected: boolean;
  onSelect: () => void;
  onSaved: (saved: InterviewQuestion) => void;
}) {
  const memoId = useId();
  const { question, card } = row;
  const [memo, setMemo] = useState(question.memo ?? "");
  // 저장하는 동안 이어서 쓴 글을 지킨다(1차 리뷰 R3): 응답은 보낸 글과 지금 글이 같을 때만 칸에 넣고,
  // 저장 중에 칸을 벗어나 건너뛴 글은 저장이 끝난 뒤 한 번 더 보낸다. 최신 글은 ref로 읽는다(응답 콜백의 오래된 값 대신).
  const latest = useRef(memo);
  const updateMemo = (value: string) => {
    latest.current = value;
    setMemo(value);
  };
  const save = useMutation({
    mutationFn: (value: string) => updateInterviewMemo(question.id, value),
    onSuccess: (saved, sent) => {
      onSaved(saved);
      if (latest.current === sent) {
        updateMemo(saved.memo ?? "");
      } else if (latest.current.trim() !== (saved.memo ?? "")) {
        save.mutate(latest.current);
      }
    },
  });
  const changed = memo.trim() !== (question.memo ?? "");

  return (
    <li className="flex flex-col gap-3" aria-current={selected ? "true" : undefined}>
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-body-1 font-semibold text-text-main">
          <button type="button" onClick={onSelect} className={`text-left hover:underline ${FOCUS_RING}`}>
            {question.question}
          </button>
        </h3>
        <Link href={cardHref(card.cardId)} className={`${BADGE_LINE} shrink-0 hover:underline ${FOCUS_RING}`}>
          {card.cardTitle}
        </Link>
      </div>
      <label htmlFor={memoId} className="sr-only">
        {`${question.question} — 내 답 메모`}
      </label>
      <textarea
        id={memoId}
        value={memo}
        rows={2}
        maxLength={INTERVIEW_MEMO_MAX_CHARS}
        placeholder="내 답 메모 — 말할 순서만 적어도 돼요"
        onFocus={onSelect}
        onChange={(event) => updateMemo(event.target.value)}
        onBlur={() => {
          if (changed && !save.isPending) save.mutate(memo);
        }}
        className={`rounded-input border bg-bg-default p-3 text-body-1 text-text-main placeholder:text-text-sub-weak ${
          selected ? "border-line-black" : "border-line-input hover:border-line-input-hover"
        } ${FOCUS_RING}`}
      />
      {save.isPending ? (
        <p role="status" className="text-body-3 text-text-sub">
          저장하는 중…
        </p>
      ) : save.error ? (
        <RequestErrorText error={save.error} />
      ) : save.isSuccess && !changed ? (
        <p role="status" className="text-body-3 text-success-text">
          ✓ 메모를 저장했어요.
        </p>
      ) : null}
    </li>
  );
}

function EvidencePanel({ row }: { row: InterviewRow }) {
  const { question, card } = row;
  const source = [card.cardTitle, SLOT_LABELS[question.slot], question.quoteSource === "answer" ? "내 답" : card.noteTitle ?? "원문 없음"]
    .filter(Boolean)
    .join(" · ");
  return (
    <section aria-labelledby="interview-evidence" className={`${CARD} flex flex-col gap-3`}>
      <h2 id="interview-evidence" className={CARD_LABEL}>
        선택한 질문의 근거
      </h2>
      <SourceQuote quote={question.quote} source={<Link href={cardHref(card.cardId)} className="underline">{source}</Link>} />
      {question.evidenceStatus !== "ok" ? (
        <p role="note" className="text-body-3 font-medium text-warning-text">
          {question.evidenceStatus === "changed"
            ? "카드 글이 바뀌어 이 인용을 찾을 수 없어요. 질문을 연습하기 전에 카드를 확인해 주세요."
            : "근거 카드를 찾을 수 없어요."}
        </p>
      ) : null}
      {card.requirementNames.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-body-3 text-text-sub">이 카드가 맞는 역량</p>
          <ul className="flex flex-wrap gap-2">
            {card.requirementNames.map((name) => (
              <li key={name} className={BADGE_LINE}>
                {name}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
