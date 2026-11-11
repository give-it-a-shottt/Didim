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
// 퀴즈(F-004) 전용 노트: 6은 [문제 만들기] 성공(만든 뒤에는 문제가 생김), 7은 오늘 AI 사용량을 다 씀(429).
// 상태가 바뀌는 응답은 이 노트들에만 둔다(테스트가 같은 가짜 서버를 동시에 쓰므로).
const smallNote = (id, title) => {
  const content = `# ${title}

## 본문
${title} 본문이에요.
`;
  return {
    id, title, kind: "study", source: "markdown", created_at: "2026-11-10T00:00:00Z", content,
    chunks: [{ id: id * 10 + 1, position: 0, heading_path: `# ${title} > ## 본문`, start_offset: cp(content, "## 본문"), end_offset: Array.from(content).length }],
  };
};
const GENERATE_NOTE = smallNote(6, "만들기 노트");
const LIMIT_NOTE = smallNote(7, "한도 노트");
// 경험 카드(F-006) 예외 경로 전용 노트: 8은 찾아도 후보 0개, 9는 다른 탭이 먼저 찾음(409 → 새로 고침하면 후보),
// 10은 후보 1001(불러오기 실패) · 1002가 있는 노트.
const NONE_FOUND_NOTE = smallNote(8, "경험 없는 노트");
const OTHER_TAB_NOTE = smallNote(9, "다른 탭 노트");
const BROKEN_CANDIDATE_NOTE = smallNote(10, "깨진 후보 노트");
const EXTRA_NOTES = new Map([
  [3, ODD_NOTE], [4, FENCE_NOTE], [5, SLOW_NOTE], [6, GENERATE_NOTE], [7, LIMIT_NOTE],
  [8, NONE_FOUND_NOTE], [9, OTHER_TAB_NOTE], [10, BROKEN_CANDIDATE_NOTE],
]);

