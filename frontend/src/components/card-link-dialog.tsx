"use client";

// [카드 연결](F-008 — D-006 'MVP는 [카드 연결] 버튼 + 카드 검색 팝오버', 사용자 확인 2026-11-14):
// 근거 없는 문장에 내 저장 카드의 칸 하나(원문 인용 또는 내 답)를 통째로 근거로 붙인다.
// ① 카드 고르기(이 공고에 매칭된 카드 먼저, 제목 검색) → ② 칸 고르기. 서버가 그 칸 글이 지금 카드에 있는지 확인한다.
// 카드 칸 글은 내 기록 원문이라 명조. 카드 상세는 useQuery(카드 후보 검토 시트와 같은 키 — 캐시를 같이 씀).

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { CardSearchInput } from "@/components/card-search-input";
import { Icon } from "@/components/icon";
import { RequestErrorText } from "@/components/request-error";
import { type CardSlot, type CardSummary, SLOT_LABELS, fetchCard, filterCardsByTitle } from "@/lib/cards";
import type { DraftSentence, EvidenceLink, QuoteSource } from "@/lib/drafts";
import { FOCUS_RING, GHOST_BUTTON_S, TEXT_BUTTON } from "@/lib/ui-classes";

export function CardLinkDialog({
  sentence,
  cards,
  matchedCardIds,
  busy,
  error,
  onClose,
  onLink,
}: {
  sentence: DraftSentence | null; // null이면 닫힘
  cards: CardSummary[] | null;
  matchedCardIds: number[];
  busy: boolean;
  error: Error | null;
  onClose: () => void;
  onLink: (link: EvidenceLink) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const isOpen = sentence !== null;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (isOpen && !dialog.open) dialog.showModal();
    if (!isOpen && dialog.open) dialog.close();
  }, [isOpen]);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="card-link-title"
      onCancel={(event) => {
        if (busy) event.preventDefault(); // 저장 중에는 Esc로 닫지 않는다
      }}
      onClose={() => {
        if (isOpen) onClose();
      }}
      // Figma 모달과 같은 틀: 위 28 · 옆 24 · 아래 24
      className="m-auto w-full max-w-140 rounded-modal bg-bg-elevated px-6 pt-7 pb-6 text-text-main backdrop:bg-bg-dim"
    >
      {sentence !== null ? (
        <LinkPicker
          key={sentence.id}
          sentence={sentence}
          cards={cards}
          matchedCardIds={matchedCardIds}
          busy={busy}
          error={error}
          onClose={onClose}
          onLink={onLink}
        />
      ) : null}
    </dialog>
  );
}

function LinkPicker({
  sentence,
  cards,
  matchedCardIds,
  busy,
  error,
  onClose,
  onLink,
}: {
  sentence: DraftSentence;
  cards: CardSummary[] | null;
  matchedCardIds: number[];
  busy: boolean;
  error: Error | null;
  onClose: () => void;
  onLink: (link: EvidenceLink) => void;
}) {
  const [cardId, setCardId] = useState<number | null>(null);
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h2 id="card-link-title" className="text-title-2 font-semibold text-text-main">
          카드 연결
        </h2>
        <p className="text-body-3 text-text-sub">이 문장의 근거가 될 카드 칸을 골라 주세요. 칸 글 전체가 근거로 붙어요.</p>
        <p className="rounded-button bg-bg-light p-3 text-body-2 text-text-main">{sentence.text}</p>
      </div>

      {cardId === null ? (
        <CardPicker cards={cards} matchedCardIds={matchedCardIds} onPick={setCardId} />
      ) : (
        <FieldPicker cardId={cardId} busy={busy} onBack={() => setCardId(null)} onPick={(slot, quoteSource) => onLink({ cardId, slot, quoteSource })} />
      )}

      {error ? <RequestErrorText error={error} /> : null}
      <div className="flex justify-end">
        <button type="button" onClick={onClose} disabled={busy} className={GHOST_BUTTON_S}>
          닫기
        </button>
      </div>
    </div>
  );
}

