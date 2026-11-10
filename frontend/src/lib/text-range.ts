/**
 * 서버가 준 글자 위치(파이썬 코드 포인트 단위)로 원문을 세 부분(앞 · 구간 · 뒤)으로 자른다.
 * 자바스크립트 문자열은 UTF-16 단위라 이모지 같은 글자가 2칸을 차지한다. 그래서 text.slice(start, end)를
 * 쓰면 이모지 뒤의 위치가 어긋난다 → Array.from(text)로 코드 포인트 단위로 바꿔 자른다(F-002 결과의 한계 메모).
 * 위치가 원문 범위를 벗어나면 null(강조 없이 원문만 보여 준다).
 */
export function sliceByCodePoints(text: string, start: number, end: number): [string, string, string] | null {
  const characters = Array.from(text);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end > characters.length || start >= end) {
    return null;
  }
  return [
    characters.slice(0, start).join(""),
    characters.slice(start, end).join(""),
    characters.slice(end).join(""),
  ];
}
