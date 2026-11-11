// 경험 카드 화면(후보 검토 시트 · 카드 상세)이 같이 쓰는 원문 인용 부품 (F-006 1차 리뷰 R1). 요청 실패 문구는 request-error.tsx.
import Link from "next/link";
import { SourceQuote } from "@/components/page-parts";
import { evidenceHref } from "@/lib/quiz";

/** 원문 인용(명조) + 근거 링크. 노트나 조각이 지워졌으면 '원문 없음'(인용 글은 카드에 남아 있음). */
export function CardQuote({ quote, noteId, chunkId }: { quote: string; noteId: number | null; chunkId: number | null }) {
  return (
    <SourceQuote
      quote={quote}
      source={
        noteId !== null && chunkId !== null ? (
          <Link href={evidenceHref(noteId, chunkId)} className="underline">
            원문에서 보기
          </Link>
        ) : (
          "원문 없음"
        )
      }
    />
  );
}