function CardPicker({
  cards,
  matchedCardIds,
  onPick,
}: {
  cards: CardSummary[] | null;
  matchedCardIds: number[];
  onPick: (cardId: number) => void;
}) {
  const [search, setSearch] = useState("");
  if (cards === null) {
    return (
      <p role="alert" className="text-body-2 text-error-text">
        카드 목록을 불러오지 못했어요. 새로고침한 뒤 다시 시도해 주세요.
      </p>
    );
  }
  const shown = filterCardsByTitle(cards, search).sort(
    (a, b) => Number(!matchedCardIds.includes(a.id)) - Number(!matchedCardIds.includes(b.id)),
  );
  return (
    <div className="flex flex-col gap-2">
      <CardSearchInput value={search} onChange={setSearch} placeholder="카드 제목으로 찾기" autoFocus />
      {shown.length === 0 ? (
        <p className="text-body-3 text-text-sub">{search.trim() ? "찾는 카드가 없어요." : "저장한 경험 카드가 없어요. 카드를 먼저 저장해 주세요."}</p>
      ) : (
        <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto">
          {shown.map((card) => (
            <li key={card.id}>
              <button
                type="button"
                onClick={() => onPick(card.id)}
                className={`flex w-full flex-col gap-1 rounded-card border border-line-regular bg-bg-default p-3 text-left hover:bg-bg-hover ${FOCUS_RING}`}
              >
                <span className="text-body-3 font-semibold text-text-main">{card.title}</span>
                <span className="text-body-4 text-text-sub">
                  근거 {card.evidenceCount} · 빈칸 {card.blankCount}
                  {matchedCardIds.includes(card.id) ? " · 이 공고에 매칭됨" : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FieldPicker({
  cardId,
  busy,
  onBack,
  onPick,
}: {
  cardId: number;
  busy: boolean;
  onBack: () => void;
  onPick: (slot: CardSlot, quoteSource: QuoteSource) => void;
}) {
  const query = useQuery({ queryKey: ["card", cardId], queryFn: () => fetchCard(cardId), retry: false });
  const options =
    query.data?.fields.flatMap((field) => [
      ...(field.quote ? [{ slot: field.slot, source: "quote" as QuoteSource, text: field.quote }] : []),
      ...(field.answer ? [{ slot: field.slot, source: "answer" as QuoteSource, text: field.answer }] : []),
    ]) ?? [];

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <button type="button" onClick={onBack} disabled={busy} className={TEXT_BUTTON}>
          <Icon name="caret-left" size={16} />
          카드 다시 고르기
        </button>
        <div className="flex-1" />
        {query.data ? <p className="truncate text-body-3 font-semibold text-text-main">{query.data.title}</p> : null}
      </div>
      {query.isPending ? (
        <p role="status" className="text-body-3 text-text-sub">
          카드를 불러오고 있어요…
        </p>
      ) : query.error ? (
        <RequestErrorText error={query.error} />
      ) : options.length === 0 ? (
        <p className="text-body-3 text-text-sub">이 카드에는 근거로 붙일 글이 없어요. 카드의 빈칸을 먼저 채워 주세요.</p>
      ) : (
        <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto">
          {options.map((option) => (
            <li key={`${option.slot}-${option.source}`}>
              <button
                type="button"
                disabled={busy}
                onClick={() => onPick(option.slot, option.source)}
                className={`flex w-full flex-col gap-2 rounded-card border border-line-regular bg-bg-default p-3 text-left hover:bg-bg-hover disabled:cursor-not-allowed ${FOCUS_RING}`}
              >
                <span className="text-body-4 font-medium text-text-sub">
                  {SLOT_LABELS[option.slot]} · {option.source === "quote" ? "원문 인용" : "내 답"}
                </span>
                <span className="border-l-2 border-line-strong px-3 font-serif text-quote whitespace-pre-wrap text-text-sub">
                  {option.text}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
