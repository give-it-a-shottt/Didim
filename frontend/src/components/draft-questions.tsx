"use client";

// APL_02_003 왼쪽 칸(Figma 18:256 '문항 · 카드', 너비 304): 문항 목록(Didim/문항 항목 — 글자 수 · 상태 배지) + 경험 카드(검색 · 이 문항에 연결됨).
// [문항 고치기]로 문항을 추가 · 수정 · 삭제한다(설계 의도 ④ — 초안 있는 문항을 지우면 초안도 같이, 확인창).

import Link from "next/link";
import { useId, useRef, useState } from "react";
import { CardSearchInput } from "@/components/card-search-input";
import { Icon } from "@/components/icon";
import { RequestErrorText } from "@/components/request-error";
import { APPLICATION_MAX_QUESTIONS, APPLICATION_QUESTION_CHAR_LIMIT_MAX, APPLICATION_QUESTION_MAX_CHARS } from "@/lib/applications";
import { type CardSummary, cardHref, filterCardsByTitle, formatCardDate } from "@/lib/cards";
import { type DraftQuestion, type QuestionEdit, type RequestState, charCountLabel, questionStage } from "@/lib/drafts";
import { BADGE_SOFT, FOCUS_RING, SECTION_TITLE, GHOST_BUTTON_S, SECONDARY_BUTTON_S, TEXT_BUTTON } from "@/lib/ui-classes";

/** 문항 목록 저장 요청: run(고친 문항, 지울 기존 문항 번호, 성공하면 부를 함수) + 오류 지우기. */
export type QuestionsSave = RequestState<(edits: QuestionEdit[], removedIds: number[], onDone: () => void) => void> & {
  reset: () => void;
};

const PANEL = "flex w-full flex-col gap-5 rounded-card border border-line-regular bg-bg-default p-4 lg:w-76 lg:shrink-0";

