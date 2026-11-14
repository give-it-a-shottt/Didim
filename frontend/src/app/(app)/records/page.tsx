import type { Metadata } from "next";
import Form from "next/form";
import Link from "next/link";
import { type ReactNode, Suspense } from "react";
import { HighlightedText } from "@/components/highlighted-text";
import { Icon } from "@/components/icon";
import { AddRecordButton } from "@/components/import-records-dialog";
import { EmptyState, PageBody, PageHeader } from "@/components/page-parts";
import { noteKindLabel } from "@/lib/import-records";
import { getTodayReviews, getWrongAnswers } from "@/lib/quiz-data";
import { listNotes, MAX_SEARCH_QUERY_CHARS, searchRecords } from "@/lib/records";
import { BADGE_LINE, CARD, CARD_LABEL, FOCUS_RING, LIST_ROW, PRIMARY_BUTTON_S, TEXT_BUTTON } from "@/lib/ui-classes";

export const metadata: Metadata = {
  title: "기록 · 복습",
  description: "올린 노트와 오늘 복습할 문제를 보고, 내 기록을 검색해요.",
};

// REV_01_001 기록 · 복습 홈(Figma 26:335): 오늘 복습 · 오답노트 카드(F-004) + 노트 목록 카드(검색 F-003 · 목록 F-004).
// Figma에 있지만 아직 데이터가 없는 것(이번 주 정답률, 예상 시간, 노트별 다음 복습, 종류 탭)은 그리지 않는다(D-019 — 가짜 화면 금지).
// 각 칸은 서로 기다리지 않게 각자 Suspense 안에서 받는다.
// 검색어는 주소의 ?q=로 받아 서버에서 결과를 그린다(사용자 확인: GET, D-012 서버 데이터는 서버 컴포넌트).
export default async function Rev01001Page(props: PageProps<"/records">) {
  const { q } = await props.searchParams;
  const query = (typeof q === "string" ? q : "").trim().slice(0, MAX_SEARCH_QUERY_CHARS);

  return (
    <section data-screen-id="REV_01_001" aria-labelledby="records-title">
      <PageHeader
        titleId="records-title"
        title="기록 · 복습"
        description="오늘 차례인 문제를 풀고, 내 기록을 찾아봐요."
        actions={<AddRecordButton variant="page" />}
      />
      <PageBody>
        <div className="grid gap-6 sm:grid-cols-2">
          <Suspense fallback={<LoadingCard label="오늘 복습" message="오늘 복습을 확인하고 있어요…" />}>
            <TodayReviewCard />
          </Suspense>
          <Suspense fallback={<LoadingCard label="오답노트" message="오답노트를 확인하고 있어요…" />}>
            <WrongAnswersCard />
          </Suspense>
        </div>

        <Suspense
          fallback={
            <NotesPanel heading="노트" query={query}>
              <p role="status" className="py-4 text-body-2 text-text-sub">
                노트 목록을 불러오고 있어요…
              </p>
            </NotesPanel>
          }
        >
          <Notes query={query} />
        </Suspense>
      </PageBody>
    </section>
  );
}

// '오늘 복습' · '오답노트' 카드: 제목을 크게(18), 아래 한 줄에 문제 수(15 · 약한 색) + 행동(버튼 S)을 가로로(사용자 화면 확인 2026-11-14)
const SUMMARY_TITLE = "text-title-3 font-semibold text-text-main";
const SUMMARY_ROW = "flex min-h-10 flex-wrap items-center justify-between gap-3";
const SUMMARY_COUNT = "text-body-1 font-medium text-text-sub";

function LoadingCard({ label, message }: { label: string; message: string }) {
  return (
    <div className={`${CARD} flex flex-col gap-3`}>
      <p className={CARD_LABEL}>{label}</p>
      <p role="status" className="text-body-2 text-text-sub">
        {message}
      </p>
    </div>
  );
}

