"use client";

// 기록 추가 모달(IMP_01_001 올리기 → 002 처리 중 → 003 결과 요약 · 900 오류, Figma 25:268 · 25:419 · 25:503 · 25:587).
// URL 없이 [기록 추가] 버튼으로 연다.
// 1주차(F-002)는 읽기 · 나누기까지. 요청 한 번에 처리하므로 002는 요청 동안의 진행 표시만 한다(Q-008).
// 가져올 곳 탭: 마크다운 파일(F-002) · 노션 연결(F-005 — 연결된 노션에서 페이지를 골라 가져옴). 결과 요약은 같이 쓴다.
// 고른 파일 · 페이지 · 단계 상태는 이 모달 안에서만 쓰여 useState로 둔다. 노션 페이지 목록은 서버 데이터라
// TanStack Query(useQuery, 키 ["notion", "pages"]) — 가져온 뒤 무효화해 '이미 가져옴'을 새로 받는다(D-012, architecture.md 상태 관리 지도).
//
// 나눈 방식
// - AddRecordButton: 버튼 + <dialog> 열고 닫기만 맡는다.
// - ImportFlow: 단계(올리기 → 처리 중 → 결과 · 오류)와 업로드. 열 때마다 새로 그려 상태가 처음으로 돌아간다.
// - SelectStep · NotionPicker · ProcessingStep · ResultSummary · FailedList: 각 화면(StepHeader = 위 줄 제목 + 1 / 3).

import { type DragEvent, type RefObject, useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Icon } from "@/components/icon";
import { ApiRequestError } from "@/lib/api-request";
import {
  NOTION_MAX_IMPORT_PAGES,
  NOTION_MAX_PAGE_LIST,
  type NotionImportResult,
  fetchNotionPages,
  importNotionPages,
} from "@/lib/notion";
import {
  FOCUS_RING,
  GHOST_BUTTON,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_S,
  TEXT_BUTTON,
} from "@/lib/ui-classes";
import {
  ACCEPTED_EXTENSIONS,
  MAX_IMPORT_FILE_MB,
  MAX_IMPORT_FILES,
  NOTE_KIND_LABELS,
  checkSelection,
  importMarkdownFiles,
  type ImportResponse,
  type NoteKind,
} from "@/lib/import-records";

type Source = "markdown" | "notion";

// 노션 결과에만 있는 안내(건너뛴 블록 수 · 도중에 연결이 끊김)
type NotionExtra = Pick<NotionImportResult, "skippedBlocks" | "connectionBroken">;

type Step =
  | { name: "select" }
  | { name: "processing" }
  | { name: "result"; data: ImportResponse; notion: NotionExtra | null }
  | { name: "error"; message: string; needsLogin: boolean; failed: ImportResponse["failed"] };

const NOTION_PAGES_KEY = ["notion", "pages"] as const;

// [기록 추가] 버튼 모양 3가지(모두 같은 모달을 연다):
// - sidebar: Figma Didim/사이드바(17:241 · 17:288) — 테두리 line/strong, 글자 text/sub. 펼침(lg 이상) = 아이콘 + 글자로
//   너비 채움, 접힘 = 40×40 아이콘 버튼(글자는 화면 읽기 프로그램에만).
// - page: 페이지 머리 오른쪽(REV_01_001) — 검정 Outline + 아이콘.
// - primary: 빈 화면(REV_01_900)의 다음 행동 — Primary.
const TRIGGER_CLASS = {
  sidebar: `flex h-10 w-full items-center justify-center gap-1.5 rounded-button border border-line-strong bg-bg-default text-body-1 font-semibold text-text-sub hover:bg-bg-hover lg:px-4 ${FOCUS_RING}`,
  page: SECONDARY_BUTTON,
  primary: PRIMARY_BUTTON,
} as const;

