// 브라우저에서 부르는 요청(TanStack Query의 queryFn · mutationFn, D-012)이 같이 쓰는 요청 함수와 오류.
// 퀴즈(lib/quiz.ts) · 경험 카드(lib/cards.ts)가 각자 복사해 두던 것을 한곳에 모았다(F-006 1차 리뷰 R1, 사용자 확인 2026-11-11).
// 브라우저는 같은 주소의 /api/*로 부르고 Next가 FastAPI로 넘긴다(next.config.ts rewrites, D-010).
import { detailOf, readJson } from "@/lib/json";

/** 실패 이유를 담은 오류. 화면은 message를 그대로 보여 주고, needsLogin이면 로그인 링크를 같이 둔다. */
export class ApiRequestError extends Error {
  readonly needsLogin: boolean;
  readonly status: number | null;

  constructor(message: string, { needsLogin = false, status = null }: { needsLogin?: boolean; status?: number | null } = {}) {
    super(message);
    this.name = "ApiRequestError";
    this.needsLogin = needsLogin;
    this.status = status;
  }
}

const NETWORK_ERROR = "네트워크 문제로 보내지 못했어요. 연결을 확인하고 다시 시도해 주세요.";
const LOGIN_ERROR = "로그인이 풀렸어요. 다시 로그인해 주세요.";

/**
 * 요청을 보내고 성공하면 본문(JSON, 없으면 null)을 돌려준다. 실패는 모두 ApiRequestError로 던진다.
 * - 네트워크 실패 → 연결 확인 문구, 401 → 로그인 문구(needsLogin), 그 밖의 실패 → 서버 문구(detail), 없으면 fallback.
 * 응답 모양 확인은 부르는 쪽이 한다(기능마다 모양이 달라서).
 */
export async function apiRequest(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  fallback: string,
  payload?: unknown,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
  } catch {
    throw new ApiRequestError(NETWORK_ERROR);
  }
  const body = await readJson(response);
  if (response.status === 401) {
    throw new ApiRequestError(LOGIN_ERROR, { needsLogin: true, status: 401 });
  }
  if (!response.ok) {
    throw new ApiRequestError(detailOf(body) ?? fallback, { status: response.status });
  }
  return body;
}