async function TodayReviewCard() {
  const outcome = await getTodayReviews();
  return (
    <section aria-labelledby="today-review-title" className={`${CARD} flex flex-col gap-3`}>
      <h2 id="today-review-title" className={SUMMARY_TITLE}>
        오늘 복습
      </h2>
      {outcome.status !== "ok" ? (
        <p role="alert" className="text-body-2 font-medium text-error-text">
          오늘 복습을 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      ) : (
        <>
          <div className={SUMMARY_ROW}>
            <p className={SUMMARY_COUNT}>{outcome.total}문제</p>
            {outcome.total > 0 ? (
              <Link href="/quiz/today" className={PRIMARY_BUTTON_S}>
                복습 시작
              </Link>
            ) : null}
          </div>
          {outcome.total === 0 ? (
            <p className="text-body-3 text-text-sub">
              오늘 복습할 문제가 없어요. 노트에서 [문제 만들기]로 문제를 만들 수 있어요.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

async function WrongAnswersCard() {
  const outcome = await getWrongAnswers();
  return (
    <section aria-labelledby="wrong-card-title" className={`${CARD} flex flex-col gap-3`}>
      <h2 id="wrong-card-title" className={SUMMARY_TITLE}>
        오답노트
      </h2>
      {outcome.status !== "ok" ? (
        <p role="alert" className="text-body-2 font-medium text-error-text">
          오답노트를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      ) : null}
      <div className={SUMMARY_ROW}>
        {outcome.status === "ok" ? <p className={SUMMARY_COUNT}>{outcome.total}문제</p> : <span />}
        <Link href="/records/wrong-answers" className={TEXT_BUTTON}>
          오답노트 보기 <span aria-hidden="true">→</span>
        </Link>
      </div>
    </section>
  );
}

/** 노트 목록 카드 틀: 위 줄 = 제목(노트 N) + 오른쪽 검색 입력칸(Figma '노트 검색'), 아래 = 검색 결과 · 목록. */
function NotesPanel({ heading, query, children }: { heading: string; query: string; children: ReactNode }) {
  return (
    <section aria-labelledby="note-list-title" className={`${CARD} flex flex-col gap-2`}>
      <div className="flex flex-wrap items-center gap-4">
        <h2 id="note-list-title" className="flex-1 text-title-4 font-semibold text-text-main">
          {heading}
        </h2>
        <SearchForm query={query} />
      </div>
      {children}
    </section>
  );
}

// 검색 입력칸(Figma Input Line M + icon/search). Enter로 보낸다 — Figma에 버튼이 없어 따로 두지 않는다.
function SearchForm({ query }: { query: string }) {
  return (
    <Form action="/records" role="search" aria-label="기록 검색" className="w-full sm:w-70">
      <label
        htmlFor="record-search"
        className={`flex h-10 items-center gap-1.5 rounded-input border border-line-input bg-bg-default px-3 hover:border-line-input-hover has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-primary-default`}
      >
        <Icon name="search" size={20} className="text-icon-main" />
        <span className="sr-only">기록 검색어</span>
        <input
          id="record-search"
          type="search"
          name="q"
          defaultValue={query}
          maxLength={MAX_SEARCH_QUERY_CHARS}
          placeholder="노트 검색"
          className="min-w-0 flex-1 bg-transparent text-body-1 text-text-main outline-none placeholder:text-text-sub-weak"
        />
      </label>
    </Form>
  );
}

async function Notes({ query }: { query: string }) {
  const outcome = await listNotes();

  if (outcome.status === "ok" && outcome.notes.length === 0 && !query) {
    // REV_01_900 빈 상태(Figma 26:732): 목록 카드 대신 다음 행동을 안내한다
    return (
      <EmptyState
        screenId="REV_01_900"
        title="기록을 올리면 문제가 생겨요"
        description="공부한 마크다운 노트를 올리면 객관식 · OX 문제를 만들어 드려요."
        action={<AddRecordButton variant="primary" />}
      />
    );
  }

  return (
    <NotesPanel heading={`노트 ${outcome.status === "ok" ? outcome.total : ""}`} query={query}>
      {query ? (
        <Suspense
          key={query}
          fallback={
            <p role="status" className="py-4 text-body-2 text-text-sub">
              기록을 찾고 있어요…
            </p>
          }
        >
          <SearchResults query={query} />
        </Suspense>
      ) : null}

      {outcome.status !== "ok" ? (
        <p role="alert" className="py-4 text-body-2 font-medium text-error-text">
          노트 목록을 불러오지 못했어요. 잠시 뒤 다시 해 주세요.
        </p>
      ) : (
        <>
          <ul>
            {outcome.notes.map((note) => (
              <li key={note.id}>
                <Link href={`/records/${note.id}`} className={`group ${LIST_ROW} ${FOCUS_RING}`}>
                  <Icon name="notebook" size={20} className="text-icon-sub" />
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="truncate text-body-1 font-medium text-text-main group-hover:underline">
                      {note.title}
                    </span>
                    <span className="text-body-4 text-text-sub">
                      {noteKindLabel(note.kind)} · 조각 {note.chunkCount}개
                    </span>
                  </span>
                  {note.quizCount > 0 ? (
                    <span className={BADGE_LINE}>문제 {note.quizCount}개</span>
                  ) : (
                    <span className="shrink-0 text-body-4 text-text-sub">문제 없음</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
          {outcome.total > outcome.notes.length ? (
            <p className="pt-2 text-body-3 text-text-sub">
              최근 올린 {outcome.notes.length}개만 보여요. 다른 노트는 검색으로 찾아 주세요.
            </p>
          ) : null}
        </>
      )}
    </NotesPanel>
  );
}

async function SearchResults({ query }: { query: string }) {
  const outcome = await searchRecords(query);

  if (outcome.status !== "ok") {
    const message = outcome.status === "unavailable" ? outcome.message : "검색하지 못했어요. 잠시 뒤 다시 해 주세요.";
    return (
      <p role="alert" className="py-4 text-body-2 font-medium text-error-text">
        {message}
      </p>
    );
  }

  if (outcome.results.length === 0) {
    return (
      <p role="status" className="py-4 text-body-2 text-text-sub">
        ‘{query}’와 맞는 기록이 없어요. 다른 낱말로 찾아보세요.
      </p>
    );
  }

  return (
    <section aria-labelledby="search-results-title" className="flex flex-col pt-2 pb-4">
      <h3 id="search-results-title" className={CARD_LABEL}>
        ‘{query}’ 검색 결과 {outcome.results.length}개
      </h3>
      <ol>
        {outcome.results.map((result) => (
          <li key={result.chunkId}>
            <Link
              href={`/records/${result.noteId}?chunk=${result.chunkId}#chunk-${result.chunkId}`}
              className={`group flex flex-col gap-1 border-b border-line-light py-4 ${FOCUS_RING}`}
            >
              <span className="text-body-1 font-medium text-text-main group-hover:underline">{result.noteTitle}</span>
              {result.headingPath ? <span className="text-body-4 text-text-sub">{result.headingPath}</span> : null}
              {/* 내 기록 원문 발췌 → 명조(설계 원칙 7) */}
              <span className="font-serif text-quote text-text-sub">
                <HighlightedText text={result.excerpt} terms={result.matchedTerms} />
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