export function AddRecordButton({ variant = "sidebar" }: { variant?: keyof typeof TRIGGER_CLASS }) {
  const router = useRouter();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [openCount, setOpenCount] = useState(0); // 열 때마다 ImportFlow를 새로 그리는 key
  const [isBusy, setIsBusy] = useState(false);
  const savedRef = useRef(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (isOpen && !dialog.open) dialog.showModal();
    if (!isOpen && dialog.open) dialog.close();
  }, [isOpen]);

  function open() {
    savedRef.current = false;
    setOpenCount((count) => count + 1);
    setIsOpen(true);
  }

  function close() {
    setIsOpen(false);
    // 저장된 노트가 있으면 서버 컴포넌트가 그린 화면(목록 등)을 새로 받아 오게 한다
    if (savedRef.current) router.refresh();
  }

  return (
    <>
      <button
        type="button"
        onClick={open}
        className={TRIGGER_CLASS[variant]}
      >
        {variant === "sidebar" ? (
          <>
            <Icon name="plus" size={20} className="text-icon-sub" />
            <span className="sr-only lg:not-sr-only lg:whitespace-nowrap">기록 추가</span>
          </>
        ) : variant === "page" ? (
          <>
            <Icon name="plus" size={20} className="text-icon-main" />
            기록 추가
          </>
        ) : (
          "기록 추가"
        )}
      </button>

      <dialog
        ref={dialogRef}
        // 단계마다 위 제목이 바뀌어도(Figma: 기록 추가 → 노트를 정리하고 있어요 → …) 창 이름은 그대로 둔다
        aria-label="기록 추가"
        onCancel={(event) => {
          // 처리 중에는 Esc로 닫지 않는다(결과를 놓치지 않게)
          if (isBusy) event.preventDefault();
        }}
        onClose={() => {
          // Esc를 연달아 누르면 브라우저가 막기를 무시하고 닫을 수 있다 → 처리 중이면 바로 다시 연다(F-002 2차 R3)
          if (isBusy) {
            dialogRef.current?.showModal();
            return;
          }
          if (isOpen) close();
        }}
        // 모달 틀 — Figma IMP_01_001 모달(25:320): 너비 560, 위 28 · 옆 24 · 아래 24, 뒤는 bg/dim
        className="m-auto w-full max-w-140 rounded-modal bg-bg-elevated px-6 pt-7 pb-6 text-text-main backdrop:bg-bg-dim"
      >
        {isOpen ? (
          <ImportFlow
            key={openCount}
            onClose={close}
            onBusyChange={setIsBusy}
            onSaved={() => {
              savedRef.current = true;
            }}
          />
        ) : null}
      </dialog>
    </>
  );
}

