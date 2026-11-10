"use client";

// 기록 추가 모달(IMP_01_001 올리기 → 002 처리 중 → 003 결과 요약 · 900 오류). URL 없이 사이드바 버튼으로 연다.
// 1주차(F-002)는 읽기 · 나누기까지. 요청 한 번에 처리하므로 002는 요청 동안의 진행 표시만 한다(Q-008).
// 상태는 이 모달 안에서만 쓰여 useState로 둔다(D-012, architecture.md 상태 관리 지도).
//
// 나눈 방식
// - AddRecordButton: 버튼 + <dialog> 열고 닫기만 맡는다.
// - ImportFlow: 단계(올리기 → 처리 중 → 결과 · 오류)와 업로드. 열 때마다 새로 그려 상태가 처음으로 돌아간다.
// - SelectStep · ResultSummary · FailedList: 각 화면.

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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

type Step =
  | { name: "select" }
  | { name: "processing" }
  | { name: "result"; data: ImportResponse }
  | { name: "error"; message: string; needsLogin: boolean; failed: ImportResponse["failed"] };

const PRIMARY_BUTTON =
  "inline-flex h-10 items-center justify-center rounded-button bg-primary-default px-4 text-body-2 font-medium text-text-on-primary hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-default disabled:cursor-not-allowed disabled:bg-bg-pressed disabled:text-text-disabled";
const SECONDARY_BUTTON =
  "inline-flex h-10 items-center justify-center rounded-button border border-line-regular bg-bg-default px-4 text-body-2 font-medium text-text-main hover:bg-bg-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-default";

