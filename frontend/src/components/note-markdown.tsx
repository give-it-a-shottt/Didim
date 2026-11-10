import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";
import Markdown, { type Options } from "react-markdown";
import remarkGfm from "remark-gfm";

// 노트 원문(마크다운)을 읽기 좋게 그린다(F-003 노트 상세, D-017). 서버 컴포넌트에서 그대로 쓴다.
// - 원문 속 HTML은 실행하지 않고 글자로 둔다(react-markdown 기본). javascript: 같은 위험한 링크 주소는 기본으로 비운다.
// - 이미지는 자동으로 불러오지 않고 링크로만 보여 준다(외부 주소를 노트를 열 때마다 부르지 않게, 3차 리뷰 R).
// - 원문을 조각(F-002가 저장한 위치) 단위로 나눠 따로 그린다(3차 리뷰 P). 이상한 입력의 비용이 조각 하나 안에 갇히고,
//   강조할 조각은 그 묶음을 감싸는 상자 하나로 표시한다. 코드 울타리가 조각 경계에 걸리면 닫힐 때까지 다음 조각과 합친다.
// - 서버가 오래 멈추지 않게 아래 안전장치(크기 · 깊이 · 시간 예산)에 걸리는 부분은 마크다운 대신 글자 그대로 보여 준다.
// - 이 화면의 h1은 노트 제목, h2는 "원문"이라 원문 속 제목은 h3부터 쓴다(설계 원칙 8: 화면마다 h1 하나).
// 디자인 값은 나중에 피그마 원본으로 맞춘다(사용자, 2026-11-10). 지금은 토큰으로 읽을 수 있는 정도만.

// 서버가 마크다운을 그리다 멈추지 않게 하는 안전장치(3차 리뷰 P · 4차 리뷰 X · P · Y, 사용자 확인). 넘으면 글자 그대로.
// 1) 원문 전체 크기 상한(자바스크립트 글자 수)
const MAX_MARKDOWN_RENDER_CHARS = 200_000;
// 2) 묶음 하나의 크기 상한. 조각 기준 길이(1,500자)의 두 배. 조각이 아닌 빈 구간(제목만 있는 줄 등)에도 걸린다.
//    코드 울타리를 맞추려고 조각을 합칠 때도 이 크기까지만 합친다.
const MAX_SEGMENT_MARKDOWN_CHARS = 3_000;
// 3) 줄 앞 `>`(인용) 겹침 · 들여쓰기 깊이 상한. 깊이 수천 단이면 렌더링이 스택 넘침으로 실패한다(2,000단부터, 4차 R2 실측).
const MAX_NESTING_DEPTH = 20;
// 4) 노트 하나를 그리는 시간 예산(밀리초). 넘으면 남은 묶음은 글자 그대로(묶음 수가 많은 원문의 총 비용을 묶는다).
const MARKDOWN_RENDER_BUDGET_MS = 300;

export type NoteChunkRange = {
  id: number;
  // 노트 원문의 코드 포인트(파이썬 글자) 위치 [startOffset, endOffset)
  startOffset: number;
  endOffset: number;
};

type Segment = { text: string; chunkIds: number[] };

/** 코드 포인트 위치들을 한 번 훑어 자바스크립트 문자열(UTF-16) 위치로 바꾼다. 원문 범위 밖 위치는 버린다. */
function toUtf16Offsets(text: string, codePointOffsets: number[]): Map<number, number> {
  const wanted = [...new Set(codePointOffsets)].sort((a, b) => a - b);
  const result = new Map<number, number>();
  let codePoint = 0;
  let utf16 = 0;
  let next = 0;
  for (const character of text) {
    while (next < wanted.length && wanted[next] === codePoint) {
      result.set(wanted[next], utf16);
      next += 1;
    }
    codePoint += 1;
    utf16 += character.length;
  }
  while (next < wanted.length && wanted[next] === codePoint) {
    result.set(wanted[next], utf16); // 원문 끝
    next += 1;
  }
  return result;
}