function ImportFlow({
  onClose,
  onBusyChange,
  onSaved,
}: {
  onClose: () => void;
  onBusyChange: (busy: boolean) => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>({ name: "select" });
  const [source, setSource] = useState<Source>("markdown");
  const [files, setFiles] = useState<File[]>([]);
  const [pageIds, setPageIds] = useState<string[]>([]);
  const [kind, setKind] = useState<NoteKind>("study");

  function finish(data: ImportResponse, notion: NotionExtra | null) {
    const { summary, failed } = data;
    if (summary.notes > 0) onSaved();
    if (summary.notes === 0 && summary.duplicates === 0) {
      // 하나도 읽지 못함 → 오류 화면(IMP_01_900)
      const message = notion?.connectionBroken
        ? "노션 연결이 끊겼어요. 설정에서 다시 연결해 주세요."
        : notion
          ? "페이지를 읽지 못했어요."
          : "노트를 읽지 못했어요.";
      setStep({ name: "error", message, needsLogin: false, failed });
      return;
    }
    setStep({ name: "result", data, notion });
  }

  async function submitMarkdown() {
    // 버튼이 막혀 있어 보통 오지 않지만, 개수 · 용량 확인은 서버도 다시 한다
    if (files.length === 0 || checkSelection(files) !== null) return;

    setStep({ name: "processing" });
    onBusyChange(true);
    const outcome = await importMarkdownFiles(files, kind); // 예외를 던지지 않는다(import-records.ts)
    onBusyChange(false);

    if (!outcome.ok) {
      setStep({ name: "error", message: outcome.message, needsLogin: outcome.needsLogin, failed: [] });
      return;
    }
    finish(outcome.data, null);
  }

  async function submitNotion() {
    if (pageIds.length === 0 || pageIds.length > NOTION_MAX_IMPORT_PAGES) return;

    setStep({ name: "processing" });
    onBusyChange(true);
    try {
      const result = await importNotionPages(pageIds, kind);
      // 저장된 페이지가 있든 없든 '이미 가져옴' 표시와 연결 상태를 새로 받게 한다
      void queryClient.invalidateQueries({ queryKey: NOTION_PAGES_KEY });
      setPageIds([]);
      finish(result.data, { skippedBlocks: result.skippedBlocks, connectionBroken: result.connectionBroken });
    } catch (error) {
      const isApiError = error instanceof ApiRequestError;
      setStep({
        name: "error",
        message: isApiError ? error.message : "노션 페이지를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.",
        needsLogin: isApiError && error.needsLogin,
        failed: [],
      });
    } finally {
      onBusyChange(false);
    }
  }

  switch (step.name) {
    case "select":
      return (
        <SelectStep
          source={source}
          files={files}
          pageIds={pageIds}
          kind={kind}
          onSource={setSource}
          onFiles={setFiles}
          onPageIds={setPageIds}
          onKind={setKind}
          onCancel={onClose}
          onSubmit={source === "markdown" ? submitMarkdown : submitNotion}
        />
      );
    case "processing":
      return (
        <ProcessingStep
          message={
            source === "markdown"
              ? `파일 ${files.length}개를 읽고 조각으로 나누고 있어요.`
              : `노션 페이지 ${pageIds.length}개를 읽고 조각으로 나누고 있어요. 페이지가 많으면 몇 분 걸릴 수 있어요.`
          }
        />
      );
    case "result":
      return <ResultSummary data={step.data} notion={step.notion} onClose={onClose} />;
    case "error":
      return (
        <div data-screen-id="IMP_01_900" className="flex flex-col gap-5">
          <StepHeader title="가져오지 못했어요" />
          <p role="alert" className="text-body-2 font-medium text-error-text">
            {step.message}
          </p>
          {step.failed.length > 0 ? <FailedList failed={step.failed} /> : null}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={GHOST_BUTTON}>
              닫기
            </button>
            {step.needsLogin ? (
              <Link href="/login" className={PRIMARY_BUTTON}>
                다시 로그인
              </Link>
            ) : (
              <button type="button" onClick={() => setStep({ name: "select" })} className={PRIMARY_BUTTON}>
                다시 시도
              </button>
            )}
          </div>
        </div>
      );
  }
}

/** 모달 위 줄(Figma 25:321): 단계 제목(20 SemiBold) + 오른쪽 "1 / 3". 오류 화면은 단계 표시 없음. */
function StepHeader({ title, step }: { title: string; step?: 1 | 2 | 3 }) {
  return (
    <div className="flex items-center gap-2">
      <h2 className="flex-1 text-title-2 font-semibold text-text-main">{title}</h2>
      {step ? (
        <p className="shrink-0 text-body-3 text-text-sub">
          <span className="sr-only">단계 </span>
          {step} / 3
        </p>
      ) : null}
    </div>
  );
}

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))}KB` : `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

// 기록 종류 칩(Figma Tag S 32): 고름 = primary/soft 바탕 + primary 테두리 · 글자, 안 고름 = 흰 바탕 + line/regular
const KIND_CHIP =
  "inline-flex h-8 cursor-pointer items-center rounded-tag border px-3 text-body-3 font-medium has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-primary-default border-line-regular bg-bg-default text-text-main hover:bg-bg-hover has-checked:border-primary-default has-checked:bg-primary-soft has-checked:text-primary-text";

// 탭(Figma Tab Line Black M): 고름 = SemiBold + 아래 2px line/black, 안 고름 = text/sub-weak
const TAB_SELECTED =
  "relative inline-flex h-10 items-center px-3 text-body-2 font-semibold text-text-main after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-line-black";
const TAB_UNSELECTED = `inline-flex h-10 items-center px-3 text-body-2 font-medium text-text-sub-weak hover:text-text-main ${FOCUS_RING}`;

const SOURCE_LABELS: Record<Source, string> = { markdown: "마크다운 파일", notion: "노션 연결" };

