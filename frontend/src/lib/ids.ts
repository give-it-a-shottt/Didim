// 주소에서 받은 DB 번호(노트 · 조각 · 문제)를 확인한다. DB integer(32비트) 범위의 양수만.
// 더 긴 숫자는 Number()가 정밀도를 잃으므로 먼저 거른다(F-003 1차 리뷰 E). 서버 MAX_NOTE_ID와 같은 값이다.
const MAX_DB_ID = 2_147_483_647;

export function parseDbId(value: unknown): number | null {
  if (typeof value !== "string" || !/^[1-9]\d{0,9}$/.test(value)) {
    return null;
  }
  const id = Number(value);
  return id <= MAX_DB_ID ? id : null;
}
