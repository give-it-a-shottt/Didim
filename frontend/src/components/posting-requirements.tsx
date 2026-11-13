// APL_02_002 왼쪽 표: 요구 역량 ↔ 내 카드(근거 칩) ↔ 상태. 줄이나 칩을 누르면 오른쪽 '선택한 역량의 근거'가 바뀐다.
// Figma와 다르게 둔 것: '근거 1개뿐' 상태(근거 수 기준이 정해지지 않음 — 근거 있음 · 없음 · 매칭 전만),
// '카드 만들기' 버튼 → [기록에서 찾기](설계 의도: 근거 없는 역량은 기록 검색 → 노트의 [카드 후보 찾기], 빈 카드 직접 만들기 없음).

import { Icon } from "@/components/icon";
import type { Requirement } from "@/lib/applications";
import { EVIDENCE_CHIP, FOCUS_RING, SECONDARY_BUTTON_S } from "@/lib/ui-classes";

export function RequirementTable({
  requirements,
  matched,
  selectedId,
  onSelect,
}: {
  requirements: Requirement[];
  matched: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <div role="table" aria-label="요구 역량과 내 카드" className="flex flex-col">
      <div role="row" className="hidden gap-4 border-b border-line-strong py-2 text-body-3 font-semibold text-text-sub md:flex">
        <span role="columnheader" className="flex-1">
          공고가 원하는 것
        </span>
        <span role="columnheader" className="w-50">
          내 카드
        </span>
        <span role="columnheader" className="w-40">
          상태
        </span>
      </div>
      {requirements.map((item) => {
        const isSelected = item.id === selectedId;
        return (
          <div
            key={item.id}
            role="row"
            aria-selected={isSelected}
            className={`flex flex-col gap-2 border-b py-3 md:flex-row md:items-center md:gap-4 ${
              isSelected ? "border-l-2 border-b-line-light border-l-line-black bg-primary-soft pl-3" : "border-line-light"
            }`}
          >
            <div role="cell" className="flex min-w-0 flex-1 flex-col gap-1">
              <button
                type="button"
                onClick={() => onSelect(item.id)}
                className={`self-start text-left text-body-1 font-medium text-text-main hover:underline ${FOCUS_RING}`}
              >
                {item.name}
                {item.kind === "preferred" ? " (우대)" : ""}
              </button>
              <p className="text-body-4 text-text-sub">{item.quote}</p>
            </div>
            <div role="cell" className="flex min-h-8 flex-wrap items-center gap-1 md:w-50">
              {item.matches.map((matchItem) => (
                <button
                  key={matchItem.id}
                  type="button"
                  onClick={() => onSelect(item.id)}
                  aria-label={`근거: 카드 ${matchItem.cardTitle} 보기`}
                  className={EVIDENCE_CHIP}
                >
                  {matchItem.cardTitle}
                </button>
              ))}
              {matched && item.matches.length === 0 ? (
                <button type="button" onClick={() => onSelect(item.id)} className={SECONDARY_BUTTON_S}>
                  기록에서 찾기
                </button>
              ) : null}
            </div>
            <div role="cell" className="flex min-h-8 items-center gap-1 md:w-40">
              <RequirementStatus matched={matched} count={item.matches.length} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RequirementStatus({ matched, count }: { matched: boolean; count: number }) {
  if (!matched) return <span className="text-body-3 text-text-sub">매칭 전</span>;
  if (count > 0) {
    return (
      <>
        <Icon name="success" size={16} className="text-success-text" />
        <span className="text-body-3 text-success-text">근거 있음</span>
      </>
    );
  }
  return (
    <>
      <Icon name="warning" size={16} className="text-sub1-text" />
      <span className="text-body-3 font-semibold text-sub1-text">근거 없음</span>
    </>
  );
}
