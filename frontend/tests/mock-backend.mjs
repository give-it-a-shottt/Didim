import http from "node:http";

const PORT = Number(process.env.MOCK_BACKEND_PORT ?? 8100);
const VALID_TOKEN = "playwright-valid-session-token";

// 기록 검색 · 노트 상세(F-003) 가짜 데이터. 이모지(UTF-16 2칸)를 두 번째 조각 앞에 넣어,
// 화면이 서버의 코드 포인트 위치를 그대로 쓰면(text.slice) 강조가 한 글자 어긋나는 것을 잡는다.
// useEffect 칸에는 원문 안전 확인용으로 HTML · javascript: 링크 · 이미지를 넣는다(실행 · 이동 · 자동 불러오기가 없어야 함).
const NOTE_CONTENT =
  "# React 정리\n\n## useEffect\nuseEffect는 그려진 뒤 부수 효과를 실행해요.\n\n" +
  "<script>window.__didimXss = 1</script>\n\n[나쁜 링크](javascript:alert(1))\n\n![다이어그램](https://example.com/a.png)\n\n" +
  "마지막 문장 😀\n\n## useState\n상태를 바꾸면 다시 그려져요.\n";
// 마크다운 대신 글자 그대로 보여 주는 큰 노트(200KB 초과)
const BIG_NOTE_CONTENT = "# 큰 노트\n\n" + "가나다라 ".repeat(45000) + "\n";
const BIG_NOTE = {
  id: 2,
  title: "큰 노트",
  kind: "study",
  source: "markdown",
  created_at: "2026-11-10T00:00:00Z",
  content: BIG_NOTE_CONTENT,
  chunks: [{ id: 21, position: 0, heading_path: "# 큰 노트", start_offset: 0, end_offset: Array.from(BIG_NOTE_CONTENT).length }],
};
const codePointIndex = (sub) => Array.from(NOTE_CONTENT.slice(0, NOTE_CONTENT.indexOf(sub))).length;
const NOTE_LENGTH = Array.from(NOTE_CONTENT).length;
const MOCK_NOTE = {
  id: 1,
  title: "React 정리",
  kind: "study",
  source: "markdown",
  created_at: "2026-11-10T00:00:00Z",
  content: NOTE_CONTENT,
  chunks: [
    {
      id: 11,
      position: 0,
      heading_path: "# React 정리 > ## useEffect",
      start_offset: codePointIndex("## useEffect"),
      end_offset: codePointIndex("## useState"),
    },
    {
      id: 12,
      position: 1,
      heading_path: "# React 정리 > ## useState",
      start_offset: codePointIndex("## useState"),
      end_offset: NOTE_LENGTH,
    },
  ],
};

// 이상한 노트(안전장치 확인): 제목 줄에 `*a` 5만 자(조각이 아닌 빈 구간) + 보통 조각 + `>` 3천 단 조각
const cp = (text, sub) => Array.from(text.slice(0, text.indexOf(sub))).length;
const ODD_CONTENT = "# " + "*a".repeat(25000) + "\n\n## 본문\n본문 문장\n\n" + ">".repeat(3000) + " 깊은 인용\n";
const ODD_NOTE = {
  id: 3, title: "이상한 노트", kind: "study", source: "markdown", created_at: "2026-11-10T00:00:00Z", content: ODD_CONTENT,
  chunks: [
    { id: 31, position: 0, heading_path: "## 본문", start_offset: cp(ODD_CONTENT, "## 본문"), end_offset: cp(ODD_CONTENT, ">>>") },
    { id: 32, position: 1, heading_path: "## 본문", start_offset: cp(ODD_CONTENT, ">>>"), end_offset: Array.from(ODD_CONTENT).length },
  ],
};
// 코드 울타리가 조각 경계에 걸린 노트 + 위치가 원문을 벗어난 조각(49)
const FENCE_CONTENT = "# 코드\n\n## 예시\n```js\nconst a = 1;\n\n## 이어짐\nconst b = 2;\n```\n끝\n";
const FENCE_NOTE = {
  id: 4, title: "코드 노트", kind: "study", source: "markdown", created_at: "2026-11-10T00:00:00Z", content: FENCE_CONTENT,
  chunks: [
    { id: 41, position: 0, heading_path: "# 코드 > ## 예시", start_offset: cp(FENCE_CONTENT, "## 예시"), end_offset: cp(FENCE_CONTENT, "## 이어짐") },
    { id: 42, position: 1, heading_path: "# 코드 > ## 이어짐", start_offset: cp(FENCE_CONTENT, "## 이어짐"), end_offset: Array.from(FENCE_CONTENT).length },
    { id: 49, position: 2, heading_path: "# 코드", start_offset: 0, end_offset: 999999 },
  ],
};
// 시간 예산 확인용: 묶음 하나하나는 안전장치(3,000자 · 깊이 20)를 통과하지만 파싱이 느린 조각이 60개 —
// 앞쪽 몇 개만 마크다운이고, 300ms를 넘긴 뒤는 글자 그대로여야 한다.
const SLOW_SECTIONS = Array.from({ length: 60 }, (_, index) => `## 느린 절 ${index}\n${"*a".repeat(1400)}\n\n`);
const SLOW_CONTENT = "# 느린 노트\n\n" + SLOW_SECTIONS.join("");
let slowCursor = Array.from("# 느린 노트\n\n").length;
const SLOW_NOTE = {
  id: 5, title: "느린 노트", kind: "study", source: "markdown", created_at: "2026-11-10T00:00:00Z", content: SLOW_CONTENT,
  chunks: SLOW_SECTIONS.map((section, index) => {
    const start = slowCursor;
    slowCursor += Array.from(section).length;
    return { id: 500 + index, position: index, heading_path: `## 느린 절 ${index}`, start_offset: start, end_offset: slowCursor };
  }),
};
const EXTRA_NOTES = new Map([[3, ODD_NOTE], [4, FENCE_NOTE], [5, SLOW_NOTE]]);

