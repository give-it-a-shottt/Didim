"use client";

// APL_01_002 공고 추가 모달(Figma 27:1313). [분석하기] → 공고를 저장하고 공고 분석 탭(APL_02_002)으로 가서 분석을 시작한다.
// Figma와 다르게 둔 것(설계 의도 F-007, 사용자 확인 2026-11-12):
// - 공고 본문은 필수(붙여 넣기). URL은 링크로 저장만 하고 서버가 읽지 않는다(D-002) — "1 / 2" 단계 표시는 두지 않음.
// - 회사 이름 칸을 더함(목록 · 머리에 '회사 · 직무'로 보여 줌). 마감일은 선택(없으면 목록 맨 아래).
// 입력 상태는 이 모달만 쓰므로 useState(D-012), 저장은 서버 수정이라 useMutation.

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { RequestErrorText } from "@/components/request-error";
import {
  APPLICATION_COMPANY_MAX_CHARS,
  APPLICATION_MAX_QUESTIONS,
  APPLICATION_QUESTION_CHAR_LIMIT_MAX,
  APPLICATION_QUESTION_MAX_CHARS,
  APPLICATION_ROLE_MAX_CHARS,
  APPLICATION_URL_MAX_CHARS,
  POSTING_TEXT_MAX_CHARS,
  applicationHref,
  createApplication,
} from "@/lib/applications";
import { FOCUS_RING, GHOST_BUTTON, PRIMARY_BUTTON, TEXT_BUTTON } from "@/lib/ui-classes";

const INPUT = `h-12 w-full rounded-input border border-line-input bg-bg-default px-4 text-title-4 text-text-main placeholder:text-text-sub-weak hover:border-line-input-hover ${FOCUS_RING}`;
const LABEL = "text-body-2 font-semibold text-text-main";
const HELP = "text-body-3 text-text-sub-weak";

export function AddApplicationButton({ variant = "primary" }: { variant?: "primary" | "empty" }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [openCount, setOpenCount] = useState(0); // 열 때마다 입력을 새로 시작하는 key
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (isOpen && !dialog.open) dialog.showModal();
    if (!isOpen && dialog.open) dialog.close();
  }, [isOpen]);

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpenCount((count) => count + 1);
          setIsOpen(true);
        }}
        className={PRIMARY_BUTTON}
      >
        {variant === "primary" ? <Icon name="plus" size={20} /> : null}
        공고 추가
      </button>
      <dialog
        ref={dialogRef}
        aria-labelledby="add-application-title"
        onCancel={(event) => {
          if (isBusy) event.preventDefault(); // 저장 중에는 Esc로 닫지 않는다
        }}
        onClose={() => {
          if (isBusy) {
            dialogRef.current?.showModal();
            return;
          }
          setIsOpen(false);
        }}
        // Figma 모달: 너비 640, 위 28 · 옆 24 · 아래 24, 칸 사이 20
        className="m-auto w-full max-w-160 rounded-modal bg-bg-elevated px-6 pt-7 pb-6 text-text-main backdrop:bg-bg-dim"
      >
        {isOpen ? (
          <ApplicationForm key={openCount} onClose={() => setIsOpen(false)} onBusyChange={setIsBusy} />
        ) : null}
      </dialog>
    </>
  );
}

type QuestionDraft = { key: number; text: string; charLimit: string };

