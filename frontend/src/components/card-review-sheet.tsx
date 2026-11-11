"use client";

// 카드 후보 검토 시트(CRD_01_003, Figma Drawer 480 · 27:1078). 후보를 하나씩 보고 제목을 확인해 [카드로 저장] 또는 [버리기].
// 노트 상세의 "후보 N개 검토"와 /cards 후보 탭에서 연다. 후보 목록(번호)은 서버 컴포넌트가 넘기고,
// 후보 하나의 내용은 열 때 브라우저가 받는다(useQuery — 서버 데이터, D-012). 저장 · 버리기는 useMutation.
// 시트 안의 '몇 번째 후보 · 제목 입력'은 이 시트에서만 쓰여 useState(D-012).
//
// Figma와 다르게 둔 것(D-003, F-006 설계 의도): 칸마다 AI 요약 대신 **원문 인용**(명조)을 그대로 보여 준다.
// 인용이 없는 칸은 "원문에 없어요 — 저장한 뒤 직접 채워요" + AI 질문.

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { CardQuote } from "@/components/card-parts";
import { RequestErrorText } from "@/components/request-error";
import {
  CARD_TITLE_MAX_CHARS,
  type CardDetail,
  cardHref,
  deleteCard,
  fetchCard,
  SLOT_LABELS,
  saveCard,
} from "@/lib/cards";
import { FOCUS_RING, GHOST_BUTTON, GHOST_BUTTON_S, PRIMARY_BUTTON } from "@/lib/ui-classes";

export function CardReviewButton({
  cardIds,
  label,
  className,
}: {
  cardIds: number[];
  label: string;
  className: string;
}) {
  const router = useRouter();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [openCount, setOpenCount] = useState(0); // 열 때마다 검토를 처음부터(새로 받은 후보 목록으로)
  const changedRef = useRef(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (isOpen && !dialog.open) dialog.showModal();
    if (!isOpen && dialog.open) dialog.close();
  }, [isOpen]);

  function close() {
    setIsOpen(false);
    // 저장 · 버린 후보가 있으면 서버 컴포넌트가 그린 목록 · 개수를 새로 받는다
    if (changedRef.current) router.refresh();
  }

  return (
    <>
      <button
        type="button"
        onClick={() => {
          changedRef.current = false;
          setOpenCount((count) => count + 1);
          setIsOpen(true);
        }}
        disabled={cardIds.length === 0}
        className={className}
      >
        {label}
      </button>
      <dialog
        ref={dialogRef}
        aria-labelledby="card-review-title"
        onClose={() => {
          if (isOpen) close();
        }}
        // Drawer 480: 오른쪽에 붙고 화면 높이 전체, 뒤는 bg/dim
        className="m-0 ml-auto h-dvh max-h-dvh w-full max-w-120 bg-bg-elevated text-text-main backdrop:bg-bg-dim"
      >
        {isOpen ? (
          <CandidateReview
            key={openCount}
            cardIds={cardIds}
            onChanged={() => {
              changedRef.current = true;
            }}
            onClose={close}
          />
        ) : null}
      </dialog>
    </>
  );
}

