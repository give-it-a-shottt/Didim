// 서버 응답(JSON)을 읽고 모양을 확인할 때 같이 쓰는 작은 함수들. 서버 컴포넌트 · 브라우저 모두에서 쓴다.
// 기록 가져오기 · 검색 · 노트 · 퀴즈가 각자 복사해 두던 것을 한곳에 모았다(F-004 1차 리뷰 R1).

export type Json = Record<string, unknown>;

export function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null;
}

export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

/** 본문이 JSON이 아니면(프록시 오류 화면 등) 없는 것(null)으로 본다. 예외를 던지지 않는다. */
export async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/** FastAPI 오류 응답의 detail 문구. 문자열이 아니면(검증 오류 목록 등) null — 화면은 기본 문구를 쓴다. */
export function detailOf(body: unknown): string | null {
  return isObject(body) && typeof body.detail === "string" ? body.detail : null;
}
