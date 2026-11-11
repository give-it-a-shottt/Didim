import type { Metadata } from "next";
import Form from "next/form";
import Link from "next/link";
import { Suspense } from "react";
import { HighlightedText } from "@/components/highlighted-text";
import { AddRecordButton } from "@/components/import-records-dialog";
import { noteKindLabel } from "@/lib/import-records";
import { getTodayReviews } from "@/lib/quiz-data";
import { listNotes, MAX_SEARCH_QUERY_CHARS, searchRecords } from "@/lib/records";
import { FOCUS_RING, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "기록 · 복습",
  description: "올린 노트와 오늘 복습할 문제를 보고, 내 기록을 검색해요.",
};

// REV_01_001 기록 · 복습 홈: 오늘 복습 N(F-004) · 기록 검색(F-003) · 노트 목록(F-004, 사용자 확인 2026-11-11).
// 오늘 복습 · 노트 목록은 서로 기다리지 않게 각자 Suspense 안에서 받는다.
// 검색어는 주소의 ?q=로 받아 서버에서 결과를 그린다(사용자 확인: GET, D-012 서버 데이터는 서버 컴포넌트).
export default async function Rev01001Page(props: PageProps<"/records">) {
  const { q } = await props.searchParams;
  const query = (typeof q === "string" ? q : "").trim().slice(0, MAX_SEARCH_QUERY_CHARS);

  return (
    <section data-screen-id="REV_01_001" aria-labelledby="records-title" className="flex flex-col gap-6 p-8">
      <header className="flex flex-col gap-1">
        <h1 id="records-title" className="text-title-1 font-semibold">
          기록 · 복습
        </h1>
        <p className="text-body-2 text-text-sub">오늘 차례인 문제를 풀고, 내 기록을 찾아봐요.</p>
      </header>

      <Suspense
        fallback={
          <p role="status" className="text-body-2 text-text-sub">
            오늘 복습을 확인하고 있어요…
          </p>
        }
      >
        <TodayReview />
      </Suspense>

      <Form action="/records" role="search" aria-label="기록 검색" className="flex gap-2">
        <label htmlFor="record-search" className="sr-only">
          기록 검색어
        </label>
        <input
          id="record-search"
          type="search"
          name="q"
          defaultValue={query}
          maxLength={MAX_SEARCH_QUERY_CHARS}
          placeholder="예: useEffect, 인덱스는 언제 쓰나요"
          className={`h-10 flex-1 rounded-input border border-line-input bg-bg-default px-3 text-body-2 text-text-main ${FOCUS_RING}`}
        />
        <button
          type="submit"
          className={`inline-flex h-10 items-center justify-center rounded-button bg-primary-default px-4 text-body-2 font-medium text-text-on-primary hover:bg-primary-hover ${FOCUS_RING}`}
        >
          검색
        </button>
      </Form>

      {query ? (
        <Suspense
          key={query}
          fallback={
            <p role="status" className="text-body-2 text-text-sub">
              기록을 찾고 있어요…
            </p>
          }
        >
          <SearchResults query={query} />
        </Suspense>
      ) : null}

      <Suspense
        fallback={
          <p role="status" className="text-body-2 text-text-sub">
            노트 목록을 불러오고 있어요…
          </p>
        }
      >
        <NoteList />
      </Suspense>
    </section>
  );
}

