import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { noteKindLabel } from "@/lib/import-records";
import { NoteMarkdown } from "@/components/note-markdown";
import { NoteQuizPanel } from "@/components/note-quiz-panel";
import { parseDbId } from "@/lib/ids";
import { getNoteQuizzes } from "@/lib/quiz-data";
import { getNote } from "@/lib/records";

export const metadata: Metadata = {
  title: "노트 상세",
  description: "노트로 문제를 만들어 풀고, 원문을 봐요.",
};


// REV_01_002 노트 상세: 문제(F-004 — [문제 만들기] · [이 노트 풀기]) + 원문(검색 · 근거에서 고른 조각 위치 강조, F-003).
// 개념 탭은 아직 없다(F-004 완료 기준 밖). ?chunk=조각ID 이면 그 구간을 강조하고 #chunk-ID로 스크롤한다.
export default async function Rev01002Page(props: PageProps<"/records/[noteId]">) {
  const { noteId } = await props.params;
  const { chunk } = await props.searchParams;
  const id = parseDbId(noteId);
  if (id === null) {
    notFound();
  }

  // 노트와 문제 목록을 같이 부른다(서로 기다리지 않게)
  const [outcome, quizOutcome] = await Promise.all([getNote(id), getNoteQuizzes(id)]);
  if (outcome.status === "not-found") {
    notFound();
  }
  if (outcome.status === "error") {
    return (
      <section data-screen-id="REV_01_002" aria-labelledby="note-title" className="flex flex-col gap-4 p-8">
        <h1 id="note-title" className="text-title-1 font-semibold">
          노트 상세
        </h1>
        <p role="alert" className="text-body-2 font-medium text-error-text">
          노트를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      </section>
    );
  }

  const { note } = outcome;
  const chunkId = parseDbId(chunk);
  const selected = chunkId === null ? undefined : note.chunks.find((item) => item.id === chunkId);

  return (
    <article data-screen-id="REV_01_002" aria-labelledby="note-title" className="flex flex-col gap-6 p-8">
      <header className="flex flex-col gap-1">
        <Link href="/records" className="text-body-3 text-text-sub hover:underline">
          ← 기록 · 복습
        </Link>
        <p className="text-body-3 text-text-sub">
          {noteKindLabel(note.kind)} · 조각 {note.chunks.length}개
        </p>
        <h1 id="note-title" className="text-title-1 font-semibold">
          {note.title}
        </h1>
      </header>

      {selected ? (
        <p className="text-body-2 text-primary-text">
          고른 부분: {selected.headingPath || "첫 제목 앞"}
        </p>
      ) : null}

      <NoteQuizPanel
        noteId={note.id}
        quizCount={quizOutcome.status === "ok" ? quizOutcome.quizzes.length : null}
      />

      <section aria-labelledby="note-original-title" className="flex flex-col gap-2">
        <h2 id="note-original-title" className="text-title-3 font-semibold">
          원문
        </h2>
        {/* 내 기록 원문. 명조 글꼴은 Q-018(글꼴 넣기)을 정한 뒤 적용한다. */}
        <div className="wrap-break-word rounded-card border border-line-regular bg-bg-default p-6 text-text-main">
          <NoteMarkdown content={note.content} chunks={note.chunks} highlightChunkId={selected?.id ?? null} />
        </div>
      </section>
    </article>
  );
}