/** 원문을 조각 경계로 나눈다. 조각 사이 · 앞뒤의 빈 구간도 자기 묶음이 된다. 위치가 틀린 조각은 건너뛴다. */
function splitByChunks(text: string, chunks: NoteChunkRange[]): Segment[] {
  const offsets = toUtf16Offsets(
    text,
    chunks.flatMap((chunk) => [chunk.startOffset, chunk.endOffset]),
  );
  const ranges = chunks
    .map((chunk) => ({ id: chunk.id, start: offsets.get(chunk.startOffset), end: offsets.get(chunk.endOffset) }))
    .filter((range): range is { id: number; start: number; end: number } =>
      range.start !== undefined && range.end !== undefined && range.start < range.end,
    )
    .sort((a, b) => a.start - b.start);

  const segments: Segment[] = [];
  let cursor = 0;
  for (const range of ranges) {
    if (range.start < cursor) continue; // 겹치는 조각은 건너뜀(정상 데이터에서는 없음)
    if (range.start > cursor) segments.push({ text: text.slice(cursor, range.start), chunkIds: [] });
    segments.push({ text: text.slice(range.start, range.end), chunkIds: [range.id] });
    cursor = range.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), chunkIds: [] });
  return segments;
}

const FENCE_LINE = /^[ \t]{0,3}(```|~~~)/gm;

function hasOpenFence(text: string): boolean {
  return (text.match(FENCE_LINE)?.length ?? 0) % 2 === 1;
}

/** 코드 울타리가 열린 채 끝나는 묶음은 닫힐 때까지(상한 안에서) 다음 묶음과 합친다. */
function mergeOpenFences(segments: Segment[]): Segment[] {
  const merged: Segment[] = [];
  for (const segment of segments) {
    const last = merged.at(-1);
    if (last && hasOpenFence(last.text) && last.text.length + segment.text.length <= MAX_SEGMENT_MARKDOWN_CHARS) {
      last.text += segment.text;
      last.chunkIds.push(...segment.chunkIds);
    } else {
      merged.push({ text: segment.text, chunkIds: [...segment.chunkIds] });
    }
  }
  return merged;
}

// 줄 앞의 겹침 표시 하나: 인용 `>` 또는 목록 기호(`-` `*` `+` 또는 `1.` `1)` 뒤에 공백). 5차 리뷰: `- - - a`처럼
// 한 줄에 겹친 목록도 깊이로 센다.
const NESTING_MARKER = /^[ \t]*(?:>|[-*+](?=[ \t])|\d{1,9}[.)](?=[ \t]))/;

/** 줄 앞 겹침 표시(인용 · 목록) 수와 들여쓰기(2칸 = 1단) 중 가장 깊은 단계. */
function maxNestingDepth(text: string): number {
  let deepest = 0;
  for (const line of text.split("\n")) {
    const indent = Math.floor((line.match(/^[ \t]*/)?.[0] ?? "").replace(/\t/g, "    ").length / 2);
    let markers = 0;
    let rest = line;
    for (let match = NESTING_MARKER.exec(rest); match; match = NESTING_MARKER.exec(rest)) {
      markers += 1;
      rest = rest.slice(match[0].length);
      if (markers > MAX_NESTING_DEPTH) break; // 상한만 넘으면 더 셀 필요 없음
    }
    deepest = Math.max(deepest, indent, markers);
  }
  return deepest;
}

/** 이 묶음을 마크다운으로 그려도 되는가(크기 · 깊이 안전장치). 시간 예산은 그리는 쪽에서 본다. */
function isSafeForMarkdown(text: string): boolean {
  return text.length <= MAX_SEGMENT_MARKDOWN_CHARS && maxNestingDepth(text) <= MAX_NESTING_DEPTH;
}

function cx(...names: (string | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}

/** react-markdown이 넘기는 node(구문 트리 조각)는 HTML 속성이 아니라서 태그에 넘기지 않는다. */
function withoutNode<P extends { node?: unknown }>(props: P): Omit<P, "node"> {
  const copy = { ...props };
  delete copy.node;
  return copy;
}

/** 태그와 기본 클래스를 받아 그리는 컴포넌트를 만든다. */
function block<T extends ElementType>(Tag: T, base: string) {
  return function Block(props: ComponentPropsWithoutRef<T> & { node?: unknown; className?: string }) {
    const { className, ...rest } = withoutNode(props);
    const Component = Tag as ElementType;
    return <Component className={cx(base, className)} {...rest} />;
  };
}

const COMPONENTS: Options["components"] = {
  h1: block("h3", "mt-6 text-title-2 font-semibold first:mt-0"),
  h2: block("h4", "mt-6 text-title-3 font-semibold first:mt-0"),
  h3: block("h5", "mt-5 text-title-4 font-semibold first:mt-0"),
  h4: block("h6", "mt-4 text-body-1 font-semibold first:mt-0"),
  h5: block("h6", "mt-4 text-body-1 font-semibold first:mt-0"),
  h6: block("h6", "mt-4 text-body-1 font-semibold first:mt-0"),
  p: block("p", "mt-3 text-body-1 first:mt-0"),
  ul: block("ul", "mt-3 list-disc pl-5 text-body-1"),
  ol: block("ol", "mt-3 list-decimal pl-5 text-body-1"),
  li: block("li", "mt-1"),
  blockquote: block("blockquote", "mt-3 border-l-2 border-line-strong pl-3 text-text-sub"),
  pre: block("pre", "mt-3 overflow-x-auto rounded-input bg-bg-regular p-4 text-body-3"),
  code: block("code", "rounded-tag bg-bg-regular px-1 text-body-3"),
  hr: block("hr", "my-4 border-line-regular"),
  table: block("table", "mt-3 border-collapse text-body-2"),
  th: block("th", "border border-line-regular px-2 py-1 text-left font-semibold"),
  td: block("td", "border border-line-regular px-2 py-1"),
  strong: block("strong", "font-semibold"),
  a: function Link(props: ComponentPropsWithoutRef<"a"> & { node?: unknown }) {
    const { className, ...rest } = withoutNode(props);
    return <a className={cx("text-primary-text underline", className)} target="_blank" rel="noopener noreferrer" {...rest} />;
  },
  // 이미지는 불러오지 않고 링크로만(주소는 react-markdown이 이미 안전한 것만 남김)
  img: function ImageLink(props: ComponentPropsWithoutRef<"img"> & { node?: unknown }) {
    const { src, alt } = withoutNode(props);
    const label = `이미지: ${alt || "(설명 없음)"}`;
    return typeof src === "string" && src ? (
      <a href={src} className="text-primary-text underline" target="_blank" rel="noopener noreferrer">
        {label}
      </a>
    ) : (
      <span>{label}</span>
    );
  },
};

const HIGHLIGHT_BOX = "-mx-3 rounded-input bg-primary-soft px-3 py-2 scroll-mt-8";

/**
 * 묶음마다 마크다운(안전하면) 또는 글자 그대로를 미리 그린다. 시간 예산을 재야 해서 컴포넌트 밖에서 한 번에 처리한다
 * (컴포넌트 안에서 시계를 읽으면 React 규칙상 순수하지 않음). Markdown을 함수로 바로 불러 파싱까지 여기서 끝낸다
 * — react-markdown의 Markdown은 동기 함수이고 훅을 쓰지 않는다.
 */
function renderMarkdownBodies(segments: Segment[]): ReactNode[] {
  const startedAt = performance.now();
  return segments.map((segment, index) => {
    const withinBudget = performance.now() - startedAt <= MARKDOWN_RENDER_BUDGET_MS;
    if (withinBudget && isSafeForMarkdown(segment.text)) {
      try {
        return Markdown({ children: segment.text, remarkPlugins: [remarkGfm], components: COMPONENTS });
      } catch {
        // 안전장치를 빠져나간 입력(스택 넘침 등)은 그 묶음만 글자 그대로 보여 주고 노트 화면 전체는 살린다(5차 리뷰)
      }
    }
    return (
      <div key={index} data-segment="plain" className="whitespace-pre-wrap text-body-1">
        {segment.text}
      </div>
    );
  });
}

export function NoteMarkdown({
  content,
  chunks,
  highlightChunkId,
}: {
  content: string;
  chunks: NoteChunkRange[];
  highlightChunkId: number | null;
}) {
  const asMarkdown = content.length <= MAX_MARKDOWN_RENDER_CHARS;
  const segments = asMarkdown ? mergeOpenFences(splitByChunks(content, chunks)) : splitByChunks(content, chunks);
  const bodies = asMarkdown ? renderMarkdownBodies(segments) : segments.map((segment) => segment.text);

  return (
    <div data-render-mode={asMarkdown ? "markdown" : "plain"} className={asMarkdown ? "flex flex-col gap-3" : "whitespace-pre-wrap text-body-1"}>
      {segments.map((segment, index) => {
        if (asMarkdown && segment.text.trim() === "") return null;
        const isHighlighted = highlightChunkId !== null && segment.chunkIds.includes(highlightChunkId);
        const body = bodies[index];
        if (!isHighlighted) {
          return asMarkdown ? <div key={index}>{body}</div> : <span key={index}>{body}</span>;
        }
        const Box = asMarkdown ? "div" : "span";
        return (
          <Box key={index} id={`chunk-${highlightChunkId}`} tabIndex={-1} data-chunk-highlight="" className={asMarkdown ? HIGHLIGHT_BOX : "bg-primary-soft scroll-mt-8"}>
            {body}
          </Box>
        );
      })}
    </div>
  );
}
