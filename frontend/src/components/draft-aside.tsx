"use client";

// APL_02_003 오른쪽 칸(Figma 18:258 '검사 · 근거', 너비 304): 요약("문장 9개 중 7개에 근거가 있어요") +
// 고른 문장의 근거(Didim/검사 항목 — 카드 칸 글은 내 기록 원문이라 명조) + 근거 없는 문장마다 [카드 연결] · [직접 고치기] · [지우기].
// 근거 없음 설명은 AI 글이 아니라 근거 상태(서버가 다시 검사한 값)마다 정해 둔 문구다.

import { Icon } from "@/components/icon";
import { SLOT_LABELS } from "@/lib/cards";
import type { Draft, DraftSentence, EvidenceStatus } from "@/lib/drafts";
import { GHOST_BUTTON_S, SECONDARY_BUTTON_S, SECTION_TITLE, TEXT_BUTTON } from "@/lib/ui-classes";

const ITEM = "flex flex-col gap-2 rounded-card border bg-bg-default p-3";

const UNSUPPORTED_TITLE: Record<Exclude<EvidenceStatus, "ok">, string> = {
  none: "근거 없음",
  card_gone: "근거 카드가 지워졌어요",
  changed: "카드 글이 바뀌었어요",
};

function unsupportedHelp(sentence: DraftSentence): string {
  if (sentence.evidenceStatus === "card_gone") return "근거로 쓴 카드를 지웠어요. 다른 카드를 연결하거나, 문장을 고치거나 지워 주세요.";
  if (sentence.evidenceStatus === "changed") {
    return "근거로 쓴 카드 칸의 글이 바뀌어 인용을 찾을 수 없어요. 카드를 다시 연결하거나 문장을 고쳐 주세요.";
  }
  if (sentence.origin === "user") return "내가 넣은 문장이에요. 기록에 있는 내용이면 카드를 연결해 근거를 붙여 주세요.";
  return "AI가 카드에서 근거를 찾지 못한 문장이에요. 기록에 있는 내용이면 카드를 연결하고, 없으면 고치거나 지우는 걸 권해요.";
}

export function DraftAside({
  draft,
  selectedSentenceId,
  onSelectSentence,
  busy,
  onEdit,
  onInsertAfter,
  onRemove,
  onLink,
  onUnlink,
}: {
  draft: Draft | null;
  selectedSentenceId: number | null;
  onSelectSentence: (sentenceId: number) => void;
  busy: boolean;
  onEdit: (sentenceId: number) => void;
  onInsertAfter: (sentenceId: number) => void;
  onRemove: (sentenceId: number) => void;
  onLink: (sentenceId: number) => void;
  onUnlink: (sentenceId: number) => void;
}) {
  if (draft === null) {
    return (
      <aside aria-labelledby="draft-aside-title" className="flex w-full flex-col gap-1 lg:w-76 lg:shrink-0">
        <h3 id="draft-aside-title" className={SECTION_TITLE}>
          검사 · 근거
        </h3>
        <p className="text-body-3 text-text-sub">초안을 쓰면 문장마다 근거가 내 카드에 그대로 있는지 확인해요.</p>
      </aside>
    );
  }

  const numbered = draft.sentences.map((sentence, index) => ({ sentence, number: index + 1 }));
  const selected = numbered.find((item) => item.sentence.id === selectedSentenceId) ?? null;
  const unsupported = numbered.filter((item) => item.sentence.evidenceStatus !== "ok");
  const supportedCount = draft.sentenceCount - draft.unsupportedCount;

  return (
    <aside aria-labelledby="draft-aside-title" className="flex w-full flex-col gap-5 lg:w-76 lg:shrink-0">
      <div className="flex flex-col gap-1">
        <h3 id="draft-aside-title" className={SECTION_TITLE}>
          검사 · 근거
        </h3>
        {/* 요약은 제목(16)보다 작게 14 · 한 단계 약한 글자색(사용자 화면 확인 2026-11-14) */}
        <p className="text-body-2 font-medium text-text-sub">
          문장 {draft.sentenceCount}개 중 {supportedCount}개에 근거가 있어요
        </p>
        {draft.unsupportedCount > 0 ? (
          <p className="text-body-3 text-warning-text">근거 없는 문장 {draft.unsupportedCount}개는 제출 전에 확인해 주세요.</p>
        ) : null}
      </div>

      {selected && selected.sentence.evidenceStatus === "ok" ? (
        <SelectedEvidence
          sentence={selected.sentence}
          number={selected.number}
          busy={busy}
          onEdit={() => onEdit(selected.sentence.id)}
          onInsertAfter={() => onInsertAfter(selected.sentence.id)}
          onRemove={() => onRemove(selected.sentence.id)}
          onUnlink={() => onUnlink(selected.sentence.id)}
        />
      ) : null}

      {unsupported.length > 0 ? (
        <ul className="flex flex-col gap-3" aria-label="근거 없는 문장">
          {unsupported.map(({ sentence, number }) => (
            <li key={sentence.id}>
              <UnsupportedItem
                sentence={sentence}
                number={number}
                selected={sentence.id === selectedSentenceId}
                busy={busy}
                onSelect={() => onSelectSentence(sentence.id)}
                onLink={() => onLink(sentence.id)}
                onEdit={() => onEdit(sentence.id)}
                onInsertAfter={() => onInsertAfter(sentence.id)}
                onRemove={() => onRemove(sentence.id)}
              />
            </li>
          ))}
        </ul>
      ) : null}

      {selected === null ? <p className="text-body-3 text-text-sub-weak">문장을 누르면 그 문장의 근거를 여기서 볼 수 있어요.</p> : null}
    </aside>
  );
}

