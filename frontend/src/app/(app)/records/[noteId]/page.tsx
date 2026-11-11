import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { noteKindLabel } from "@/lib/import-records";
import { NoteCardPanel } from "@/components/note-card-panel";
import { NoteMarkdown } from "@/components/note-markdown";
import { NoteQuizPanel } from "@/components/note-quiz-panel";
import { PageBody, PageHeader } from "@/components/page-parts";
import { getCardList } from "@/lib/cards-data";
import { parseDbId } from "@/lib/ids";
import { noteSessionHref } from "@/lib/quiz";
import { getNoteQuizzes } from "@/lib/quiz-data";
import { getNote } from "@/lib/records";
import { CARD, CARD_LABEL, PRIMARY_BUTTON } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "노트 상세",
  description: "노트로 문제를 만들어 풀고, 경험 카드 후보를 찾고, 원문을 봐요.",
};

// REV_01_002 노트 상세(Figma 26:490): 머리 [이 노트 풀기] + 왼쪽 원문(검색 · 근거에서 고른 조각 위치 강조, F-003)
// + 오른쪽 문제 칸(F-004 — [문제 만들기]) + 경험 카드 칸(F-006 — [카드 후보 찾기] · 후보 검토). Figma의 개념 탭 · 복습 상태(최근 정답 · 간격 · 자주 틀린 개념)는
// 데이터가 없어 그리지 않는다(D-019). ?chunk=조각ID 이면 그 구간을 강조하고 #chunk-ID로 스크롤한다.
export default async function Rev01002Page(props: PageProps<"/records/[noteId]">) {
  const { noteId } = await props.params;
  const { chunk } = await props.searchParams;
  const id = parseDbId(noteId);
  if (id === null) {
    notFound();
  }

  // 노트 · 문제 · 이 노트의 카드(후보 · 저장)를 같이 부른다(서로 기다리지 않게)
  const [outcome, quizOutcome, candidates, saved] = await Promise.all([
    getNote(id),
    getNoteQuizzes(id),
    getCardList("candidate", id),
    getCardList("saved", id),
  ]);
  if (outcome.status === "not-found") {
    notFound();
  }
  if (outcome.status === "error") {
    return (
      <section data-screen-id="REV_01_002" aria-labelledby="note-title">
        <PageHeader titleId="note-title" title="노트 상세" />
        <PageBody>
          <p role="alert" className="text-body-2 font-medium text-error-text">
            노트를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
          </p>
        </PageBody>
      </section>
    );
  }

  const { note } = outcome;
  const chunkId = parseDbId(chunk);
  const selected = chunkId === null ? undefined : note.chunks.find((item) => item.id === chunkId);
  const quizCount = quizOutcome.status === "ok" ? quizOutcome.quizzes.length : null;
  const cardsLoaded = candidates.status === "ok" && saved.status === "ok";

  return (
    <article data-screen-id="REV_01_002" aria-labelledby="note-title">
      <PageHeader
        titleId="note-title"
        title={note.title}
        description={`${noteKindLabel(note.kind)} · 조각 ${note.chunks.length}개`}
        actions={
          quizCount !== null && quizCount > 0 ? (
            <Link href={noteSessionHref(note.id)} className={PRIMARY_BUTTON}>
              이 노트 풀기
            </Link>
          ) : null
        }
      />
      <PageBody>
        <div className="grid items-start gap-6 lg:grid-cols-12">
          {/* 좁은 화면에서는 문제 칸이 원문보다 먼저 보이게 앞에 두고, 넓은 화면에서 오른쪽으로 보낸다 */}
          <div className="flex flex-col gap-6 lg:order-last lg:col-span-4">
            <NoteQuizPanel noteId={note.id} quizCount={quizCount} />
            <NoteCardPanel
              noteId={note.id}
              searched={cardsLoaded ? candidates.noteSearched === true : null}
              candidateIds={candidates.status === "ok" ? candidates.cards.map((card) => card.id) : []}
              savedCount={saved.status === "ok" ? saved.total : 0}
            />
          </div>

          <section aria-labelledby="note-original-title" className={`${CARD} flex flex-col gap-3 lg:col-span-8`}>
            <h2 id="note-original-title" className={CARD_LABEL}>
              원문
            </h2>
            {selected ? (
              <p className="text-body-2 text-primary-text">고른 부분: {selected.headingPath || "첫 제목 앞"}</p>
            ) : null}
            {/* 내 기록 원문 → 명조(설계 원칙 7). 코드 블록은 note-markdown.tsx에서 고정폭 글꼴 */}
            <div className="font-serif wrap-break-word text-text-main">
              <NoteMarkdown content={note.content} chunks={note.chunks} highlightChunkId={selected?.id ?? null} />
            </div>
          </section>
        </div>
      </PageBody>
    </article>
  );
}
