import "server-only";

import { fetchBackendAsUser } from "@/lib/backend";
import { type CardDetail, type CardStatus, type CardSummary, toCardDetail, toCardSummary } from "@/lib/cards";
import { isObject, readJson } from "@/lib/json";

// 경험 카드(F-006)를 서버 컴포넌트에서 FastAPI로 부른다. 처음 화면을 그릴 때 필요한 서버 데이터라 서버 컴포넌트(D-012).

export type CardListOutcome =
  | { status: "ok"; total: number; cards: CardSummary[]; noteSearched: boolean | null }
  | { status: "error" };

export type CardOutcome = { status: "ok"; card: CardDetail } | { status: "not-found" } | { status: "error" };

/** 상태별 카드 목록. noteId를 주면 그 노트의 카드만 + 그 노트에서 후보 찾기를 끝냈는지(noteSearched). */
export async function getCardList(status: CardStatus, noteId?: number): Promise<CardListOutcome> {
  const params = new URLSearchParams({ status });
  if (noteId !== undefined) params.set("note_id", String(noteId));
  const response = await fetchBackendAsUser(`/api/cards?${params.toString()}`);
  if (response === null || !response.ok) {
    return { status: "error" };
  }
  const body = await readJson(response);
  if (!isObject(body) || typeof body.total !== "number" || !Array.isArray(body.cards)) {
    return { status: "error" };
  }
  const cards = body.cards.map(toCardSummary);
  if (cards.some((card) => card === null)) {
    return { status: "error" };
  }
  const noteSearched = typeof body.note_searched === "boolean" ? body.note_searched : null;
  return { status: "ok", total: body.total, cards: cards as CardSummary[], noteSearched };
}

export async function getCard(cardId: number): Promise<CardOutcome> {
  const response = await fetchBackendAsUser(`/api/cards/${cardId}`);
  if (response === null) {
    return { status: "error" };
  }
  if (response.status === 404) {
    return { status: "not-found" };
  }
  const card = response.ok ? toCardDetail(await readJson(response)) : null;
  return card === null ? { status: "error" } : { status: "ok", card };
}
