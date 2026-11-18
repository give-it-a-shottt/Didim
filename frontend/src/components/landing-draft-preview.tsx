import { Icon } from "@/components/icon";
import { DRAFT_POSTING, DRAFT_PROGRESS, DRAFT_QUESTION, DRAFT_QUESTION_LABEL, DRAFT_SENTENCES, type DraftSentence } from "@/lib/landing";
import { BADGE_LINE, CHIP, CHIP_WARNING, PRIMARY_BUTTON, SECONDARY_BUTTON_S } from "@/lib/ui-classes";

// 랜딩 첫 화면의 '실제 화면'(F-011 완료 기준 1, Figma 29:1478 '자소서 에디터 가운데'). 샘플 계정의 실제 초안 · 근거 검사 결과를
// 자소서 화면(draft-editor.tsx)과 같은 칩 · 밑줄 모양으로 그린 보기 전용 카드다 — 버튼처럼 보이는 것도 누를 수 없어서
// 화면 읽기 프로그램에는 감추고(aria-hidden), 카드 전체를 이름 붙은 그림(figure)으로 읽힌다.
export function LandingDraftPreview() {
  const flagged = DRAFT_SENTENCES.filter((sentence) => sentence.kind !== "ok").length;
  return (
    <figure
      aria-label={`디딤 자소서 화면 예시: 문장 ${DRAFT_SENTENCES.length}개 중 ${flagged}개에 경고가 붙은 샘플 초안`}
      className="flex flex-col gap-3"
    >
      <div className="flex flex-col gap-5 rounded-card border border-line-regular bg-bg-default p-4 lg:p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <p className="text-title-2 font-semibold text-text-main">{DRAFT_QUESTION_LABEL}</p>
            <p className="text-body-4 text-text-sub">{DRAFT_PROGRESS}</p>
          </div>
          <span aria-hidden="true" className={`pointer-events-none ${PRIMARY_BUTTON}`}>
            이 문항 완료
          </span>
        </div>
        <p className="text-body-2 text-text-sub">{DRAFT_QUESTION}</p>
        <p className="text-title-4 leading-8 font-normal text-text-main">
          {DRAFT_SENTENCES.map((sentence) => (
            <PreviewSentence key={sentence.text} sentence={sentence} />
          ))}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <span aria-hidden="true" className={`pointer-events-none ${SECONDARY_BUTTON_S}`}>
            근거 다시 검사
          </span>
          <span className="text-body-4 text-text-sub">문장을 고치면 자동으로 다시 검사해요</span>
        </div>
      </div>
      <figcaption className="flex flex-wrap items-center gap-2 text-body-4 text-text-sub-weak">
        <span className={BADGE_LINE}>샘플</span>
        {DRAFT_POSTING} 2번 문항의 실제 AI 초안과 근거 검사 결과예요.
      </figcaption>
    </figure>
  );
}

/** 문장 하나 — 근거 칩 · '확인 필요' · '근거 없음' 표시는 자소서 화면과 같은 규칙(근거 없음 = 실선, 확인 필요 = 점선). */
function PreviewSentence({ sentence }: { sentence: DraftSentence }) {
  return (
    <>
      <span
        className={
          sentence.kind === "none"
            ? "underline decoration-warning-text decoration-2 underline-offset-4"
            : sentence.kind === "check"
              ? "underline decoration-warning-text decoration-dotted decoration-2 underline-offset-4"
              : undefined
        }
      >
        {sentence.text}
      </span>
      {sentence.kind === "none" ? (
        <span className="ml-1 inline-flex items-center gap-1 align-middle">
          <Icon name="warning" size={16} className="text-warning-text" />
          <span className={CHIP_WARNING}>근거 없음</span>
        </span>
      ) : (
        <>
          <span className={CHIP}>{sentence.card}</span>
          {sentence.kind === "check" ? (
            <span className={`${CHIP_WARNING} ml-1`}>확인 필요 · 카드에 없는 낱말: {sentence.unknownWords}</span>
          ) : null}
        </>
      )}{" "}
    </>
  );
}
