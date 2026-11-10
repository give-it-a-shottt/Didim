import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { NOTE_KIND_LABELS, type NoteKind } from "@/lib/import-records";
import { NoteMarkdown } from "@/components/note-markdown";
import { getNote } from "@/lib/records";

export const metadata: Metadata = {
  title: "노트 상세",
  description: "노트의 개념과 문제, 원문을 봐요.",
};

// 노트 · 조각 번호는 DB integer(32비트) 범위의 양수만. 더 긴 숫자는 Number()가 정밀도를 잃으므로 먼저 거른다(1차 리뷰 E).
// 서버(backend/app/api/notes.py MAX_NOTE_ID)와 같은 값이다.
const MAX_DB_ID = 2_147_483_647;

function parseDbId(value: unknown): number | null {
  if (typeof value !== "string" || !/^[1-9]\d{0,9}$/.test(value)) {
    return null;
  }
  const id = Number(value);
  return id <= MAX_DB_ID ? id : null;
}

function kindLabel(kind: string): string {
  return kind in NOTE_KIND_LABELS ? NOTE_KIND_LABELS[kind as NoteKind] : kind;
}

// REV_01_002 노트 상세. 1차로 원문 + 검색 · 근거에서 고른 조각 위치 강조(F-003)만 있다.
// 개념 · 문제 탭은 퀴즈 · 복습(F-004)에서 붙인다. ?chunk=조각ID 이면 그 구간을 강조하고 #chunk-ID로 스크롤한다.
export default async function Rev01002Page(props: PageProps<"/records/[noteId]">) {
  const { noteId } = await props.params;
  const { chunk } = await props.searchParams;
  const id = parseDbId(noteId);
  if (id === null) {
    notFound();
  }

  const outcome = await getNote(id);
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
          {kindLabel(note.kind)} · 조각 {note.chunks.length}개
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

      <section aria-labelledby="note-original-title" className="flex flex-col gap-2">
        <h2 id="note-original-title" className="text-title-3 font-semibold">
          원문
        </h2>
        {/* 내 기록 원문. 명조 글꼴은 Q-018(글꼴 넣기)을 정한 뒤 적용한다. */}
        <div className="wrap-break-word rounded-card border border-line-regular bg-bg-default p-6 text-text-main">
          <NoteMarkdown content={note.content} chunks={note.chunks} highlightChunkId={selected?.id ?? null} />
        </div>
      </section>

      <p className="text-body-3 text-text-sub-weak">개념 · 문제 탭은 퀴즈 · 복습 기능에서 붙어요.</p>
    </article>
  );
}
