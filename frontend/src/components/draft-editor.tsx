"use client";

// APL_02_003 가운데 칸(Figma 18:257 '에디터'): 문항 머리(글자 수 · 내가 고친 비율 · [이 문항 완료]) + 문장마다 근거 칩.
// - 근거 없음(근거 상태가 ok가 아님): 문장에 경고색 밑줄 + 경고 아이콘 + '근거 없음' 칩. 고친 AI 문장은 '내가 고침'.
// - 문장을 누르면 고른 문장(primary/soft 바탕) → 오른쪽 칸에 근거. 고치기는 그 자리에 고치는 칸(Figma 23:959).
// - 초안 전: 매칭 카드가 없으면 빈 상태(Figma 19:383), 있으면 보내는 범위 안내 + [초안 쓰기](원칙 6).
// - 쓰는 중(Figma 19:407): 요청 한 번(D-022)이라 진행 단계를 실제로 알 수 없어 단계 목록만 보여 준다(문장 수 · 만든 문장 미리보기 없음).

import Link from "next/link";
import { type KeyboardEvent, type ReactNode, useState } from "react";
import { Icon } from "@/components/icon";
import { RequestErrorBlock, RequestErrorText } from "@/components/request-error";
import { applicationHref } from "@/lib/applications";
import type { CardSummary } from "@/lib/cards";
import {
  type ApplicationDrafts,
  type Draft,
  DRAFT_DEFAULT_TARGET_CHARS,
  DRAFT_MAX_CARDS_SENT,
  DRAFT_SENTENCE_MAX_CHARS,
  type DraftQuestion,
  type DraftSentence,
  type RequestState,
  type SentenceEdit,
  charCountLabel,
  editsOf,
  formatTime,
} from "@/lib/drafts";
import {
  BADGE_SHAPE,
  BADGE_SOFT,
  FOCUS_RING,
  GHOST_BUTTON_S,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_S,
} from "@/lib/ui-classes";

export type EditTarget = { kind: "edit"; sentenceId: number } | { kind: "insert"; afterSentenceId: number | null };

// Figma Didim/근거 칩(Badge Line · 검정 글자) — 문장 끝에 붙는다. 근거 없음은 경고색.
const CHIP = `${BADGE_SHAPE} ml-1 border border-badge-black-text bg-bg-default align-middle text-badge-black-text`;
const CHIP_WARNING = `${BADGE_SHAPE} border border-warning-text bg-bg-default align-middle text-warning-text`;

/** 초안 쓰기 상태(어느 문항의 요청인지 문항 번호로 가린다). */
export type WriteState = RequestState<(questionId: number, overwrite: boolean) => void> & {
  pendingQuestionId: number | null; // 지금 쓰는 문항(없으면 null)
  failedQuestionId: number | null; // 마지막 요청이 실패한 문항(error와 짝)
  emptyQuestionId: number | null; // AI가 문장을 주지 않아 바뀌지 않은 문항
};
/** 고른 문장 · 고치는 문장(이 화면만 쓰는 상태 — draft-workspace의 useState). */
export type Selection = {
  sentenceId: number | null;
  onSelect: (sentenceId: number | null) => void;
  editTarget: EditTarget | null;
  onEdit: (target: EditTarget | null) => void;
};