async function SearchResults({ query }: { query: string }) {
  const outcome = await searchRecords(query);

  if (outcome.status !== "ok") {
    const message = outcome.status === "unavailable" ? outcome.message : "검색하지 못했어요. 잠시 뒤 다시 해 주세요.";
    return (
      <p role="alert" className="text-body-2 font-medium text-error-text">
        {message}
      </p>
    );
  }

  if (outcome.results.length === 0) {
    return (
      <p role="status" className="text-body-2 text-text-sub">
        ‘{query}’와 맞는 기록이 없어요. 다른 낱말로 찾아보세요.
      </p>
    );
  }

  return (
    <section aria-labelledby="search-results-title" className="flex flex-col gap-3">
      <h2 id="search-results-title" className="text-title-3 font-semibold">
        ‘{query}’ 검색 결과 {outcome.results.length}개
      </h2>
      <ol className="flex flex-col gap-2">
        {outcome.results.map((result) => (
          <li key={result.chunkId}>
            <Link
              href={`/records/${result.noteId}?chunk=${result.chunkId}#chunk-${result.chunkId}`}
              className={`flex flex-col gap-1 rounded-card border border-line-regular bg-bg-default p-4 hover:bg-bg-hover ${FOCUS_RING}`}
            >
              <span className="text-body-1 font-semibold text-text-main">{result.noteTitle}</span>
              {result.headingPath ? <span className="text-body-4 text-text-sub">{result.headingPath}</span> : null}
              {/* 내 기록 원문 발췌. 명조 글꼴은 Q-018(글꼴 넣기)을 정한 뒤 적용한다. */}
              <span className="text-body-2 text-text-sub">
                <HighlightedText text={result.excerpt} terms={result.matchedTerms} />
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}


async function TodayReview() {
  const outcome = await getTodayReviews();
  return (
    <section
      aria-labelledby="today-review-title"
      className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-line-regular bg-bg-default p-6"
    >
      <div className="flex flex-col gap-1">
        <h2 id="today-review-title" className="text-title-3 font-semibold">
          오늘 복습 {outcome.status === "ok" ? outcome.total : ""}
        </h2>
        {outcome.status !== "ok" ? (
          <p role="alert" className="text-body-2 font-medium text-error-text">
            오늘 복습을 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
          </p>
        ) : (
          <p className="text-body-2 text-text-sub">
            {outcome.total > 0
              ? `모든 노트에서 오늘 차례인 문제 ${outcome.total}개예요.`
              : "오늘 복습할 문제가 없어요. 노트에서 [문제 만들기]로 문제를 만들 수 있어요."}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {outcome.status === "ok" && outcome.total > 0 ? (
          <Link href="/quiz/today" className={PRIMARY_BUTTON}>
            복습 시작
          </Link>
        ) : null}
        <Link href="/records/wrong-answers" className={SECONDARY_BUTTON}>
          오답노트
        </Link>
      </div>
    </section>
  );
}

async function NoteList() {
  const outcome = await listNotes();
  return (
    <section aria-labelledby="note-list-title" className="flex flex-col gap-3">
      <h2 id="note-list-title" className="text-title-3 font-semibold">
        노트 {outcome.status === "ok" ? outcome.total : ""}
      </h2>
      {outcome.status !== "ok" ? (
        <p role="alert" className="text-body-2 font-medium text-error-text">
          노트 목록을 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      ) : outcome.notes.length === 0 ? (
        // REV_01_900 빈 상태
        <div data-screen-id="REV_01_900" className="flex flex-col items-start gap-3">
          <p className="text-body-2 text-text-sub">기록을 올리면 문제가 생겨요.</p>
          <AddRecordButton />
        </div>
      ) : (
        <>
          <ul className="flex flex-col gap-2">
            {outcome.notes.map((note) => (
              <li key={note.id}>
                <Link
                  href={`/records/${note.id}`}
                  className={`flex flex-col gap-1 rounded-card border border-line-regular bg-bg-default p-4 hover:bg-bg-hover ${FOCUS_RING}`}
                >
                  <span className="text-body-1 font-semibold text-text-main">{note.title}</span>
                  <span className="text-body-4 text-text-sub">
                    {noteKindLabel(note.kind)} · 조각 {note.chunkCount}개 ·{" "}
                    {note.quizCount > 0 ? `문제 ${note.quizCount}개` : "문제 없음"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          {outcome.total > outcome.notes.length ? (
            <p className="text-body-3 text-text-sub">
              최근 올린 {outcome.notes.length}개만 보여요. 다른 노트는 검색으로 찾아 주세요.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