// 드래그 앤 드롭(F-002 변경, 사용자 요청 2026-11-10): 브라우저 기본 기능(HTML5 Drag and Drop)만 쓴다.
// 올리기 단계 전체를 드롭 영역으로 둔다 — 칸을 빗나가게 놓아도 브라우저가 파일을 열어 화면을 잃지 않게.
// 놓은 파일은 "파일 선택"과 같은 길(onFiles → checkSelection)로 가고, 서버가 확장자 · 크기를 다시 확인한다.
// enabled가 아니면(노션 탭) 파일을 받지 않는다 — 놓아도 브라우저 기본 동작만 막는다.
function useFileDrop(onFiles: (files: File[]) => void, enabled: boolean) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  // 파일을 끌어오는 중인지(파일 칸 강조용). 안쪽 요소를 지날 때마다 enter/leave가 오므로 깊이로 센다.
  const [isDragging, setIsDragging] = useState(false);
  const dragDepth = useRef(0);
  const carriesFiles = (event: DragEvent) => Array.from(event.dataTransfer.types).includes("Files");
  const handlers = {
    onDragEnter: (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      dragDepth.current += 1;
      setIsDragging(true);
    },
    onDragOver: (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault(); // 이걸 막아야 drop이 온다
      event.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (dragDepth.current === 0) setIsDragging(false);
    },
    onDrop: (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault(); // 브라우저가 파일을 새 화면으로 여는 것을 막는다
      dragDepth.current = 0;
      setIsDragging(false);
      if (!enabled) return;
      if (fileInputRef.current) {
        fileInputRef.current.files = event.dataTransfer.files; // 입력칸 값도 놓은 파일과 맞춘다
      }
      onFiles(Array.from(event.dataTransfer.files));
    },
  };
  return { fileInputRef, isDragging, handlers };
}

// 올리기 단계: 기록 종류 · 가져올 곳 탭(마크다운 · 노션) · 안내 · 버튼. 탭 내용은 MarkdownPicker · NotionPicker.
function SelectStep({
  source,
  files,
  pageIds,
  kind,
  onSource,
  onFiles,
  onPageIds,
  onKind,
  onCancel,
  onSubmit,
}: {
  source: Source;
  files: File[];
  pageIds: string[];
  kind: NoteKind;
  onSource: (source: Source) => void;
  onFiles: (files: File[]) => void;
  onPageIds: (pageIds: string[]) => void;
  onKind: (kind: NoteKind) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const markdownTab = source === "markdown";
  const selectError = markdownTab ? checkSelection(files) : null;
  const tabPanelId = useId();
  const kindLegendId = useId();
  const drop = useFileDrop(onFiles, markdownTab);
  const count = markdownTab ? files.length : pageIds.length;

  return (
    <div data-screen-id="IMP_01_001" className="flex flex-col gap-5" {...drop.handlers}>
      <StepHeader title="기록 추가" step={1} />

      <fieldset aria-labelledby={kindLegendId} className="flex flex-col gap-3">
        <p id={kindLegendId} className="text-body-2 font-semibold text-text-sub">
          기록 종류
        </p>
        <div className="flex flex-wrap gap-2">
          {(Object.keys(NOTE_KIND_LABELS) as NoteKind[]).map((value) => (
            <label key={value} className={KIND_CHIP}>
              <input
                type="radio"
                name="note-kind"
                value={value}
                checked={kind === value}
                onChange={() => onKind(value)}
                className="sr-only"
              />
              {NOTE_KIND_LABELS[value]}
            </label>
          ))}
        </div>
      </fieldset>

      {/* 가져올 곳 탭(F-002 마크다운 · F-005 노션) */}
      <div role="tablist" aria-label="가져올 곳" className="flex border-b border-line-regular">
        {(Object.keys(SOURCE_LABELS) as Source[]).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            id={`${tabPanelId}-${value}`}
            aria-selected={source === value}
            aria-controls={tabPanelId}
            onClick={() => onSource(value)}
            className={source === value ? TAB_SELECTED : TAB_UNSELECTED}
          >
            {SOURCE_LABELS[value]}
          </button>
        ))}
      </div>

      <div id={tabPanelId} role="tabpanel" aria-labelledby={`${tabPanelId}-${source}`} className="flex flex-col gap-5">
        {markdownTab ? (
          <MarkdownPicker
            files={files}
            onFiles={onFiles}
            selectError={selectError}
            fileInputRef={drop.fileInputRef}
            isDragging={drop.isDragging}
          />
        ) : (
          <NotionPicker pageIds={pageIds} onPageIds={onPageIds} />
        )}
      </div>

      {/* 보내는 범위 안내(설계 원칙 6) */}
      <ul className="flex flex-col gap-1 text-body-4 text-text-sub">
        <li>
          {markdownTab
            ? "이미 올린 것과 같은 내용은 다시 저장하지 않고 ‘중복’으로 알려 드려요."
            : "이미 가져온 페이지 · 같은 내용은 다시 저장하지 않아요. 노션에서 고친 내용은 다시 가져오지 않아요."}
        </li>
        <li>가져온 기록은 내 계정에만 저장돼요. 지금 단계에서는 AI에 보내지 않아요.</li>
      </ul>

      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className={GHOST_BUTTON}>
          취소
        </button>
        <button type="button" onClick={onSubmit} disabled={count === 0 || selectError !== null} className={PRIMARY_BUTTON}>
          {count > 0 ? `${count}개 가져오기` : "가져오기"}
        </button>
      </div>
    </div>
  );
}

