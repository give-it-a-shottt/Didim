"use client";

// 카드 상세 · 편집(CRD_01_002, Figma 27:892 main 27:937). 서버 컴포넌트가 카드를 받아 넘기고, 고치는 일은 여기서 한다.
// - 칸마다: 원문 인용(고칠 수 없음 · [인용 빼기]) + 내 답(덧붙이기). 빈칸이면 노란 테두리 + AI 빈칸 질문.
// - [저장] = 바뀐 칸의 답을 저장(PUT) → 제목 확인 · 후보면 카드로 저장(POST save). 인용 빼기 · 지우기는 바로 보낸다.
// 카드 내용은 받은 응답으로 바꿔 끼우고(useState), 입력 중인 글도 useState — 이 화면에서만 쓰여서(D-012).
// 서버 수정은 useMutation. 저장 뒤 router.refresh()로 사이드바 · 목록 같은 서버 화면을 새로 받는다.
//
// - [면접 질문 만들기](F-009): 저장 카드에서 한 번(사용자 확인 2026-11-15). 만든 뒤 카드를 다시 받아 '이 카드의 면접 질문'을 채운다.
//   질문이 이미 있거나 후보 카드면 버튼을 두지 않고 오른쪽 칸에서 안내한다(Figma는 버튼이 늘 있음 — 다시 만들기는 2차 후보).
// Figma와 다르게 둔 것(기능 · 데이터 없음): '원문이 고쳐졌어요 · 다시 반영'(노트는 고칠 수 없음), '노트 연결'(근거 직접 붙이기 —
// 이번 범위 밖). 칸 글은 입력 칸 대신 인용 + 내 답으로 나눴다(D-003).

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { CardQuote } from "@/components/card-parts";
import { RequestErrorText } from "@/components/request-error";
import { Icon } from "@/components/icon";
import { PageBody, PageHeader, SourceQuote } from "@/components/page-parts";
import {
  CARD_MAX_ANSWER_CHARS,
  CARD_SLOTS,
  CARD_TITLE_MAX_CHARS,
  type CardDetail,
  type CardField,
  type CardSlot,
  deleteCard,
  fetchCard,
  formatCardDate,
  isBlank,
  SLOT_LABELS,
  saveCard,
  updateField,
  writeInterviewQuestions,
} from "@/lib/cards";
import { ApiRequestError } from "@/lib/api-request";
import { INTERVIEW_MAX_QUESTIONS, INTERVIEW_MIN_QUESTIONS, type InterviewQuestion } from "@/lib/interview";
import { evidenceHref } from "@/lib/quiz";
import {
  BADGE_LINE,
  CARD,
  CARD_LABEL,
  FOCUS_RING,
  GHOST_BUTTON,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
  SOURCE_LINK,
  TEXT_BUTTON,
} from "@/lib/ui-classes";

type Drafts = Record<CardSlot, string>;

function draftsOf(card: CardDetail): Drafts {
  const drafts = { situation: "", task: "", action: "", result: "" };
  for (const field of card.fields) drafts[field.slot] = field.answer ?? "";
  return drafts;
}

const FORM_ID = "card-edit-form";