export function DraftEditor({
  applicationId,
  data,
  question,
  cards,
  selection,
  write,
  save,
  complete,
}: {
  applicationId: number;
  data: ApplicationDrafts; // checkedAt = 서버가 근거를 마지막으로 다시 검사한 시각(읽을 때 · 저장할 때)
  question: DraftQuestion | null;
  cards: CardSummary[] | null;
  selection: Selection;
  write: WriteState;
  save: RequestState<(edits: SentenceEdit[]) => void>;
  complete: RequestState<(draftId: number, completed: boolean) => void>;
}) {
  if (question === null) {
    return (
      <section aria-labelledby="draft-editor-title" className={EDITOR}>
        <h2 id="draft-editor-title" className="text-title-2 font-semibold text-text-main">
          자소서 문항
        </h2>
        <p className="text-body-2 text-text-sub">이 공고에는 자소서 문항이 없어요. 왼쪽 [문항 고치기]로 문항을 넣어 주세요.</p>
      </section>
    );
  }

  const number = data.questions.findIndex((item) => item.id === question.id) + 1;
  const draft = question.draft;
  const writing = write.pendingQuestionId !== null;
  const writingThis = write.pendingQuestionId === question.id;
  const writeErrorThis = write.failedQuestionId === question.id ? write.error : null;
  const emptyResult = write.emptyQuestionId === question.id;
  const matchedTitles = (cards ?? [])
    .filter((card) => data.matchedCardIds.includes(card.id))
    .slice(0, DRAFT_MAX_CARDS_SENT)
    .map((card) => card.title);
  const cardsToSend = Math.min(data.matchedCardIds.length, DRAFT_MAX_CARDS_SENT);

  const startWrite = (overwrite: boolean) => {
    if (overwrite && !window.confirm("지금 초안을 지우고 AI가 다시 써요. 내가 고친 문장도 사라져요. 오늘 AI 사용량을 1회 써요. 다시 쓸까요?")) {
      return;
    }
    write.run(question.id, overwrite);
  };

  return (
    <section aria-labelledby="draft-editor-title" className={EDITOR}>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 id="draft-editor-title" className="text-title-2 font-semibold text-text-main">
            {number}번 문항
          </h2>
          {draft ? <DraftMeta draft={draft} /> : <p className="text-body-4 text-text-sub">{charCountLabel(0, question.charLimit)}</p>}
        </div>
        {draft && !writingThis ? (
          <>
            <button type="button" onClick={() => startWrite(true)} disabled={writing} className={GHOST_BUTTON_S}>
              다시 쓰기
            </button>
            <button
              type="button"
              disabled={complete.pending}
              onClick={() => complete.run(draft.id, draft.completedAt === null)}
              className={draft.completedAt === null ? PRIMARY_BUTTON : SECONDARY_BUTTON}
            >
              {draft.completedAt === null ? "이 문항 완료" : "완료 풀기"}
            </button>
          </>
        ) : null}
      </div>
      {complete.error ? <RequestErrorText error={complete.error} /> : null}

      <p className="text-body-2 text-text-sub">{question.text}</p>

      {writingThis ? (
        <WritingProgress titles={matchedTitles} count={cardsToSend} />
      ) : draft === null ? (
        data.matchedCardIds.length === 0 ? (
          <EmptyCards applicationId={applicationId} analysisDone={data.analysisDone} />
        ) : (
          <div className="flex flex-col gap-3">
            {/* 설계 원칙 6: AI에 무엇을 보내는지 누르기 전에 알린다 */}
            <p className="text-body-2 text-text-sub">
              이 공고에 매칭된 내 카드 {cardsToSend}장의 제목 · 칸 글과 문항을 AI에 보내{" "}
              {question.charLimit ? `${question.charLimit.toLocaleString("ko-KR")}자 안의` : `${DRAFT_DEFAULT_TARGET_CHARS}자쯤의`} 초안을 써요.
              문장마다 카드 칸 글을 그대로 근거로 달고, 근거를 찾지 못한 문장은 &apos;근거 없음&apos;으로 표시해요. 오늘 AI 사용량을 1회 써요.
            </p>
            {writeErrorThis ? <WriteFailure error={writeErrorThis} onRetry={() => startWrite(false)} /> : null}
            <button type="button" onClick={() => startWrite(false)} disabled={writing} className={`${PRIMARY_BUTTON} self-start`}>
              초안 쓰기
            </button>
            {writing ? <p className="text-body-3 text-text-sub">다른 문항의 초안을 쓰는 중이에요. 끝난 뒤 눌러 주세요.</p> : null}
          </div>
        )
      ) : (
        <>
          {writeErrorThis ? <WriteFailure error={writeErrorThis} onRetry={() => startWrite(true)} /> : null}
          {emptyResult ? (
            <p role="status" className="rounded-button bg-bg-light p-4 text-body-2 text-text-sub">
              AI가 쓸 만한 문장을 주지 않았어요. 이전 초안은 그대로예요.
            </p>
          ) : null}
          <SentenceFlow
            draft={draft}
            selection={selection}
            busy={save.pending}
            onApply={save.run}
          />
          {save.error ? <RequestErrorText error={save.error} /> : null}
          <p className="text-body-4 text-text-sub">
            마지막 검사 {formatTime(data.checkedAt)} · 문장을 고치면 자동으로 다시 검사해요
          </p>
        </>
      )}
    </section>
  );
}

const EDITOR = "flex min-w-0 flex-1 flex-col gap-5 rounded-card border border-line-regular bg-bg-default p-4";

/** "487 / 700자 · AI 초안에서 내가 고친 부분 42%". 글자 수를 넘으면 경고색(저장은 됨 — 설계 의도 ②). */
function DraftMeta({ draft }: { draft: Draft }) {
  const over = draft.charLimit !== null && draft.chars > draft.charLimit;
  return (
    <p className="text-body-4 text-text-sub">
      <span className={over ? "font-medium text-warning-text" : undefined}>
        {charCountLabel(draft.chars, draft.charLimit)}
        {over ? " · 글자 수를 넘었어요" : ""}
      </span>
      {" · "}AI 초안에서 내가 고친 부분 {draft.editedPercent}%
    </p>
  );
}