// 마크다운 탭: 파일 칸(끌어 놓기 · 파일 선택) · 고른 파일 목록 · 개수/용량 오류
function MarkdownPicker({
  files,
  onFiles,
  selectError,
  fileInputRef,
  isDragging,
}: {
  files: File[];
  onFiles: (files: File[]) => void;
  selectError: string | null;
  fileInputRef: RefObject<HTMLInputElement | null>;
  isDragging: boolean;
}) {
  return (
    <>
      {/* 파일 칸(Figma 25:360): 점선 line/input · bg/light. 끄는 동안 primary로 강조 */}
      <div
        className={`flex flex-col items-center justify-center gap-2 rounded-card border border-dashed p-8 text-center ${
          isDragging ? "border-primary-default bg-primary-soft" : "border-line-input bg-bg-light"
        }`}
      >
        <Icon name="upload" size={32} className="text-icon-sub" />
        <p className="text-body-1 font-medium text-text-main">마크다운 파일을 여기에 끌어 놓으세요</p>
        <p className="text-body-4 text-text-sub">
          .md · 파일당 {MAX_IMPORT_FILE_MB}MB · 한 번에 {MAX_IMPORT_FILES}개까지
        </p>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS}
          aria-label="올릴 마크다운 파일"
          tabIndex={-1}
          onChange={(event) => onFiles(event.target.files ? Array.from(event.target.files) : [])}
          data-dragging={isDragging ? "" : undefined}
          className="sr-only"
        />
        <button type="button" onClick={() => fileInputRef.current?.click()} className={SECONDARY_BUTTON_S}>
          파일 선택
        </button>
      </div>

      {files.length > 0 ? (
        <ul aria-label="고른 파일" className="flex max-h-60 flex-col gap-3 overflow-y-auto">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`} className="flex items-center gap-3">
              <Icon name="notebook" size={20} className="text-icon-sub" />
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="truncate text-body-2 font-medium text-text-main">{file.name}</span>
                <span className="text-body-4 text-text-sub">{formatSize(file.size)}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {selectError ? (
        <p role="alert" className="text-body-3 text-error-text">
          {selectError}
        </p>
      ) : null}
    </>
  );
}

function formatEdited(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.getMonth() + 1}.${String(date.getDate()).padStart(2, "0")} 수정`;
}

// 노션 탭: 연결된 노션에서 공유한 페이지 목록(최근 수정 순)을 골라 가져온다(F-005).
// 연결 안 됨 · 끊김(409) · 서버 설정 없음(503)이면 설정 화면으로 안내한다.
function NotionPicker({ pageIds, onPageIds }: { pageIds: string[]; onPageIds: (pageIds: string[]) => void }) {
  // 탭을 오가거나 창을 다시 볼 때마다 노션 검색을 다시 부르지 않게 1분은 그대로 쓴다(1차 리뷰 R2). 가져온 뒤에는 무효화로 새로 받는다
  const pages = useQuery({
    queryKey: NOTION_PAGES_KEY,
    queryFn: fetchNotionPages,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const atLimit = pageIds.length >= NOTION_MAX_IMPORT_PAGES;

  function toggle(id: string, checked: boolean) {
    if (checked) {
      if (!pageIds.includes(id) && !atLimit) onPageIds([...pageIds, id]);
    } else {
      onPageIds(pageIds.filter((value) => value !== id));
    }
  }

  if (pages.isPending) {
    return (
      <p role="status" className="text-body-3 text-text-sub">
        노션 페이지 목록을 불러오고 있어요…
      </p>
    );
  }
  if (pages.isError) {
    const error = pages.error;
    const toSettings = error instanceof ApiRequestError && (error.status === 409 || error.status === 503);
    return (
      <div className="flex flex-col items-start gap-3 rounded-card border border-line-regular bg-bg-light p-6">
        <p role="alert" className="text-body-2 font-medium text-text-main">
          {error instanceof ApiRequestError ? error.message : "노션 페이지 목록을 불러오지 못했어요."}
        </p>
        {error instanceof ApiRequestError && error.needsLogin ? (
          <Link href="/login" className={SECONDARY_BUTTON_S}>
            다시 로그인
          </Link>
        ) : toSettings ? (
          <Link href="/settings" className={SECONDARY_BUTTON_S}>
            설정에서 노션 연결
          </Link>
        ) : (
          <button type="button" onClick={() => void pages.refetch()} className={SECONDARY_BUTTON_S}>
            다시 불러오기
          </button>
        )}
      </div>
    );
  }
  if (pages.data.pages.length === 0) {
    return (
      <p className="rounded-card border border-line-regular bg-bg-light p-6 text-body-3 text-text-sub">
        가져올 수 있는 페이지가 없어요. 노션에서 페이지의 [연결] 메뉴로 디딤에 공유하거나, 설정에서 다시 연결하며 페이지를 골라 주세요.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-body-4 text-text-sub">
        {pageIds.length} / {NOTION_MAX_IMPORT_PAGES}개 고름 · 하위 페이지는 따로 골라 주세요
      </p>
      {pages.data.truncated ? (
        // 1차 리뷰 F: 노션이 더 있다고 하면 오래된 페이지가 목록에서 빠졌음을 알린다
        <p className="text-body-4 text-text-sub">
          최근 수정한 {NOTION_MAX_PAGE_LIST}개만 보여요. 오래된 페이지는 노션에서 한 번 고치면 목록 위로 올라와요.
        </p>
      ) : null}
      <ul aria-label="가져올 노션 페이지" className="flex max-h-72 flex-col overflow-y-auto">
        {pages.data.pages.map((page) => {
          const checked = pageIds.includes(page.id);
          const imported = page.importedNoteId !== null;
          const edited = formatEdited(page.lastEditedTime);
          return (
            <li key={page.id} className="border-b border-line-light last:border-b-0">
              <label
                className={`flex items-center gap-3 py-3 ${imported || (atLimit && !checked) ? "cursor-not-allowed" : "cursor-pointer"}`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={imported || (atLimit && !checked)}
                  onChange={(event) => toggle(page.id, event.target.checked)}
                  className={`size-4 shrink-0 accent-primary-default ${FOCUS_RING}`}
                />
                <Icon name="notebook" size={20} className="text-icon-sub" />
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className={`truncate text-body-2 font-medium ${imported ? "text-text-sub" : "text-text-main"}`}>
                    {page.title}
                  </span>
                  {edited ? <span className="text-body-4 text-text-sub">{edited}</span> : null}
                </span>
                {imported ? <span className="shrink-0 text-body-4 text-text-sub">이미 가져옴</span> : null}
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// 처리 중(Figma IMP_01_002 25:471). 요청 한 번에 읽기 · 나누기를 끝내 단계별 진행을 알 수 없어(Q-008)
// 진행 막대는 '모를 때' 모양(좌우로 흐름)으로 두고, Figma의 단계별 체크 · [닫고 계속 진행]은 그리지 않는다(D-019).
function ProcessingStep({ message }: { message: string }) {
  return (
    <div data-screen-id="IMP_01_002" className="flex flex-col gap-5">
      <StepHeader title="노트를 정리하고 있어요" step={2} />
      <p role="status" className="text-body-2 text-text-sub">
        {message} 창을 닫지 말고 잠시만 기다려 주세요.
      </p>
      <div
        role="progressbar"
        aria-label="가져오는 중"
        aria-valuetext="진행 중"
        className="h-1 overflow-hidden rounded-xs bg-line-light"
      >
        <div className="h-full w-2/5 animate-indeterminate rounded-xs bg-primary-default motion-reduce:w-full motion-reduce:animate-none" />
      </div>
    </div>
  );
}

function FailedList({ failed, label = "읽지 못한 파일" }: { failed: ImportResponse["failed"]; label?: string }) {
  return (
    <ul aria-label={label} className="flex flex-col gap-3">
      {failed.map((item, index) => (
        <li key={`${item.filename}-${index}`} className="flex items-start gap-3">
          <Icon name="error" size={20} className="text-error-text" />
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="text-body-2 font-semibold wrap-break-word text-text-main">{item.filename}</span>
            <span className="text-body-3 text-text-sub">{item.reason}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

// 결과 요약(Figma IMP_01_003 25:555): 숫자 칸 + 건너뛴 파일 + [기록 · 복습 보기] · [확인].
// Figma의 '개념 · 퀴즈 문제 · 경험 카드 후보'는 가져올 때 만들지 않아(문제는 노트 상세에서 만든다) 실제로 센 노트 · 조각을 보여 준다.
function ResultSummary({
  data,
  notion,
  onClose,
}: {
  data: ImportResponse;
  notion: NotionExtra | null;
  onClose: () => void;
}) {
  const { summary } = data;
  const tiles: [string, number][] = [
    ["노트", summary.notes],
    ["조각", summary.chunks],
  ];
  return (
    <div data-screen-id="IMP_01_003" className="flex flex-col gap-5">
      <StepHeader title={`노트 ${summary.notes}개를 정리했어요`} step={3} />
      <dl className="grid grid-cols-2 gap-4">
        {tiles.map(([label, count]) => (
          <div
            key={label}
            className="flex flex-col-reverse gap-1 rounded-card border border-line-regular bg-bg-light p-4"
          >
            <dt className="text-body-3 text-text-sub">{label}</dt>
            <dd className="text-title-1 font-semibold text-text-main">{count}</dd>
          </div>
        ))}
      </dl>

      {notion?.connectionBroken ? (
        <p role="alert" className="text-body-3 font-medium text-error-text">
          가져오는 중에 노션 연결이 끊겼어요. 설정에서 다시 연결한 뒤 남은 페이지를 가져와 주세요.
        </p>
      ) : null}
      {notion && notion.skippedBlocks > 0 ? (
        <p className="text-body-4 text-text-sub">
          이미지 · 파일 · 임베드 · 하위 페이지 같은 블록 {notion.skippedBlocks}개는 글로 옮길 수 없어 건너뛰었어요.
        </p>
      ) : null}
      {data.duplicates.length > 0 ? (
        <div className="flex flex-col gap-1">
          <p className="text-body-4 text-text-sub">
            건너뛴 {notion ? "페이지" : "파일"} {data.duplicates.length}개(이미 {notion ? "가져온" : "올린"} 노트와 같음)
          </p>
          <ul
            aria-label={notion ? "중복이라 저장하지 않은 페이지" : "중복이라 저장하지 않은 파일"}
            className="flex flex-col gap-1 text-body-4 text-text-sub"
          >
            {data.duplicates.map((item, index) => (
              <li key={`${item.filename}-${index}`}>
                {item.filename} — 이미 {notion ? "가져온" : "올린"} &lsquo;{item.existing_title}&rsquo;과 같아요
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {data.failed.length > 0 ? (
        <FailedList failed={data.failed} label={notion ? "읽지 못한 페이지" : "읽지 못한 파일"} />
      ) : null}

      <p className="text-body-3 text-text-sub">복습 문제는 노트 상세에서 [문제 만들기]로 만들어요.</p>
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/records" onClick={onClose} className={TEXT_BUTTON}>
          기록 · 복습 보기
        </Link>
        <div className="flex-1" />
        <button type="button" onClick={onClose} className={PRIMARY_BUTTON}>
          확인
        </button>
      </div>
    </div>
  );
}