export function AddRecordButton() {
  const router = useRouter();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
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
        className="rounded-button border border-line-regular bg-bg-default px-3 py-2 text-left text-body-2 font-medium text-text-main hover:bg-bg-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-default"
      >
        + 기록 추가
      </button>

      <dialog
        ref={dialogRef}
        aria-labelledby={titleId}
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
        className="m-auto w-full max-w-lg rounded-modal bg-bg-default p-6 text-text-main"
      >
        <h2 id={titleId} className="text-title-2 font-semibold">
          기록 추가
        </h2>
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
  const [step, setStep] = useState<Step>({ name: "select" });
  const [files, setFiles] = useState<File[]>([]);
  const [kind, setKind] = useState<NoteKind>("study");

  async function submit() {
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
    const { summary, failed } = outcome.data;
    if (summary.notes > 0) onSaved();
    if (summary.notes === 0 && summary.duplicates === 0) {
      // 하나도 읽지 못함 → 오류 화면(IMP_01_900)
      setStep({ name: "error", message: "노트를 읽지 못했어요.", needsLogin: false, failed });
      return;
    }
    setStep({ name: "result", data: outcome.data });
  }

  switch (step.name) {
    case "select":
      return (
        <SelectStep files={files} kind={kind} onFiles={setFiles} onKind={setKind} onCancel={onClose} onSubmit={submit} />
      );
    case "processing":
      return (
        <div data-screen-id="IMP_01_002" role="status" className="mt-6 flex flex-col gap-2 text-body-2 text-text-sub">
          <p>기록을 읽고 조각으로 나누고 있어요…</p>
          <p className="text-body-3">창을 닫지 말고 잠시만 기다려 주세요.</p>
        </div>
      );
    case "result":
      return <ResultSummary data={step.data} onClose={onClose} />;
    case "error":
      return (
        <div data-screen-id="IMP_01_900" className="mt-4 flex flex-col gap-3">
          <p role="alert" className="text-body-2 font-medium text-error-text">
            {step.message}
          </p>
          {step.failed.length > 0 ? <FailedList failed={step.failed} /> : null}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={SECONDARY_BUTTON}>
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

function SelectStep({
  files,
  kind,
  onFiles,
  onKind,
  onCancel,
  onSubmit,
}: {
  files: File[];
  kind: NoteKind;
  onFiles: (files: File[]) => void;
  onKind: (kind: NoteKind) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const selectError = checkSelection(files);

  return (
    <div data-screen-id="IMP_01_001" className="mt-4 flex flex-col gap-4">
      <div role="tablist" aria-label="가져올 곳" className="flex gap-2">
        <button
          type="button"
          role="tab"
          aria-selected="true"
          className="rounded-button bg-primary-soft px-3 py-1.5 text-body-2 font-medium text-primary-text"
        >
          마크다운
        </button>
        <button
          type="button"
          role="tab"
          aria-selected="false"
          aria-disabled="true"
          disabled
          className="rounded-button px-3 py-1.5 text-body-2 text-text-disabled"
        >
          노션 (4주차)
        </button>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-body-2 font-medium">기록 종류</legend>
        <div className="flex gap-4">
          {(Object.keys(NOTE_KIND_LABELS) as NoteKind[]).map((value) => (
            <label key={value} className="flex items-center gap-2 text-body-2">
              <input type="radio" name="note-kind" value={value} checked={kind === value} onChange={() => onKind(value)} />
              {NOTE_KIND_LABELS[value]}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="flex flex-col gap-2 text-body-2 font-medium">
        마크다운 파일
        <input
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS}
          onChange={(event) => onFiles(event.target.files ? Array.from(event.target.files) : [])}
          className="rounded-input border border-line-input p-2 text-body-3 font-normal"
        />
      </label>
      <ul className="flex flex-col gap-1 text-body-3 text-text-sub">
        <li>
          .md 파일, 한 번에 {MAX_IMPORT_FILES}개 · 파일당 {MAX_IMPORT_FILE_MB}MB까지
        </li>
        <li>이미 올린 것과 같은 내용은 다시 저장하지 않고 &lsquo;중복&rsquo;으로 알려 드려요.</li>
        <li>올린 기록은 내 계정에만 저장돼요. 지금 단계에서는 AI에 보내지 않아요.</li>
      </ul>
      {selectError ? (
        <p role="alert" className="text-body-3 text-error-text">
          {selectError}
        </p>
      ) : null}

      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className={SECONDARY_BUTTON}>
          취소
        </button>
        <button
          type="button"
          onClick={onSubmit}
          disabled={files.length === 0 || selectError !== null}
          className={PRIMARY_BUTTON}
        >
          가져오기{files.length > 0 ? ` (${files.length}개)` : ""}
        </button>
      </div>
    </div>
  );
}

function FailedList({ failed }: { failed: ImportResponse["failed"] }) {
  return (
    <ul aria-label="읽지 못한 파일" className="flex flex-col gap-1 text-body-3">
      {failed.map((item, index) => (
        <li key={`${item.filename}-${index}`}>
          <span className="font-medium">{item.filename}</span>
          <span className="text-text-sub"> — {item.reason}</span>
        </li>
      ))}
    </ul>
  );
}

function ResultSummary({ data, onClose }: { data: ImportResponse; onClose: () => void }) {
  const { summary } = data;
  return (
    <div data-screen-id="IMP_01_003" className="mt-4 flex flex-col gap-4">
      <dl className="grid grid-cols-4 gap-2 text-center">
        {[
          ["노트", summary.notes],
          ["조각", summary.chunks],
          ["중복", summary.duplicates],
          ["실패", summary.failed],
        ].map(([label, count]) => (
          <div key={label} className="rounded-card bg-bg-light p-3">
            <dt className="text-body-3 text-text-sub">{label}</dt>
            <dd className="text-title-3 font-semibold">{count}</dd>
          </div>
        ))}
      </dl>

      {data.duplicates.length > 0 ? (
        <ul aria-label="중복이라 저장하지 않은 파일" className="flex flex-col gap-1 text-body-3">
          {data.duplicates.map((item, index) => (
            <li key={`${item.filename}-${index}`}>
              <span className="font-medium">{item.filename}</span>
              <span className="text-text-sub"> — 이미 올린 &lsquo;{item.existing_title}&rsquo;과 같아요</span>
            </li>
          ))}
        </ul>
      ) : null}
      {data.failed.length > 0 ? <FailedList failed={data.failed} /> : null}

      <p className="text-body-3 text-text-sub">복습 문제와 경험 카드 후보는 다음 단계(3 · 4주차)에서 이 기록으로 만들어요.</p>
      <div className="flex justify-end gap-2">
        <Link href="/records" onClick={onClose} className={SECONDARY_BUTTON}>
          기록 · 복습 보기
        </Link>
        <button type="button" onClick={onClose} className={PRIMARY_BUTTON}>
          확인
        </button>
      </div>
    </div>
  );
}