/** 문장들을 한 문단처럼 이어 그린다. 고치는 문장 · 새 문장 자리에는 고치는 칸이 끼어든다. */
function SentenceFlow({
  draft,
  selection,
  busy,
  onApply,
}: {
  draft: Draft;
  selection: Selection;
  busy: boolean;
  onApply: (edits: SentenceEdit[]) => void;
}) {
  const { sentenceId: selectedSentenceId, onSelect: onSelectSentence, editTarget, onEdit } = selection;
  const blocks: ReactNode[] = [];
  let run: ReactNode[] = [];
  const flush = () => {
    if (run.length > 0) {
      blocks.push(
        <p key={`run-${blocks.length}`} className="text-title-4 leading-8 font-normal text-text-main">
          {run}
        </p>,
      );
      run = [];
    }
  };
  const insertBox = (afterSentenceId: number | null, index: number) => (
    <EditBox
      key={`insert-${afterSentenceId ?? "start"}`}
      initial=""
      originalText={null}
      busy={busy}
      onCancel={() => onEdit(null)}
      onApply={(text) => {
        const edits = editsOf(draft);
        edits.splice(index, 0, { id: null, text });
        onApply(edits);
      }}
    />
  );

  if (editTarget?.kind === "insert" && editTarget.afterSentenceId === null) blocks.push(insertBox(null, 0));
  draft.sentences.forEach((sentence, index) => {
    if (editTarget?.kind === "edit" && editTarget.sentenceId === sentence.id) {
      flush();
      blocks.push(
        <EditBox
          key={`edit-${sentence.id}`}
          initial={sentence.text}
          originalText={sentence.originalText}
          busy={busy}
          onCancel={() => onEdit(null)}
          onApply={(text) => onApply(editsOf(draft).map((item) => (item.id === sentence.id ? { ...item, text } : item)))}
        />,
      );
    } else {
      run.push(
        <SentenceSpan
          key={sentence.id}
          sentence={sentence}
          number={index + 1}
          selected={sentence.id === selectedSentenceId}
          onSelect={() => onSelectSentence(sentence.id === selectedSentenceId ? null : sentence.id)}
        />,
        " ",
      );
    }
    if (editTarget?.kind === "insert" && editTarget.afterSentenceId === sentence.id) {
      flush();
      blocks.push(insertBox(sentence.id, index + 1));
    }
  });
  flush();
  return <div className="flex flex-col gap-3">{blocks}</div>;
}

/** 문장 하나 + 근거 칩. 누르면 고른 문장이 된다(오른쪽 칸에 근거). */
function SentenceSpan({
  sentence,
  number,
  selected,
  onSelect,
}: {
  sentence: DraftSentence;
  number: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const supported = sentence.evidenceStatus === "ok";
  const onKeyDown = (event: KeyboardEvent<HTMLSpanElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  };
  return (
    <span
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={`문장 ${number}${supported ? "" : " · 근거 없음"}${sentence.origin === "edited" ? " · 내가 고침" : ""}: ${sentence.text}`}
      onClick={onSelect}
      onKeyDown={onKeyDown}
      className={`cursor-pointer rounded-tag px-0.5 box-decoration-clone ${selected ? "bg-primary-soft" : "hover:bg-bg-hover"} ${FOCUS_RING}`}
    >
      <span className={supported ? undefined : "underline decoration-warning-text decoration-2 underline-offset-4"}>{sentence.text}</span>
      {/* '내가 고침'은 문장 글 바로 뒤 — 칩 뒤에 두면 줄이 바뀔 때 다음 문장 앞에 붙어 보인다 */}
      {sentence.origin === "edited" ? <span className={`${BADGE_SOFT} ml-1 align-middle`}>내가 고침</span> : null}
      {supported ? (
        <span className={CHIP}>{sentence.evidence?.cardTitle ?? "근거"}</span>
      ) : (
        <span className="ml-1 inline-flex items-center gap-1 align-middle">
          <Icon name="warning" size={16} className="text-warning-text" />
          <span className={CHIP_WARNING}>근거 없음</span>
        </span>
      )}
    </span>
  );
}

/** 문장 직접 고치기(Figma 23:959): 글 칸 + '원래 문장' 안내 + [취소] · [이 문장 적용]. Esc = 취소. */
function EditBox({
  initial,
  originalText,
  busy,
  onCancel,
  onApply,
}: {
  initial: string;
  originalText: string | null;
  busy: boolean;
  onCancel: () => void;
  onApply: (text: string) => void;
}) {
  const [text, setText] = useState(initial);
  const empty = text.trim() === "";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 rounded-button border-2 border-primary-default p-3">
        <label className="sr-only" htmlFor="draft-edit-sentence">
          {originalText === null && initial === "" ? "새 문장" : "고칠 문장"}
        </label>
        <textarea
          id="draft-edit-sentence"
          autoFocus
          value={text}
          rows={2}
          maxLength={DRAFT_SENTENCE_MAX_CHARS}
          disabled={busy}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onCancel();
          }}
          className="w-full resize-y bg-transparent text-title-4 text-text-main outline-none"
        />
        <p className="flex items-start gap-1 text-body-4 text-text-sub">
          <Icon name="check" size={16} className="shrink-0 text-icon-sub" />
          {originalText !== null
            ? `고친 문장은 근거 칩을 그대로 두고, 저장할 때 근거를 다시 확인해요 · 원래 문장: ${originalText}`
            : "새 문장은 근거 없이 저장돼요. 기록에 있는 내용이면 저장한 뒤 [카드 연결]로 근거를 붙여 주세요."}
        </p>
      </div>
      <div className="flex gap-2">
        <button type="button" onClick={onCancel} disabled={busy} className={GHOST_BUTTON_S}>
          취소
        </button>
        <button type="button" onClick={() => onApply(text)} disabled={busy || empty} className={SECONDARY_BUTTON_S}>
          {busy ? "저장하는 중…" : "이 문장 적용"}
        </button>
      </div>
    </div>
  );
}

