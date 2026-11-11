"use client";

// 노트 상세(REV_01_002) 오른쪽의 경험 카드 칸(F-006). Figma에는 없는 자리라 문제 칸(note-quiz-panel)과 같은 모양으로 둔다.
// - 아직 안 찾았으면 [카드 후보 찾기](AI 1번) — 누르기 전에 무엇을 보내는지 알린다(설계 원칙 6).
// - 찾았으면 검토할 후보 수 + [후보 검토](시트) + 저장한 카드 수.
// 후보 · 카드 수는 서버 컴포넌트가 넘기고, 찾기는 서버 수정이라 useMutation(D-012). 찾은 뒤 router.refresh()로 새로 받는다.

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CardReviewButton } from "@/components/card-review-sheet";
import { RequestErrorBlock } from "@/components/request-error";
import { ApiRequestError } from "@/lib/api-request";
import { CARD_MAX_CANDIDATES_PER_NOTE, type FindResult, findCandidates } from "@/lib/cards";
import { CARD, CARD_LABEL, PRIMARY_BUTTON, SECONDARY_BUTTON, TEXT_BUTTON } from "@/lib/ui-classes";

const CONFLICT = 409;

export function NoteCardPanel({
  noteId,
  searched,
  candidateIds,
  savedCount,
}: {
  noteId: number;
  searched: boolean | null; // null = 불러오지 못함
  candidateIds: number[];
  savedCount: number;
}) {
  const router = useRouter();
  const find = useMutation({
    mutationFn: () => findCandidates(noteId),
    onSuccess: () => router.refresh(),
    onError: (error) => {
      // 409 "이미 찾았어요"(다른 탭에서 먼저 찾음) — 새로 받아 후보를 보여 준다
      if (error instanceof ApiRequestError && error.status === CONFLICT) router.refresh();
    },
  });

  return (
    <section aria-labelledby="note-card-title" className={`${CARD} flex flex-col gap-3`}>
      <h2 id="note-card-title" className={CARD_LABEL}>
        경험 카드
      </h2>

      {searched === null ? (
        <p role="alert" className="text-body-2 font-medium text-error-text">
          경험 카드를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      ) : searched ? (
        <div className="flex flex-col gap-3">
          <p className="text-body-2 text-text-sub">
            {candidateIds.length > 0
              ? `검토할 후보 ${candidateIds.length}개가 있어요. 맞는 것만 카드로 저장해요.`
              : "이 노트의 후보는 모두 검토했어요."}
            {savedCount > 0 ? ` 저장한 카드 ${savedCount}장.` : ""}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            {candidateIds.length > 0 ? (
              <CardReviewButton cardIds={candidateIds} label={`후보 ${candidateIds.length}개 검토`} className={PRIMARY_BUTTON} />
            ) : null}
            {savedCount > 0 ? (
              <Link href="/cards" className={TEXT_BUTTON}>
                내 카드 보기
              </Link>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {/* 설계 원칙 6: AI에 무엇을 보내는지 누르기 전에 알린다 */}
          <p className="text-body-2 text-text-sub">
            이 노트를 앞에서부터 AI에 보내 경험(상황 · 과제 · 행동 · 결과)을 최대 {CARD_MAX_CANDIDATES_PER_NOTE}개 찾아요.
            칸마다 원문 문장을 그대로 골라 오고, 원문에 없으면 빈칸으로 둬요. 오늘 AI 사용량 1회를 써요.
          </p>
          <button
            type="button"
            onClick={() => find.mutate()}
            disabled={find.isPending}
            className={`${SECONDARY_BUTTON} self-start`}
          >
            {find.isPending ? "찾는 중…" : "카드 후보 찾기"}
          </button>
          {find.isPending ? (
            <p role="status" className="text-body-2 text-text-sub">
              경험을 찾고 있어요. AI 답을 기다리느라 1~2분 걸릴 수 있어요.
            </p>
          ) : null}
        </div>
      )}

      {find.data ? <FindSummary result={find.data} /> : null}
      {find.error ? <RequestErrorBlock error={find.error} /> : null}
    </section>
  );
}

function FindSummary({ result }: { result: FindResult }) {
  const found = result.cardIds.length;
  return (
    <div role="status" className="flex flex-col gap-1 text-body-2">
      <p className={found > 0 ? "font-medium text-success-text" : "font-medium text-text-main"}>
        {found > 0
          ? `✓ 카드 후보 ${found}개를 찾았어요.`
          : "원문에서 근거를 확인한 경험을 찾지 못했어요. 다시 시도할 수 있어요."}
      </p>
      {result.emptiedFields > 0 ? (
        <p className="text-text-sub">원문에 그대로 없는 문장 {result.emptiedFields}곳은 빈칸으로 돌렸어요.</p>
      ) : null}
      {result.chunksSent < result.chunksTotal ? (
        <p className="text-text-sub">
          노트가 길어 앞부분 {result.chunksSent}/{result.chunksTotal} 조각만 AI에 보냈어요.
        </p>
      ) : null}
      <p className="text-text-sub">오늘 남은 AI 사용: {result.remainingToday}회</p>
    </div>
  );
}