export function DraftQuestions({
  questions,
  selectedQuestionId,
  onSelect,
  saveQuestions,
  cards,
  matchedCardIds,
  usedCardIds,
}: {
  questions: DraftQuestion[];
  selectedQuestionId: number | null;
  onSelect: (questionId: number) => void;
  saveQuestions: QuestionsSave;
  cards: CardSummary[] | null;
  matchedCardIds: number[];
  usedCardIds: Set<number>;
}) {
  const [editing, setEditing] = useState(false);

  return (
    <div className={PANEL}>
      <section aria-labelledby="draft-questions-title" className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <h3 id="draft-questions-title" className={SECTION_TITLE}>
            문항
          </h3>
          <div className="flex-1" />
          {editing ? null : (
            <button type="button" onClick={() => setEditing(true)} className={TEXT_BUTTON}>
              문항 고치기
            </button>
          )}
        </div>
        {editing ? (
          <QuestionForm
            questions={questions}
            saveQuestions={saveQuestions}
            onDone={() => {
              setEditing(false);
              saveQuestions.reset();
            }}
          />
        ) : questions.length === 0 ? (
          <p className="py-2 text-body-3 text-text-sub">문항이 없어요. [문항 고치기]로 자소서 문항을 넣어 주세요.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {questions.map((question, index) => (
              <li key={question.id}>
                <QuestionItem
                  question={question}
                  number={index + 1}
                  selected={question.id === selectedQuestionId}
                  onSelect={() => onSelect(question.id)}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      <div aria-hidden="true" className="h-px bg-line-regular" />

      <CardList cards={cards} matchedCardIds={matchedCardIds} usedCardIds={usedCardIds} />
    </div>
  );
}

/** Figma Didim/문항 항목(17:330): 제목 + 글자 수, 오른쪽 상태 배지. 고른 문항 = 왼쪽 2px 검정 줄 + SemiBold. */
function QuestionItem({
  question,
  number,
  selected,
  onSelect,
}: {
  question: DraftQuestion;
  number: number;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={`flex w-full items-center gap-2 rounded-button px-3 py-2 text-left hover:bg-bg-hover ${
        selected ? "border-l-2 border-line-black" : ""
      } ${FOCUS_RING}`}
    >
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className={`line-clamp-2 text-body-2 text-text-main ${selected ? "font-semibold" : "font-medium"}`}>
          {number}. {question.text}
        </span>
        <span className="text-body-4 text-text-sub">{charCountLabel(question.draft?.chars ?? 0, question.charLimit)}</span>
      </span>
      <span className={BADGE_SOFT}>{questionStage(question)}</span>
    </button>
  );
}

type QuestionRow = { key: number; id: number | null; text: string; charLimit: string; hasDraft: boolean };

/** 문항 추가 · 수정 · 삭제. [저장]하면 목록을 통째로 보낸다(PUT /api/applications/{id}/questions). */
function QuestionForm({
  questions,
  saveQuestions,
  onDone,
}: {
  questions: DraftQuestion[];
  saveQuestions: QuestionsSave;
  onDone: () => void;
}) {
  const ids = useId();
  const nextKey = useRef(questions.length);
  const [rows, setRows] = useState<QuestionRow[]>(() =>
    questions.map((item, index) => ({
      key: index,
      id: item.id,
      text: item.text,
      charLimit: item.charLimit === null ? "" : String(item.charLimit),
      hasDraft: item.draft !== null,
    })),
  );

  const update = (key: number, patch: Partial<QuestionRow>) =>
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  const submit = () => {
    const removedWithDraft = questions.filter((item) => item.draft !== null && !rows.some((row) => row.id === item.id)).length;
    if (removedWithDraft > 0 && !window.confirm(`초안이 있는 문항 ${removedWithDraft}개를 지우면 초안도 같이 지워져요. 지울까요?`)) {
      return;
    }
    // 지울 문항은 직접 보낸다 — 서버가 '보낸 + 지울 = 지금 목록'인지 확인해 다른 탭의 변경을 모르고 지우지 않게(2차 리뷰 R2)
    const removedIds = questions.filter((item) => !rows.some((row) => row.id === item.id)).map((item) => item.id);
    saveQuestions.run(
      rows.map((row) => ({ id: row.id, text: row.text, charLimit: row.charLimit ? Number(row.charLimit) : null })),
      removedIds,
      onDone,
    );
  };

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {rows.map((row, index) => (
        <fieldset key={row.key} className="flex flex-col gap-2 rounded-button border border-line-regular p-3">
          <legend className="sr-only">{index + 1}번 문항</legend>
          <label htmlFor={`${ids}-text-${row.key}`} className="text-body-3 font-medium text-text-main">
            {index + 1}번 문항
          </label>
          <textarea
            id={`${ids}-text-${row.key}`}
            value={row.text}
            required
            maxLength={APPLICATION_QUESTION_MAX_CHARS}
            rows={2}
            onChange={(event) => update(row.key, { text: event.target.value })}
            className={`w-full resize-y rounded-input border border-line-input bg-bg-default px-3 py-2 text-body-2 text-text-main hover:border-line-input-hover ${FOCUS_RING}`}
          />
          <div className="flex items-center gap-2">
            <label htmlFor={`${ids}-limit-${row.key}`} className="text-body-3 text-text-sub">
              글자 수 제한
            </label>
            <input
              id={`${ids}-limit-${row.key}`}
              type="number"
              inputMode="numeric"
              min={1}
              max={APPLICATION_QUESTION_CHAR_LIMIT_MAX}
              value={row.charLimit}
              placeholder="없음"
              onChange={(event) => update(row.key, { charLimit: event.target.value })}
              className={`h-8 w-20 rounded-input border border-line-input bg-bg-default px-2 text-body-2 text-text-main hover:border-line-input-hover ${FOCUS_RING}`}
            />
            <div className="flex-1" />
            <button
              type="button"
              onClick={() => setRows((current) => current.filter((item) => item.key !== row.key))}
              className={TEXT_BUTTON}
            >
              지우기
            </button>
          </div>
          {row.hasDraft && row.id !== null ? <p className="text-body-4 text-text-sub-weak">초안이 있어요. 지우면 초안도 같이 지워져요.</p> : null}
        </fieldset>
      ))}
      {rows.length < APPLICATION_MAX_QUESTIONS ? (
        <button
          type="button"
          onClick={() => {
            const key = nextKey.current++;
            setRows((current) => [...current, { key, id: null, text: "", charLimit: "", hasDraft: false }]);
          }}
          className={`${GHOST_BUTTON_S} self-start`}
        >
          <Icon name="plus" size={16} />
          문항 추가
        </button>
      ) : null}
      {saveQuestions.error ? <RequestErrorText error={saveQuestions.error} /> : null}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onDone} disabled={saveQuestions.pending} className={GHOST_BUTTON_S}>
          취소
        </button>
        <button type="submit" disabled={saveQuestions.pending} className={SECONDARY_BUTTON_S}>
          {saveQuestions.pending ? "저장하는 중…" : "저장"}
        </button>
      </div>
    </form>
  );
}

/** 경험 카드(Figma 18:280): 이 문항에 근거로 쓴 카드 → 이 공고에 매칭된 카드 → 나머지 순. 제목으로 검색. */
function CardList({
  cards,
  matchedCardIds,
  usedCardIds,
}: {
  cards: CardSummary[] | null;
  matchedCardIds: number[];
  usedCardIds: Set<number>;
}) {
  const [search, setSearch] = useState("");
  const rank = (card: CardSummary) => (usedCardIds.has(card.id) ? 0 : matchedCardIds.includes(card.id) ? 1 : 2);
  const shown = filterCardsByTitle(cards ?? [], search).sort((a, b) => rank(a) - rank(b));

  return (
    <section aria-labelledby="draft-cards-title" className="flex flex-col gap-2">
      <div className="flex items-center">
        <h3 id="draft-cards-title" className={SECTION_TITLE}>
          경험 카드
        </h3>
        <div className="flex-1" />
        <p className="text-body-4 text-text-sub">근거로 쓴 카드 {usedCardIds.size}</p>
      </div>
      {cards === null ? (
        <p role="alert" className="text-body-3 text-error-text">
          카드 목록을 불러오지 못했어요.
        </p>
      ) : (
        <>
          <CardSearchInput value={search} onChange={setSearch} />
          {shown.length === 0 ? (
            <p className="text-body-3 text-text-sub">{search.trim() ? "찾는 카드가 없어요." : "저장한 경험 카드가 없어요."}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {shown.map((card) => (
                <li key={card.id}>
                  <Link
                    href={cardHref(card.id)}
                    className={`flex flex-col gap-1 rounded-card border border-line-regular bg-bg-default p-3 hover:bg-bg-hover ${FOCUS_RING}`}
                  >
                    <span className="text-body-3 font-semibold text-text-main">{card.title}</span>
                    <span className="text-body-4 text-text-sub">
                      근거 {card.evidenceCount} · 빈칸 {card.blankCount} · {formatCardDate(card.updatedAt)} 수정
                    </span>
                    {usedCardIds.has(card.id) ? (
                      <span className="flex items-center gap-1 text-body-4 font-medium text-primary-text">
                        <Icon name="check" size={16} />이 문항에 연결됨
                      </span>
                    ) : matchedCardIds.includes(card.id) ? (
                      <span className="text-body-4 text-text-sub-weak">이 공고에 매칭됨</span>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