export function CardEditor({ initial }: { initial: CardDetail }) {
  const router = useRouter();
  const titleId = useId();
  const [card, setCard] = useState(initial);
  const [title, setTitle] = useState(initial.title);
  const [drafts, setDrafts] = useState<Drafts>(() => draftsOf(initial));
  const isCandidate = card.status === "candidate";

  const changedSlots = card.fields.filter((field) => drafts[field.slot].trim() !== (field.answer ?? ""));

  const save = useMutation({
    mutationFn: async () => {
      // 칸마다 차례로 보낸다(한 칸이 실패하면 거기서 멈추고 오류를 보여 줌 — 앞 칸은 이미 저장됨).
      // 저장된 칸은 그때그때 응답으로 화면의 카드를 바꿔서, 중간에 실패해도 빈칸 수 · 바뀐 칸이 서버와 같게(F-006 1차 리뷰 R3).
      // 입력 중인 답(drafts)은 그대로 둔다 — 실패한 칸 이후의 입력을 잃지 않게.
      for (const field of changedSlots) {
        setCard(await updateField(card.id, field.slot, { answer: drafts[field.slot] }));
      }
      return saveCard(card.id, title);
    },
    onSuccess: (saved) => {
      setCard(saved);
      setTitle(saved.title);
      setDrafts(draftsOf(saved));
      router.refresh();
    },
  });

  const removeQuote = useMutation({
    mutationFn: (slot: CardSlot) => updateField(card.id, slot, { answer: drafts[slot], removeQuote: true }),
    onSuccess: (updated) => {
      setCard(updated);
      router.refresh();
    },
  });

  const discard = useMutation({
    mutationFn: () => deleteCard(card.id),
    onSuccess: () => {
      router.push(isCandidate ? "/cards?tab=candidate" : "/cards");
      router.refresh();
    },
  });

  // [면접 질문 만들기] — 서버는 저장된 칸 글만 보낸다. 만든 뒤 카드를 다시 받아 질문 목록을 채운다(입력 중인 답은 그대로).
  // 만들기와 다시 받기를 나눈다 — 질문은 저장됐는데 다시 받기만 실패하면 '실패'가 아니라 새로 고침 안내(1차 리뷰 R1 · R3).
  // 409(이미 질문 있음 — 다른 탭에서 먼저 만듦)면 카드를 다시 받아 그 질문을 보여 준다.
  const [refreshFailed, setRefreshFailed] = useState(false);
  const reloadCard = () =>
    fetchCard(card.id).then(
      (fresh) => setCard(fresh),
      () => setRefreshFailed(true),
    );
  const makeQuestions = useMutation({
    mutationFn: () => writeInterviewQuestions(card.id),
    onMutate: () => setRefreshFailed(false),
    onSuccess: (result) => (result.written ? reloadCard() : undefined),
    onError: (failure) => {
      if (failure instanceof ApiRequestError && failure.status === 409) void reloadCard();
    },
  });

  const isBusy = save.isPending || removeQuote.isPending || discard.isPending || makeQuestions.isPending;
  const error = save.error ?? removeQuote.error ?? discard.error ?? makeQuestions.error;
  const makeState = makeStateOf(card, changedSlots.length > 0);
  const quoted = card.fields.filter((field) => field.quote !== null);
  const blankNow = card.fields.filter((field) => field.quote === null && drafts[field.slot].trim() === "").length;

  return (
    <>
      <PageHeader
        titleId="card-title"
        title={card.title}
        description={[
          isCandidate ? "검토 전 후보" : blankNow === 0 ? "완성" : `빈칸 ${blankNow}`,
          card.noteTitle ?? "원문 없음",
          `${formatCardDate(card.updatedAt)} 수정`,
        ].join(" · ")}
        actions={
          <>
            {makeState === "ready" || makeState === "unsaved" ? (
              <button
                type="button"
                disabled={isBusy || makeState === "unsaved"}
                title={makeState === "unsaved" ? "고친 칸을 먼저 저장해 주세요" : undefined}
                onClick={() => makeQuestions.mutate()}
                className={SECONDARY_BUTTON}
              >
                {makeQuestions.isPending ? "질문 만드는 중…" : "면접 질문 만들기"}
              </button>
            ) : null}
            <button
              type="button"
              disabled={isBusy}
              onClick={() => {
                // 면접 질문 · 메모도 CASCADE로 같이 지워진다 — 질문이 있으면 그렇게 알린다(사용자 확인 2026-11-16, 2차 리뷰 R4)
                const message = isCandidate
                  ? "이 후보를 버릴까요?"
                  : card.interviewQuestions.length > 0
                    ? "이 카드를 지울까요? 내가 쓴 답과 면접 질문 · 메모도 같이 지워져요."
                    : "이 카드를 지울까요? 내가 쓴 답도 같이 지워져요.";
                if (window.confirm(message)) discard.mutate();
              }}
              className={GHOST_BUTTON}
            >
              {isCandidate ? "버리기" : "카드 지우기"}
            </button>
            <button type="submit" form={FORM_ID} disabled={isBusy || title.trim() === ""} className={PRIMARY_BUTTON}>
              {save.isPending ? "저장하는 중…" : isCandidate ? "카드로 저장" : "저장"}
            </button>
          </>
        }
      />
      <PageBody>
        {save.isSuccess && !save.isPending ? (
          <p role="status" className="text-body-2 font-medium text-success-text">
            ✓ 저장했어요.
          </p>
        ) : null}
        {makeQuestions.data && !makeQuestions.isPending ? (
          <p role="status" className="text-body-2 font-medium text-text-main">
            {interviewResultText(makeQuestions.data.written, makeQuestions.data.questions)}
          </p>
        ) : null}
        {/* 만든 뒤 · 409 뒤 어느 쪽이든 카드 다시 받기가 실패하면 알린다(409는 data가 없어 위 문단에 붙이면 안 보임 — 3차 리뷰 R3) */}
        {refreshFailed && !makeQuestions.isPending ? (
          <p role="status" className="text-body-2 font-medium text-text-main">
            질문 목록을 불러오지 못했어요. 새로 고침해 확인해 주세요.
          </p>
        ) : null}
        {error ? <RequestErrorText error={error} /> : null}

        <div className="grid items-start gap-6 lg:grid-cols-12">
          <form
            id={FORM_ID}
            aria-label="카드 내용"
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate();
            }}
            className={`${CARD} flex flex-col gap-5 lg:col-span-8`}
          >
            <div className="flex flex-col gap-2">
              <label htmlFor={titleId} className="text-body-2 font-semibold text-text-main">
                카드 제목
              </label>
              <input
                id={titleId}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                maxLength={CARD_TITLE_MAX_CHARS}
                required
                className={`h-10 rounded-input border border-line-input bg-bg-default px-3 text-body-1 text-text-main hover:border-line-input-hover ${FOCUS_RING}`}
              />
            </div>

            {CARD_SLOTS.map((slot) => {
              const field = card.fields.find((item) => item.slot === slot);
              return field ? (
                <SlotEditor
                  key={slot}
                  field={field}
                  noteId={card.noteId}
                  draft={drafts[slot]}
                  disabled={isBusy}
                  onDraft={(value) => setDrafts((current) => ({ ...current, [slot]: value }))}
                  onRemoveQuote={() => {
                    if (window.confirm(`${SLOT_LABELS[slot]} 칸의 인용을 뺄까요? 이 칸의 근거가 사라져요.`)) {
                      removeQuote.mutate(slot);
                    }
                  }}
                />
              ) : null;
            })}
          </form>

          <div className="flex flex-col gap-4 lg:col-span-4">
            <aside aria-labelledby="card-evidence-title" className={`${CARD} flex flex-col gap-3`}>
              <h2 id="card-evidence-title" className={CARD_LABEL}>
                근거 {quoted.length}
              </h2>
              {quoted.length === 0 ? (
                <p className="text-body-2 text-text-sub">원문 인용이 없어요. 내가 쓴 답만 남아 있어요.</p>
              ) : (
                quoted.map((field) => (
                  <SourceQuote
                    key={field.slot}
                    quote={field.quote ?? ""}
                    source={<EvidenceSource field={field} noteId={card.noteId} noteTitle={card.noteTitle} />}
                  />
                ))
              )}
            </aside>
            <InterviewQuestions questions={card.interviewQuestions} makeState={makeState} />
          </div>
        </div>
      </PageBody>
    </>
  );
}