/** 고른 문장의 근거(Figma 18:410): 성공 아이콘 + "선택한 문장 3 · 카드 제목", 아래 카드 칸 글(명조, 왼쪽 2px 줄) + 출처. */
function SelectedEvidence({
  sentence,
  number,
  busy,
  onEdit,
  onInsertAfter,
  onRemove,
  onUnlink,
}: {
  sentence: DraftSentence;
  number: number;
  busy: boolean;
  onEdit: () => void;
  onInsertAfter: () => void;
  onRemove: () => void;
  onUnlink: () => void;
}) {
  const evidence = sentence.evidence;
  if (evidence === null) return null;
  const source = [
    evidence.noteTitle ? `노트 · ${evidence.noteTitle}` : null,
    `${SLOT_LABELS[evidence.slot]} 칸 ${evidence.quoteSource === "quote" ? "원문 인용" : "내 답"}`,
    evidence.addedBy === "user" ? "내가 연결함" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <section aria-label={`선택한 문장 ${number}의 근거`} className={`${ITEM} border-line-regular`}>
      <p className="flex items-center gap-1.5 text-body-3 font-semibold text-text-main">
        <Icon name="success" size={16} className="text-success-base" />
        선택한 문장 {number} · {evidence.cardTitle ?? "카드"}
      </p>
      <blockquote className="flex flex-col gap-2 border-l-2 border-line-strong px-3 text-text-sub">
        <p className="font-serif text-quote whitespace-pre-wrap">「{evidence.quote}」</p>
        <footer className="text-body-4">{source}</footer>
      </blockquote>
      {sentence.origin === "edited" && sentence.originalText ? (
        <p className="text-body-4 text-text-sub-weak">내가 고침 · 원래 문장: {sentence.originalText}</p>
      ) : null}
      {/* 글자 버튼 사이에 짧은 세로 구분선(글자 높이보다 짧게 — 사용자 화면 확인 2026-11-14).
          구분선은 뒤 버튼과 한 덩어리라 줄이 바뀌면 같이 내려가고, 줄 맨 앞에 온 구분선은 안쪽 줄을 왼쪽으로 밀어(-ml-2.75 =
          구분선 1px + 간격 10px) 바깥 칸(overflow-hidden) 밖으로 가린다 — 줄 끝 · 줄 앞에 구분선이 혼자 남지 않게.
          바깥 -mx-1 px-1 · -my-1 py-1은 버튼 포커스 링이 잘리지 않게 둔 여백 */}
      <div className="-mx-1 -my-1 overflow-hidden px-1 py-1">
        <div className="-ml-2.75 flex flex-wrap items-center gap-y-1">
          {[
            { label: "직접 고치기", onClick: onEdit },
            { label: "뒤에 문장 넣기", onClick: onInsertAfter },
            { label: "근거 떼기", onClick: onUnlink },
            { label: "지우기", onClick: onRemove },
          ].map((action) => (
            <span key={action.label} className="flex items-center pr-2.5">
              <span aria-hidden="true" className="mr-2.5 h-3 w-px shrink-0 bg-line-strong" />
              <button type="button" onClick={action.onClick} disabled={busy} className={TEXT_BUTTON}>
                {action.label}
              </button>
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

/** 근거 없는 문장(Figma 18:380): 경고 아이콘 + "문장 4 · 근거 없음", 설명, [카드 연결] · [직접 고치기] · [지우기]. */
function UnsupportedItem({
  sentence,
  number,
  selected,
  busy,
  onSelect,
  onLink,
  onEdit,
  onInsertAfter,
  onRemove,
}: {
  sentence: DraftSentence;
  number: number;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onLink: () => void;
  onEdit: () => void;
  onInsertAfter: () => void;
  onRemove: () => void;
}) {
  const status = sentence.evidenceStatus as Exclude<EvidenceStatus, "ok">;
  return (
    <section
      aria-label={`문장 ${number} · ${UNSUPPORTED_TITLE[status]}`}
      className={`${ITEM} border-warning-text ${selected ? "bg-warning-bg" : ""}`}
    >
      <button type="button" onClick={onSelect} className={`${TEXT_BUTTON} self-start text-warning-text`}>
        <Icon name="warning" size={16} />
        <span className="font-semibold">
          문장 {number} · {UNSUPPORTED_TITLE[status]}
        </span>
      </button>
      <p className="text-body-3 text-text-sub">{unsupportedHelp(sentence)}</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={onLink} disabled={busy} className={SECONDARY_BUTTON_S}>
          카드 연결
        </button>
        <button type="button" onClick={onEdit} disabled={busy} className={GHOST_BUTTON_S}>
          직접 고치기
        </button>
        <button type="button" onClick={onRemove} disabled={busy} className={GHOST_BUTTON_S}>
          지우기
        </button>
        <button type="button" onClick={onInsertAfter} disabled={busy} className={GHOST_BUTTON_S}>
          뒤에 문장 넣기
        </button>
      </div>
    </section>
  );
}