// 퀴즈 · 복습(F-004) 가짜 데이터. 목록에는 정답 · 해설 · 인용이 없고, 답을 내면 받는다(서버와 같은 모양).
// 101: 노트 1 객관식(정답 1번), 102: 노트 1 OX(정답 O, 오답노트에 있음 — 맞히면 빠짐).
const QUIZ_CARDS = [
  {
    id: 101, note_id: 1, note_title: "React 정리", kind: "mcq", question: "useEffect는 언제 실행되나요?",
    choices: ["그리기 전", "그려진 뒤", "서버에서만", "실행되지 않음"], next_review_on: "2026-11-11", in_wrong_notes: false,
  },
  {
    id: 102, note_id: 1, note_title: "React 정리", kind: "ox", question: "상태를 바꾸면 다시 그려진다.",
    choices: ["O", "X"], next_review_on: "2026-11-11", in_wrong_notes: true,
  },
];
const QUIZ_ANSWERS = new Map([
  [101, { answer_index: 1, explanation: "useEffect는 화면을 그린 뒤 실행돼요.", chunk_id: 11, quote: "useEffect는 그려진 뒤 부수 효과를 실행해요." }],
  [102, { answer_index: 0, explanation: "상태가 바뀌면 컴포넌트를 다시 그려요.", chunk_id: 12, quote: "상태를 바꾸면 다시 그려져요." }],
]);
const generatedNotes = new Set(); // [문제 만들기]에 성공한 노트(6)
const GENERATED_CARD = {
  id: 601, note_id: 6, note_title: "만들기 노트", kind: "ox", question: "만들기 노트 본문이 있다.",
  choices: ["O", "X"], next_review_on: "2026-11-11", in_wrong_notes: false,
};
const noteQuizzes = (noteId) => {
  if (noteId === 1) return QUIZ_CARDS;
  if (noteId === 6 && generatedNotes.has(6)) return [GENERATED_CARD];
  return [];
};
// 경험 카드(F-006) 가짜 데이터. 테스트가 동시에 돌아서 테스트마다 다른 카드를 쓴다.
// 801: 저장한 카드(목록 · 상세 읽기 전용) · 802: 노트 1의 후보(목록 읽기 전용) · 803: 저장한 카드(상세 고치기 테스트)
// 811 · 812: 노트 4의 후보(후보 검토 시트 테스트). 노트 4 · 1은 이미 찾음, 노트 6에서 찾으면 906이 생김, 노트 7은 429.
// 804: 저장한 카드(결과 칸 저장만 500으로 실패 — 앞 칸은 저장됨) · 1001 · 1002: 노트 10의 후보(1001은 불러오기 500).
// 노트 8에서 찾으면 후보 0개, 노트 9에서 찾으면 다른 탭이 먼저 찾은 것처럼 909를 만들고 409.
const SLOTS = ["situation", "task", "action", "result"];
const mockCard = (id, noteId, status, title, quotes) => ({
  id, note_id: noteId, note_title: noteId === 1 ? "React 정리" : noteId === 4 ? "코드 노트" : "만들기 노트",
  title, status, created_at: "2026-11-10T03:00:00Z", updated_at: "2026-11-10T03:00:00Z",
  fields: SLOTS.map((slot) => ({
    slot, quote: quotes[slot] ?? null, quote_start: quotes[slot] ? 0 : null,
    quote_end: quotes[slot] ? Array.from(quotes[slot]).length : null, chunk_id: quotes[slot] ? 11 : null,
    question: quotes[slot] ? null : `${slot} 칸에 무엇을 적을까요?`, answer: null,
  })),
});
const MOCK_CARDS = new Map(
  [
    mockCard(801, 1, "saved", "useEffect로 구독 정리", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요.", action: "상태를 바꾸면 다시 그려져요." }),
    mockCard(802, 1, "candidate", "상태 바꾸기 실험", { situation: "상태를 바꾸면 다시 그려져요." }),
    mockCard(803, 1, "saved", "고칠 카드", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요.", action: "상태를 바꾸면 다시 그려져요." }),
    mockCard(811, 4, "candidate", "코드 블록 정리", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요." }),
    mockCard(812, 4, "candidate", "버릴 후보", { action: "상태를 바꾸면 다시 그려져요." }),
    mockCard(804, 1, "saved", "저장이 실패하는 카드", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요." }),
    mockCard(1001, 10, "candidate", "불러오지 못하는 후보", { situation: "깨진 후보 노트 본문이에요." }),
    mockCard(1002, 10, "candidate", "멀쩡한 후보", { situation: "깨진 후보 노트 본문이에요." }),
  ].map((card) => [card.id, card]),
);
const searchedNotes = new Set([1, 4, 10]);
const isBlankField = (field) => field.quote === null && field.answer === null;
const cardSummary = (card) => ({
  id: card.id, title: card.title, status: card.status, note_id: card.note_id, note_title: card.note_title,
  blank_count: card.fields.filter(isBlankField).length,
  evidence_count: card.fields.filter((field) => field.quote !== null).length,
  updated_at: card.updated_at, blank_slots: card.fields.filter(isBlankField).map((field) => field.slot),
});
const cardDetail = (card) => {
  const summary = cardSummary(card);
  delete summary.blank_slots; // 상세에는 없음(서버와 같은 모양)
  return { ...summary, created_at: card.created_at, fields: card.fields };
};
const noteExists = (noteId) => noteId === MOCK_NOTE.id || noteId === BIG_NOTE.id || EXTRA_NOTES.has(noteId);

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

  // --- 퀴즈 · 복습(F-004) ---
  if (url.pathname === "/api/notes" || url.pathname === "/api/reviews/today" || url.pathname === "/api/wrong-answers" ||
      /^\/api\/(notes\/\d+\/quizzes|quizzes\/\d+\/answer)$/.test(url.pathname)) {
    if (!isLoggedIn(req)) {
      sendJson(res, 401, { detail: "로그인이 필요해요." });
      return;
    }
  }
  if (req.method === "GET" && url.pathname === "/api/notes") {
    const summary = (note, quizCount) => ({
      id: note.id, title: note.title, kind: note.kind, created_at: note.created_at,
      chunk_count: note.chunks.length, quiz_count: quizCount,
    });
    sendJson(res, 200, { total: 2, notes: [summary(MOCK_NOTE, QUIZ_CARDS.length), summary(FENCE_NOTE, 0)] });
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/reviews/today") {
    sendJson(res, 200, { total: QUIZ_CARDS.length, quizzes: QUIZ_CARDS });
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/wrong-answers") {
    const wrong = QUIZ_CARDS.filter((card) => card.in_wrong_notes);
    sendJson(res, 200, { total: wrong.length, quizzes: wrong });
    return;
  }
  const quizListMatch = url.pathname.match(/^\/api\/notes\/(\d+)\/quizzes$/);
  if (quizListMatch) {
    const noteId = Number(quizListMatch[1]);
    if (!noteExists(noteId)) {
      sendJson(res, 404, { detail: "노트를 찾을 수 없어요." });
    } else if (req.method === "GET") {
      sendJson(res, 200, { quizzes: noteQuizzes(noteId) });
    } else if (req.method === "POST" && noteId === 7) {
      sendJson(res, 429, { detail: "오늘 AI 사용량(30회)을 다 썼어요. 한국 시간 0시에 다시 쓸 수 있어요." });
    } else if (req.method === "POST" && noteId === 6 && !generatedNotes.has(6)) {
      generatedNotes.add(6);
      sendJson(res, 201, { note_id: 6, created: 1, dropped: 1, drop_reasons: { quote_not_found: 1 }, remaining_today: 29 });
    } else if (req.method === "POST") {
      sendJson(res, 409, { detail: "이 노트에는 이미 문제가 있어요." });
    } else {
      sendJson(res, 405, { detail: "Method Not Allowed" });
    }
    return;
  }
  const answerMatch = req.method === "POST" ? url.pathname.match(/^\/api\/quizzes\/(\d+)\/answer$/) : null;
  if (answerMatch) {
    const quizId = Number(answerMatch[1]);
    const card = QUIZ_CARDS.find((item) => item.id === quizId);
    const answer = QUIZ_ANSWERS.get(quizId);
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      if (!card || !answer) {
        sendJson(res, 404, { detail: "문제를 찾을 수 없어요." });
        return;
      }
      const chosen = JSON.parse(Buffer.concat(chunks).toString("utf8")).chosen_index;
      const correct = chosen === answer.answer_index;
      sendJson(res, 200, {
        correct, answer_index: answer.answer_index, explanation: answer.explanation,
        note_id: card.note_id, note_title: card.note_title, chunk_id: answer.chunk_id, quote: answer.quote,
        quote_start: 0, quote_end: answer.quote.length,
        next_review_on: correct ? "2026-11-12" : "2026-11-11",
        in_wrong_notes: !correct, // 틀리면 오답노트, 맞히면(102는 연속 2번째라고 가정) 빠짐
      });
    });
    return;
  }

  // --- 경험 카드(F-006) ---
  if (url.pathname === "/api/cards" || /^\/api\/(cards\/\d+(\/save|\/fields\/\w+)?|notes\/\d+\/cards\/candidates)$/.test(url.pathname)) {
    if (!isLoggedIn(req)) {
      sendJson(res, 401, { detail: "로그인이 필요해요." });
      return;
    }
  }
  if (req.method === "GET" && url.pathname === "/api/cards") {
    const status = url.searchParams.get("status") ?? "saved";
    const noteParam = url.searchParams.get("note_id");
    const noteId = noteParam === null ? null : Number(noteParam);
    const list = [...MOCK_CARDS.values()].filter(
      (card) => card.status === status && (noteId === null || card.note_id === noteId),
    );
    sendJson(res, 200, {
      total: list.length,
      cards: list.map(cardSummary),
      note_searched: noteId === null ? null : searchedNotes.has(noteId),
    });
    return;
  }
  const findMatch = req.method === "POST" ? url.pathname.match(/^\/api\/notes\/(\d+)\/cards\/candidates$/) : null;
  if (findMatch) {
    const noteId = Number(findMatch[1]);
    if (!noteExists(noteId)) {
      sendJson(res, 404, { detail: "노트를 찾을 수 없어요." });
    } else if (noteId === 7) {
      sendJson(res, 429, { detail: "오늘 AI 사용량(30회)을 다 썼어요. 한국 시간 0시에 다시 쓸 수 있어요." });
    } else if (searchedNotes.has(noteId)) {
      sendJson(res, 409, { detail: "이 노트에서는 이미 카드 후보를 찾았어요." });
    } else if (noteId === 8) {
      sendJson(res, 201, {
        note_id: noteId, card_ids: [], quoted_fields: 0, emptied_fields: 0,
        drop_reasons: {}, chunks_sent: 1, chunks_total: 1, remaining_today: 27,
      });
    } else if (noteId === 9) {
      // 다른 탭에서 먼저 찾아 끝난 상황: 후보는 이미 있고 이 요청은 409
      searchedNotes.add(noteId);
      MOCK_CARDS.set(909, mockCard(909, noteId, "candidate", "다른 탭에서 찾은 경험", { situation: "다른 탭 노트 본문이에요." }));
      sendJson(res, 409, { detail: "이 노트에서는 이미 카드 후보를 찾았어요." });
    } else {
      searchedNotes.add(noteId);
      const card = mockCard(900 + noteId, noteId, "candidate", "만들기 노트에서 찾은 경험", {
        situation: "만들기 노트 본문이 있다.",
      });
      MOCK_CARDS.set(card.id, card);
      sendJson(res, 201, {
        note_id: noteId, card_ids: [card.id], quoted_fields: 1, emptied_fields: 1,
        drop_reasons: { quote_not_found: 1 }, chunks_sent: 1, chunks_total: 1, remaining_today: 28,
      });
    }
    return;
  }
  const cardMatch = url.pathname.match(/^\/api\/cards\/(\d+)(\/save|\/fields\/(\w+))?$/);
  if (cardMatch) {
    const card = MOCK_CARDS.get(Number(cardMatch[1]));
    if (!card) {
      sendJson(res, 404, { detail: "카드를 찾을 수 없어요." });
      return;
    }
    if (req.method === "GET" && !cardMatch[2] && card.id === 1001) {
      sendJson(res, 500, { detail: "카드를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요." });
      return;
    }
    if (req.method === "GET" && !cardMatch[2]) {
      sendJson(res, 200, cardDetail(card));
      return;
    }
    if (req.method === "DELETE" && !cardMatch[2]) {
      MOCK_CARDS.delete(card.id);
      res.writeHead(204);
      res.end();
      return;
    }
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
      if (req.method === "POST" && cardMatch[2] === "/save") {
        const title = String(body.title ?? "").trim();
        if (!title) {
          sendJson(res, 422, { detail: "카드 제목을 적어 주세요." });
          return;
        }
        card.title = title;
        card.status = "saved";
      } else if (req.method === "PUT" && cardMatch[3] === "result" && card.id === 804) {
        sendJson(res, 500, { detail: "칸을 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요." });
        return;
      } else if (req.method === "PUT" && cardMatch[3]) {
        const field = card.fields.find((item) => item.slot === cardMatch[3]);
        if (!field) {
          sendJson(res, 422, { detail: "칸 이름이 틀렸어요." });
          return;
        }
        field.answer = String(body.answer ?? "").trim() || null;
        if (body.remove_quote && field.quote !== null) {
          Object.assign(field, { quote: null, quote_start: null, quote_end: null, chunk_id: null, question: "직접 적어 주세요." });
        }
      } else {
        sendJson(res, 405, { detail: "Method Not Allowed" });
        return;
      }
      card.updated_at = "2026-11-11T03:00:00Z";
      sendJson(res, 200, cardDetail(card));
    });
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