/** [면접 질문 만들기] 결과 문구. 근거가 맞는 질문이 적게 남아도 저장하고 끝(사용자 확인 2026-11-15, Q-027). */
function interviewResultText(written: boolean, count: number): string {
  if (!written) return "카드 글에서 근거를 찾은 질문이 없어 아무것도 저장하지 않았어요. 다시 눌러 볼 수 있어요.";
  if (count < INTERVIEW_MIN_QUESTIONS) return `✓ 카드 글에서 근거를 찾은 질문 ${count}개를 만들었어요(카드 글이 짧으면 질문도 적어요).`;
  return `✓ 면접 질문 ${count}개를 만들었어요.`;
}

/** [면접 질문 만들기] 상태 — 머리 버튼과 오른쪽 안내가 같이 쓴다(조건을 한 곳에서 계산, 2차 리뷰 R1).
 *  done = 이미 질문이 있음(카드당 한 번), unsaved = 고친 칸이 저장 전(버튼은 보이되 비활성). */
type MakeState = "candidate" | "done" | "no-text" | "unsaved" | "ready";

function makeStateOf(card: CardDetail, unsavedChanges: boolean): MakeState {
  if (card.status === "candidate") return "candidate";
  if (card.interviewQuestions.length > 0) return "done";
  if (!card.fields.some((field) => field.quote !== null || field.answer !== null)) return "no-text";
  return unsavedChanges ? "unsaved" : "ready";
}

const EMPTY_INTERVIEW_TEXT: Record<Exclude<MakeState, "done">, string> = {
  candidate: "카드로 저장하면 면접 질문을 만들 수 있어요.",
  "no-text": "글이 있는 칸이 없어 질문을 만들 근거가 없어요. 빈칸에 내 답을 먼저 써 주세요.",
  unsaved: "고친 칸을 저장한 뒤 [면접 질문 만들기]를 눌러 주세요.",
  ready: `[면접 질문 만들기]를 누르면 글이 있는 칸마다 꼬리 질문을 ${INTERVIEW_MIN_QUESTIONS}~${INTERVIEW_MAX_QUESTIONS}개 만들어요. 이 카드의 칸 글만 AI에 보내요.`,
};

