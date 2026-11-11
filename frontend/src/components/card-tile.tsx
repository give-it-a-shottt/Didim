import Link from "next/link";
import { CARD_SLOTS, type CardSummary, cardHref, formatCardDate, SLOT_LABELS } from "@/lib/cards";
import { FOCUS_RING } from "@/lib/ui-classes";

// 경험 카드 목록의 카드 한 장(Figma CRD_01_001 27:787): 노트 이름 · 제목 · 네 칸 칩(빈칸은 노란 테두리) · 근거 수 · 빈칸 수 · 수정일.
// 서버 컴포넌트에서도 쓰는 그림 부품이라 "use client"가 없다.

export function CardTile({ card }: { card: CardSummary }) {
  const blank = new Set(card.blankSlots);
  const meta = [`근거 ${card.evidenceCount}`, card.blankCount > 0 ? `빈칸 ${card.blankCount}` : null, formatCardDate(card.updatedAt)]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="min-w-0">
      <Link
        href={cardHref(card.id)}
        className={`flex h-full flex-col gap-3 rounded-card border border-line-regular bg-bg-default p-5 hover:bg-bg-hover ${FOCUS_RING}`}
      >
        <span className="text-body-4 text-text-sub">{card.noteTitle ?? "원문 없음"}</span>
        <span className="text-body-1 font-medium wrap-break-word text-text-main">{card.title}</span>
        <span className="flex flex-wrap gap-1">
          {CARD_SLOTS.map((slot) => (
            <span
              key={slot}
              className={
                blank.has(slot)
                  ? "rounded-button border border-warning-text bg-bg-default px-2 py-1 text-body-4 text-warning-text"
                  : "rounded-button border border-line-light bg-bg-regular px-2 py-1 text-body-4 text-text-sub"
              }
            >
              {SLOT_LABELS[slot]}
              {blank.has(slot) ? <span className="sr-only"> 빈칸</span> : null}
            </span>
          ))}
        </span>
        <span className="text-body-4 text-text-sub">{meta}</span>
      </Link>
    </li>
  );
}