function CandidateReview({
  cardIds,
  onChanged,
  onClose,
}: {
  cardIds: number[];
  onChanged: () => void;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [savedIds, setSavedIds] = useState<number[]>([]);
  const cardId = cardIds[index];
  const isDone = index >= cardIds.length;

  function next(saved?: number) {
    onChanged();
    if (saved !== undefined) setSavedIds((ids) => [...ids, saved]);
    setIndex((value) => value + 1);
  }

  return (
    <div className="flex h-full flex-col gap-5">
      <div className="flex h-16 shrink-0 items-center border-b border-line-regular px-6">
        <h2 id="card-review-title" className="text-title-3 font-semibold text-text-main">
          {isDone ? "후보를 모두 봤어요" : `카드 후보 ${cardIds.length}개 중 ${index + 1}`}
        </h2>
        <div className="flex-1" />
        <button type="button" onClick={onClose} className={GHOST_BUTTON_S}>
          닫기
        </button>
      </div>
      {isDone ? (
        <ReviewDone savedIds={savedIds} onClose={onClose} />
      ) : (
        <CandidateStep key={cardId} cardId={cardId} onDone={next} />
      )}
    </div>
  );
}

function ReviewDone({ savedIds, onClose }: { savedIds: number[]; onClose: () => void }) {
  return (
    <>
      <div role="status" className="flex flex-1 flex-col gap-2 px-6">
        <p className="text-body-1 text-text-main">
          {savedIds.length > 0 ? `카드 ${savedIds.length}장을 저장했어요.` : "저장한 카드가 없어요."}
        </p>
        {savedIds.length > 0 ? (
          <p className="text-body-2 text-text-sub">카드 상세에서 빈칸을 채우면 완성돼요.</p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2 border-t border-line-regular px-6 py-4">
        <div className="flex-1" />
        {savedIds.length > 0 ? (
          <Link href={cardHref(savedIds[0])} className={PRIMARY_BUTTON}>
            빈칸 채우러 가기
          </Link>
        ) : (
          <button type="button" onClick={onClose} className={PRIMARY_BUTTON}>
            닫기
          </button>
        )}
      </div>
    </>
  );
}

function CandidateStep({ cardId, onDone }: { cardId: number; onDone: (saved?: number) => void }) {
  const query = useQuery({ queryKey: ["card", cardId], queryFn: () => fetchCard(cardId), retry: false });

  if (query.isPending) {
    return (
      <p role="status" className="flex-1 px-6 text-body-2 text-text-sub">
        후보를 불러오는 중…
      </p>
    );
  }
  if (query.isError) {
    return (
      <div className="flex flex-1 flex-col gap-3 px-6">
        <p role="alert" className="text-body-2 font-medium text-error-text">
          {query.error.message}
        </p>
        <button type="button" onClick={() => onDone()} className={`${GHOST_BUTTON} self-start`}>
          다음 후보 보기
        </button>
      </div>
    );
  }
  return <CandidateForm card={query.data} onDone={onDone} />;
}

function CandidateForm({ card, onDone }: { card: CardDetail; onDone: (saved?: number) => void }) {
  const titleId = useId();
  const [title, setTitle] = useState(card.title);
  const save = useMutation({ mutationFn: () => saveCard(card.id, title), onSuccess: () => onDone(card.id) });
  const discard = useMutation({ mutationFn: () => deleteCard(card.id), onSuccess: () => onDone() });
  const isBusy = save.isPending || discard.isPending;
  const error = save.error ?? discard.error;

  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 pb-4">
        <p className="text-body-2 text-text-sub">
          {card.noteTitle ? `「${card.noteTitle}」에서 찾았어요. ` : ""}
          맞는 내용이면 저장하고, 아니면 버리세요. 칸 글은 내 노트 원문 그대로예요.
        </p>

        <div className="flex flex-col gap-1">
          <label htmlFor={titleId} className="text-body-3 font-semibold text-text-sub">
            카드 제목 <span className="font-normal">(AI 제안 — 고쳐도 돼요)</span>
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

        {card.fields.map((field) => (
          <section key={field.slot} aria-label={SLOT_LABELS[field.slot]} className="flex flex-col gap-1">
            <h3 className="text-body-3 font-semibold text-text-sub">{SLOT_LABELS[field.slot]}</h3>
            {field.quote !== null ? (
              <CardQuote quote={field.quote} noteId={card.noteId} chunkId={field.chunkId} />
            ) : (
              <>
                <p className="text-body-1 text-warning-text">원문에 없어요 — 저장한 뒤 직접 채워요</p>
                {field.question ? <p className="text-body-3 text-text-sub">AI 질문: {field.question}</p> : null}
              </>
            )}
          </section>
        ))}

        {error ? <RequestErrorText error={error} /> : null}
      </div>

      <div className="flex shrink-0 items-center gap-2 border-t border-line-regular px-6 py-4">
        <button type="button" onClick={() => discard.mutate()} disabled={isBusy} className={GHOST_BUTTON}>
          {discard.isPending ? "버리는 중…" : "버리기"}
        </button>
        <div className="flex-1" />
        <button type="submit" disabled={isBusy || title.trim() === ""} className={PRIMARY_BUTTON}>
          {save.isPending ? "저장하는 중…" : "카드로 저장"}
        </button>
      </div>
    </form>
  );
}