/** 오른쪽 '이 카드의 면접 질문 N'(Figma 27:892). 근거 칸 글이 바뀐 질문은 표시만 한다(질문 · 메모는 남김, 사용자 확인 2026-11-15). */
function InterviewQuestions({ questions, makeState }: { questions: InterviewQuestion[]; makeState: MakeState }) {
  const empty = makeState === "done" ? null : EMPTY_INTERVIEW_TEXT[makeState];
  return (
    <section aria-labelledby="card-interview-title" className={`${CARD} flex flex-col gap-3`}>
      <h2 id="card-interview-title" className={CARD_LABEL}>
        이 카드의 면접 질문 {questions.length}
      </h2>
      {empty ? (
        <p className="text-body-2 text-text-sub">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {questions.map((question) => (
            <li key={question.id} className="flex flex-col gap-1">
              <p className="text-body-2 text-text-main">· {question.question}</p>
              <p className="pl-2 text-body-4 text-text-sub">
                {SLOT_LABELS[question.slot]} 칸 근거
                {question.evidenceStatus !== "ok" ? (
                  <span className="ml-1 font-medium text-warning-text">· 카드 글이 바뀌어 근거를 찾을 수 없어요</span>
                ) : null}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function EvidenceSource({ field, noteId, noteTitle }: { field: CardField; noteId: number | null; noteTitle: string | null }) {
  const label = `${SLOT_LABELS[field.slot]} · ${noteTitle ?? "원문 없음"}`;
  if (noteId === null || field.chunkId === null) return <>{label}</>;
  return (
    <Link href={evidenceHref(noteId, field.chunkId)} className={SOURCE_LINK}>
      {label}
    </Link>
  );
}

function SlotEditor({
  field,
  noteId,
  draft,
  disabled,
  onDraft,
  onRemoveQuote,
}: {
  field: CardField;
  noteId: number | null;
  draft: string;
  disabled: boolean;
  onDraft: (value: string) => void;
  onRemoveQuote: () => void;
}) {
  const answerId = useId();
  const label = SLOT_LABELS[field.slot];
  const blank = isBlank({ quote: field.quote, answer: draft.trim() === "" ? null : draft });

  return (
    <section aria-labelledby={`${answerId}-label`} className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <h3 id={`${answerId}-label`} className="text-body-2 font-semibold text-text-main">
          {label}
        </h3>
        {blank ? <span className={BADGE_LINE}>빈칸</span> : null}
      </div>

      {field.quote !== null ? (
        <div className="flex flex-col gap-2">
          <CardQuote quote={field.quote} noteId={noteId} chunkId={field.chunkId} />
          <button type="button" onClick={onRemoveQuote} disabled={disabled} className={`${TEXT_BUTTON} self-start`}>
            인용 빼기
          </button>
        </div>
      ) : null}

      <label htmlFor={answerId} className="sr-only">
        {field.quote !== null ? `${label} — 내 답 덧붙이기` : `${label} — 내 답`}
      </label>
      <textarea
        disabled={disabled}
        id={answerId}
        value={draft}
        onChange={(event) => onDraft(event.target.value)}
        maxLength={CARD_MAX_ANSWER_CHARS}
        rows={field.quote !== null ? 2 : 3}
        placeholder={field.quote !== null ? "덧붙일 내용이 있으면 적어 주세요" : "직접 적어 주세요"}
        className={`rounded-input border bg-bg-default p-3 text-body-1 text-text-main placeholder:text-text-sub-weak ${
          blank ? "border-warning-text" : "border-line-input hover:border-line-input-hover"
        } ${FOCUS_RING}`}
      />

      {field.quote === null && field.question ? (
        <div className="flex flex-col gap-1 rounded-button bg-bg-light p-3">
          <p className="flex items-center gap-2 text-body-3 font-semibold text-text-sub">
            <Icon name="chat" size={16} className="text-icon-sub" />
            빈칸 질문
          </p>
          <p className="text-body-3 text-text-sub">
            {field.question} AI는 질문만 하고, 답은 직접 쓴 내용만 저장해요.
          </p>
        </div>
      ) : null}
    </section>
  );
}