function ApplicationForm({ onClose, onBusyChange }: { onClose: () => void; onBusyChange: (busy: boolean) => void }) {
  const router = useRouter();
  const ids = useId();
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [deadline, setDeadline] = useState("");
  const [url, setUrl] = useState("");
  const [postingText, setPostingText] = useState("");
  const [questions, setQuestions] = useState<QuestionDraft[]>([{ key: 0, text: "", charLimit: "" }]);
  const nextKey = useRef(1);

  const save = useMutation({
    mutationFn: () =>
      createApplication({
        company,
        role,
        deadline: deadline || null,
        url: url.trim() || null,
        postingText,
        questions: questions
          .filter((item) => item.text.trim())
          .map((item) => ({ text: item.text, charLimit: item.charLimit ? Number(item.charLimit) : null })),
      }),
    onMutate: () => onBusyChange(true),
    onSettled: () => onBusyChange(false),
    onSuccess: (created) => {
      onClose();
      // 분석 탭에서 ① 역량 뽑기 → ② 매칭을 이어서 시작한다(analyze=1). 새로 고쳐도 다시 시작하지 않게 그쪽에서 주소를 지운다.
      router.push(`${applicationHref(created.id)}?analyze=1`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!save.isPending) save.mutate();
  }

  function updateQuestion(key: number, change: Partial<QuestionDraft>) {
    setQuestions((items) => items.map((item) => (item.key === key ? { ...item, ...change } : item)));
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <h2 id="add-application-title" className="text-title-2 font-semibold">
        공고 추가
      </h2>

      <div className="flex flex-col gap-2 sm:flex-row sm:gap-4">
        <label className="flex flex-1 flex-col gap-2">
          <span className={LABEL}>
            회사 <span className="text-error-text">*</span>
          </span>
          <input
            required
            value={company}
            onChange={(event) => setCompany(event.target.value)}
            maxLength={APPLICATION_COMPANY_MAX_CHARS}
            placeholder="누리랩"
            className={INPUT}
          />
        </label>
        <label className="flex flex-1 flex-col gap-2">
          <span className={LABEL}>
            직무 <span className="text-error-text">*</span>
          </span>
          <input
            required
            value={role}
            onChange={(event) => setRole(event.target.value)}
            maxLength={APPLICATION_ROLE_MAX_CHARS}
            placeholder="풀스택 개발자 (신입)"
            className={INPUT}
          />
        </label>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={`${ids}-posting`} className={LABEL}>
          공고 본문 <span className="text-error-text">*</span>
        </label>
        <textarea
          id={`${ids}-posting`}
          required
          value={postingText}
          onChange={(event) => setPostingText(event.target.value)}
          maxLength={POSTING_TEXT_MAX_CHARS}
          aria-describedby={`${ids}-posting-help ${ids}-posting-tip`}
          placeholder="자격 요건 · 우대 사항이 들어간 부분을 붙여 넣으면 더 정확해요"
          className={`h-30 w-full resize-y rounded-input border border-line-input bg-bg-default p-3 text-body-1 text-text-main placeholder:text-text-sub-weak hover:border-line-input-hover ${FOCUS_RING}`}
        />
        <p id={`${ids}-posting-help`} className={HELP}>
          {/* 설계 원칙 6: AI에 무엇을 보내는지 알린다 */}
          [분석하기]를 누르면 이 본문을 AI에 보내 요구 역량을 뽑아요. {postingText.length.toLocaleString()} /{" "}
          {POSTING_TEXT_MAX_CHARS.toLocaleString()}자
        </p>
        <p id={`${ids}-posting-tip`} className={HELP}>
          {/* 공고 사이트가 복사를 막거나 본문이 이미지일 때. URL로 자동 가져오기는 하지 않는다(D-002) */}
          복사가 막혔거나 이미지로 된 공고라면, Windows 캡처 도구(Win + Shift + S)로 찍은 뒤 [텍스트 작업]으로
          글자를 뽑아 붙여 넣으세요.
        </p>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:gap-4">
        <div className="flex flex-1 flex-col gap-2">
          <label htmlFor={`${ids}-url`} className={LABEL}>
            공고 URL
          </label>
          <input
            id={`${ids}-url`}
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            maxLength={APPLICATION_URL_MAX_CHARS}
            aria-describedby={`${ids}-url-help`}
            placeholder="https://"
            className={INPUT}
          />
          <p id={`${ids}-url-help`} className={HELP}>
            링크로만 저장해요. 사이트를 자동으로 긁어 오지 않아요.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:w-48">
          <label htmlFor={`${ids}-deadline`} className={LABEL}>
            마감일
          </label>
          <input
            id={`${ids}-deadline`}
            type="date"
            value={deadline}
            onChange={(event) => setDeadline(event.target.value)}
            aria-describedby={`${ids}-deadline-help`}
            className={INPUT}
          />
          <p id={`${ids}-deadline-help`} className={HELP}>
            D-day 순으로 정렬해요
          </p>
        </div>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className={`${LABEL} mb-2`}>자소서 문항</legend>
        {questions.map((item, index) => (
          <div key={item.key} className="flex items-center gap-2">
            <span className="w-5 shrink-0 text-body-2 text-text-main">{index + 1}.</span>
            <input
              value={item.text}
              onChange={(event) => updateQuestion(item.key, { text: event.target.value })}
              maxLength={APPLICATION_QUESTION_MAX_CHARS}
              aria-label={`${index + 1}번 문항`}
              placeholder="지원 동기"
              className={`h-10 min-w-0 flex-1 rounded-input border border-line-input bg-bg-default px-3 text-body-1 text-text-main placeholder:text-text-sub-weak hover:border-line-input-hover ${FOCUS_RING}`}
            />
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={APPLICATION_QUESTION_CHAR_LIMIT_MAX}
              value={item.charLimit}
              onChange={(event) => updateQuestion(item.key, { charLimit: event.target.value })}
              aria-label={`${index + 1}번 문항 글자 수`}
              placeholder="700"
              className={`h-10 w-20 rounded-input border border-line-input bg-bg-default px-3 text-body-1 text-text-main placeholder:text-text-sub-weak hover:border-line-input-hover ${FOCUS_RING}`}
            />
            <span className="text-body-3 text-text-sub">자</span>
          </div>
        ))}
        {questions.length < APPLICATION_MAX_QUESTIONS ? (
          <button
            type="button"
            onClick={() => {
              const key = nextKey.current++;
              setQuestions((items) => [...items, { key, text: "", charLimit: "" }]);
            }}
            className={`${TEXT_BUTTON} self-start`}
          >
            문항 추가
          </button>
        ) : null}
      </fieldset>

      {save.error ? <RequestErrorText error={save.error} /> : null}

      <div className="flex items-center justify-end gap-2">
        <button type="button" onClick={onClose} disabled={save.isPending} className={GHOST_BUTTON}>
          취소
        </button>
        <button type="submit" disabled={save.isPending} className={PRIMARY_BUTTON}>
          {save.isPending ? "저장하는 중…" : "분석하기"}
        </button>
      </div>
    </form>
  );
}
