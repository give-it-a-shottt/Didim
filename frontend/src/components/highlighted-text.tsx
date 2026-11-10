// 검색 결과 발췌에서 서버가 알려 준 낱말(matched_terms)을 표시한다(F-003).
// 글자 위치 대신 낱말을 문자열로 다시 찾으므로 서버 · 화면의 글자 단위 차이가 생기지 않는다.
type HighlightedTextProps = {
  text: string;
  terms: string[];
};

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function HighlightedText({ text, terms }: HighlightedTextProps) {
  const usable = terms.filter((term) => term.length > 0);
  if (usable.length === 0) {
    return <>{text}</>;
  }
  // 긴 낱말을 먼저 맞춘다("useEffect"와 "use"가 같이 있으면 긴 쪽으로 표시).
  const alternatives = [...usable].sort((a, b) => b.length - a.length).map(escapeRegExp);
  const pattern = new RegExp(`(${alternatives.join("|")})`, "giu");
  // 캡처 그룹으로 나누면 맞은 부분이 홀수 번째에 들어간다.
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <mark key={index} className="bg-primary-soft font-semibold text-text-main">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  );
}