const isLoggedIn = (req) => (req.headers.cookie ?? "").includes(`didim_session=${VALID_TOKEN}`);

const sendJson = (res, status, body) => {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://mock");

  // 기록 검색(F-003): 검색어에 따라 응답을 바꾼다.
  // "검색불가" · "시간초과" → 503(서버가 준 이유), "검색오류" → 500, "모양틀림" → 200인데 결과 모양이 틀림,
  // "없는말" → 결과 없음, 나머지 → 노트 1의 useState 조각 하나.
  if (req.method === "GET" && url.pathname === "/api/search") {
    if (!isLoggedIn(req)) {
      sendJson(res, 401, { detail: "로그인이 필요해요." });
      return;
    }
    const q = url.searchParams.get("q") ?? "";
    if (q === "검색불가") {
      sendJson(res, 503, { detail: "지금은 기록 검색을 쓸 수 없어요." });
      return;
    }
    if (q === "시간초과") {
      sendJson(res, 503, { detail: "검색이 오래 걸려 멈췄어요. 낱말을 줄이거나 더 구체적인 낱말로 찾아보세요." });
      return;
    }
    if (q === "검색오류") {
      sendJson(res, 500, { detail: "Internal Server Error" });
      return;
    }
    if (q === "모양틀림") {
      sendJson(res, 200, { query: q, terms: [q], method: "keyword", results: [{ chunk_id: "열둘" }] });
      return;
    }
    const chunk = MOCK_NOTE.chunks[1];
    const results =
      q === "없는말"
        ? []
        : [
            {
              chunk_id: chunk.id,
              note_id: MOCK_NOTE.id,
              note_title: MOCK_NOTE.title,
              heading_path: chunk.heading_path,
              start_offset: chunk.start_offset,
              end_offset: chunk.end_offset,
              excerpt: "useState 상태를 바꾸면 다시 그려져요.", // 서버는 발췌에서 마크다운 기호를 뺀다
              matched_terms: ["useState"],
              score: 1,
            },
          ];
    sendJson(res, 200, { query: q, terms: [q], method: "keyword", results });
    return;
  }

  // 노트 상세(F-003): 노트 1만 있다. 500번은 서버 오류, 나머지는 404(없거나 다른 사람 노트).
  const noteMatch = req.method === "GET" ? url.pathname.match(/^\/api\/notes\/(\d+)$/) : null;
  if (noteMatch) {
    if (!isLoggedIn(req)) {
      sendJson(res, 401, { detail: "로그인이 필요해요." });
      return;
    }
    if (Number(noteMatch[1]) === MOCK_NOTE.id) {
      sendJson(res, 200, MOCK_NOTE);
    } else if (Number(noteMatch[1]) === BIG_NOTE.id) {
      sendJson(res, 200, BIG_NOTE);
    } else if (EXTRA_NOTES.has(Number(noteMatch[1]))) {
      sendJson(res, 200, EXTRA_NOTES.get(Number(noteMatch[1])));
    } else if (Number(noteMatch[1]) === 500) {
      sendJson(res, 500, { detail: "Internal Server Error" });
    } else {
      sendJson(res, 404, { detail: "노트를 찾을 수 없어요." });
    }
    return;
  }

  if (req.method === "GET" && req.url === "/api/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok" }));
    return;
  }

  if (req.method === "GET" && req.url === "/api/auth/me") {
    const cookieHeader = req.headers.cookie ?? "";
    if (cookieHeader.includes(`didim_session=${VALID_TOKEN}`)) {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          id: 1,
          email: "didim@example.com",
          name: "이디딤",
        }),
      );
      return;
    }
    res.writeHead(401, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ detail: "로그인이 필요해요." }));
    return;
  }

  // 기록 가져오기(F-002) 가짜 응답: 본문에서 파일 이름만 꺼내 .md는 성공, 나머지는 실패로 돌려준다.
  if (req.method === "POST" && req.url === "/api/notes/import") {
    const cookieHeader = req.headers.cookie ?? "";
    if (!cookieHeader.includes(`didim_session=${VALID_TOKEN}`)) {
      res.writeHead(401, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "로그인이 필요해요." }));
      return;
    }
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const body = Buffer.concat(chunks).toString("utf8");
      const names = [...body.matchAll(/filename="([^"]*)"/g)].map((match) => match[1]);
      const imported = names
        .filter((name) => name.endsWith(".md"))
        .map((name, index) => ({ filename: name, note_id: index + 1, title: name.replace(/\.md$/, ""), chunk_count: 2 }));
      const failed = names
        .filter((name) => !name.endsWith(".md"))
        .map((name) => ({ filename: name, reason: "마크다운(.md) 파일만 올릴 수 있어요." }));
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          summary: { notes: imported.length, chunks: imported.length * 2, duplicates: 0, failed: failed.length },
          imported,
          duplicates: [],
          failed,
        }),
      );
    });
    return;
  }

  if (req.method === "POST" && req.url === "/api/auth/logout") {
    res.writeHead(204, {
      "Set-Cookie": "didim_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
    });
    res.end();
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ detail: "Not Found" }));
});

server.listen(PORT, "127.0.0.1");