/** 매칭된 카드가 없을 때(Figma 19:383) — 근거 없이 쓰면 AI 창작이 되므로 초안 쓰기를 막는다(D-003 예외 7). */
function EmptyCards({ applicationId, analysisDone }: { applicationId: number; analysisDone: boolean }) {
  return (
    <div className="flex flex-col items-center gap-2 py-16 text-center">
      <p className="text-title-4 font-semibold text-text-main">
        {analysisDone ? "이 공고에 맞는 경험 카드가 아직 없어요" : "공고 분석을 먼저 해 주세요"}
      </p>
      <p className="text-body-3 text-text-sub">
        {analysisDone
          ? "근거 없이 쓰면 AI가 지어낸 문장이 돼요. 카드를 만든 뒤 공고 분석에서 [매칭 다시]를 누르면 초안을 쓸 수 있어요."
          : "초안은 이 공고에 매칭된 내 경험 카드로만 써요. 공고 분석에서 요구 역량과 내 카드를 먼저 맞춰 주세요."}
      </p>
      <div className="mt-4 flex gap-2">
        {analysisDone ? (
          <Link href="/cards" className={PRIMARY_BUTTON}>
            카드 만들기
          </Link>
        ) : null}
        <Link href={applicationHref(applicationId, "analysis")} className={analysisDone ? SECONDARY_BUTTON : PRIMARY_BUTTON}>
          공고 분석으로
        </Link>
      </div>
    </div>
  );
}

/** 쓰는 중(Figma 19:407). 요청 한 번(D-022)이라 실제 단계를 알 수 없다 — 카드 읽기는 끝, 문장 만들기 · 근거 확인은 진행 표시만. */
function WritingProgress({ titles, count }: { titles: string[]; count: number }) {
  return (
    <div role="status" className="flex flex-col gap-4">
      <p className="text-body-2 text-text-sub">카드 {count}장에서 초안을 만들고 있어요. 최대 3분쯤 걸리고, 이 화면을 나가도 이어서 만들어요.</p>
      <ol className="flex flex-col gap-3">
        <li className="flex items-center gap-2">
          <Icon name="success" size={20} className="text-success-base" />
          <span className="text-body-2 font-medium text-text-main">카드 {count}장 읽기</span>
          <span className="min-w-0 truncate text-body-4 text-text-sub">{titles.join(" · ")}</span>
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="size-5 animate-spin rounded-full border-2 border-line-regular border-t-primary-default" />
          <span className="text-body-2 font-semibold text-text-main">문장 만들기</span>
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="size-5 rounded-full border-2 border-line-regular" />
          <span className="text-body-2 text-text-sub">문장마다 근거 확인</span>
          <span className="text-body-4 text-text-sub">카드 칸 글에 그대로 있는지 서버가 확인해요</span>
        </li>
      </ol>
    </div>
  );
}

/** 초안 쓰기 실패(APL_02_900과 같은 모양). 이전 초안은 그대로다. */
function WriteFailure({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className="flex gap-3 rounded-button border border-warning-text bg-bg-light p-4">
      <Icon name="warning" size={20} className="text-warning-text" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <RequestErrorBlock
          error={error}
          hint={
            <button type="button" onClick={onRetry} className={`${SECONDARY_BUTTON_S} self-start`}>
              다시 시도
            </button>
          }
        />
      </div>
    </div>
  );
}
