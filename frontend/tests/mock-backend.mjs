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
// 면접 연습(F-009): 831 [면접 질문 만들기] 성공(질문 2개가 생김) · 832 질문 3개(8322는 근거가 바뀜, 8323은 메모 저장 500) ·
// 833 만들기 503 · 834 질문 없는 저장 카드(공고 930 · 933에 매칭) · 835 만들기는 되는데 그 뒤 카드 다시 받기 500 ·
// 836 질문 8361(메모 저장이 1.5초 — 저장 중에 이어 쓰기, 공고 935에 매칭) · 837 다른 탭이 먼저 만들어 409(누르는 순간 질문이 생김) ·
// 838 409에 카드 다시 받기까지 500.
const interviewQuestion = (id, cardId, position, slot, question, quote, extra = {}) => ({
  id, card_id: cardId, position, slot, question, quote, quote_source: "quote", evidence_status: "ok",
  memo: null, answered_at: null, updated_at: "2026-11-15T03:00:00Z", ...extra,
});
const withInterview = (card, questions) => ({ ...card, interview: questions });
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
    mockCard(831, 1, "saved", "질문 만들 카드", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요.", action: "상태를 바꾸면 다시 그려져요." }),
    withInterview(
      mockCard(832, 1, "saved", "Redis 재설계", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요.", action: "상태를 바꾸면 다시 그려져요." }),
      [
        interviewQuestion(8321, 832, 0, "situation", "그 상황에서 무엇이 문제였나요?", "useEffect는 그려진 뒤", {
          memo: "그려진 뒤 실행되는 점을 먼저 말한다", answered_at: "2026-11-15T03:00:00Z",
        }),
        interviewQuestion(8322, 832, 1, "action", "왜 상태를 바꾸는 방법을 골랐나요?", "상태를 바꾸면 다시", { evidence_status: "changed" }),
        interviewQuestion(8323, 832, 2, "action", "다시 그려지는 걸 어떻게 확인했나요?", "다시 그려져요"),
      ],
    ),
    mockCard(833, 1, "saved", "질문 만들기가 실패하는 카드", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요." }),
    mockCard(834, 1, "saved", "질문 없는 카드", { situation: "상태를 바꾸면 다시 그려져요." }),
    mockCard(835, 1, "saved", "다시 받기가 실패하는 카드", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요." }),
    mockCard(837, 1, "saved", "다른 탭에서 만든 카드", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요." }),
    mockCard(838, 1, "saved", "409 뒤 다시 받기도 실패하는 카드", { situation: "useEffect는 그려진 뒤 부수 효과를 실행해요." }),
    withInterview(mockCard(836, 1, "saved", "느린 메모 카드", { situation: "상태를 바꾸면 다시 그려져요." }), [
      interviewQuestion(8361, 836, 0, "situation", "느린 메모 질문인가요?", "상태를 바꾸면"),
    ]),
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
  return { ...summary, created_at: card.created_at, fields: card.fields, interview_questions: card.interview ?? [] };
};
const noteExists = (noteId) => noteId === MOCK_NOTE.id || noteId === BIG_NOTE.id || EXTRA_NOTES.has(noteId);

const isLoggedIn = (req) => (req.headers.cookie ?? "").includes(`didim_session=${VALID_TOKEN}`);

// 노션 연결(F-005) 가짜 페이지 번호
const NOTION_PAGE_A = "0000000a-0000-4000-8000-00000000000a";
const NOTION_PAGE_B = "0000000b-0000-4000-8000-00000000000b";
const NOTION_PAGE_C = "0000000c-0000-4000-8000-00000000000c";
const notionFlakySeen = new Set(); // "-notion-flaky": 세션마다 첫 목록 요청만 실패

// --- 지원 · 공고 분석(F-007) 가짜 데이터 ---
const POSTING_A = "자격 요건\n- React로 화면을 만든 경험\n- 클라우드 배포 경험\n";
const appRequirement = (id, name, kind, posting, quote, matches = []) => ({
  id, position: 0, name, kind, quote, quote_start: posting.indexOf(quote), quote_end: posting.indexOf(quote) + quote.length, matches,
});
const mockApplication = (id, company, role, extra = {}) => ({
  id, company, role, deadline: null, days_left: null, url: null, posting_text: POSTING_A, status: "ready",
  extracted_at: null, matched_at: null, created_at: "2026-11-12T03:00:00Z", updated_at: "2026-11-12T03:00:00Z",
  questions: [{ id: id * 10, position: 0, text: "지원 동기", char_limit: 700 }], requirements: [], ...extra,
});
const MOCK_APPLICATIONS = new Map(
  [
    mockApplication(901, "누리랩", "풀스택 개발자 (신입)", {
      deadline: "2026-11-15", days_left: 3, status: "writing", url: "https://example.com/jobs/901",
      extracted_at: "2026-11-12T03:00:00Z", matched_at: "2026-11-12T03:01:00Z",
      requirements: [
        appRequirement(9011, "React 화면 개발", "required", POSTING_A, "React로 화면을 만든 경험", [
          { id: 1, card_id: 801, card_title: "useEffect로 구독 정리", slot: "situation", quote: "useEffect는 그려진 뒤 부수 효과를 실행해요.",
            quote_source: "quote", quote_start: 0, quote_end: 27, reason: "React 훅으로 화면을 다룬 경험이에요." },
        ]),
        appRequirement(9012, "클라우드 배포", "preferred", POSTING_A, "클라우드 배포 경험"),
      ],
    }),
    mockApplication(902, "바른책방", "프론트엔드 개발자", { deadline: "2026-11-24", days_left: 12 }),
    mockApplication(903, "모아데이터", "백엔드 개발자 인턴"),
    mockApplication(904, "한도회사", "개발자"),
    mockApplication(905, "지울회사", "개발자", { status: "submitted", deadline: "2026-11-01", days_left: -11 }),
    // 906: 뽑기는 2개라고 답하지만 상세는 늦게 바뀌고(새로 받기 전 상태), 매칭은 3초 걸림 — ① 직후 화면 확인용
    mockApplication(906, "늦은회사", "개발자"),
    // 907: 상태 바꾸기 · 지우기가 서버 오류(500, 글자)로 실패 — 머리의 오류 표시 확인용(F-007 4차 R3)
    mockApplication(907, "실패회사", "개발자", { status: "ready" }),
    // --- 자소서(F-008) 전용 공고. 모두 카드 801과 매칭됨(912만 매칭 없음). 테스트마다 다른 공고 ---
    ...[
      [910, "초안회사"], [911, "쓰기회사"], [913, "실패쓰기회사"], [914, "제출회사"], [915, "고치기회사"], [916, "연결회사"], [917, "문항회사"], [918, "충돌회사"], [919, "목록실패회사"], [920, "완료실패회사"], [921, "다시받기실패회사"], [922, "문항충돌회사"], [923, "확인회사"], [924, "개수모양회사"], [925, "확인모양회사"], [926, "확인충돌회사"], [927, "확인없음회사"],
    ].map(([id, company]) => mockApplication(id, company, "개발자", { extracted_at: "2026-11-12T03:00:00Z", matched_at: "2026-11-12T03:01:00Z", requirements: matchedRequirements(id) })),
    mockApplication(912, "카드없는회사", "개발자", { extracted_at: "2026-11-12T03:00:00Z", matched_at: "2026-11-12T03:01:00Z" }),
    // --- 면접 연습(F-009): 930 카드 832(역량 2개) · 834(질문 없음) 매칭 / 931 분석 전 ---
    mockApplication(930, "면접회사", "개발자", {
      extracted_at: "2026-11-12T03:00:00Z", matched_at: "2026-11-12T03:01:00Z",
      requirements: [
        appRequirement(9301, "React 화면 개발", "required", POSTING_A, "React로 화면을 만든 경험", [interviewMatch(1, 832), interviewMatch(2, 834)]),
        appRequirement(9302, "클라우드 배포", "preferred", POSTING_A, "클라우드 배포 경험", [interviewMatch(3, 832)]),
      ],
    }),
    mockApplication(931, "분석전면접회사", "개발자"),
    // 932 분석 끝 · 매칭 카드 없음 / 933 질문 없는 카드만 매칭 / 934 탭 500 / 935 느린 메모 카드 836
    mockApplication(932, "매칭없는면접회사", "개발자", { extracted_at: "2026-11-12T03:00:00Z", matched_at: "2026-11-12T03:01:00Z" }),
    mockApplication(933, "질문없는면접회사", "개발자", {
      extracted_at: "2026-11-12T03:00:00Z", matched_at: "2026-11-12T03:01:00Z",
      requirements: [appRequirement(9331, "React 화면 개발", "required", POSTING_A, "React로 화면을 만든 경험", [interviewMatch(4, 834)])],
    }),
    mockApplication(934, "탭실패면접회사", "개발자", { extracted_at: "2026-11-12T03:00:00Z", matched_at: "2026-11-12T03:01:00Z" }),
    mockApplication(935, "느린메모면접회사", "개발자", {
      extracted_at: "2026-11-12T03:00:00Z", matched_at: "2026-11-12T03:01:00Z",
      requirements: [appRequirement(9351, "React 화면 개발", "required", POSTING_A, "React로 화면을 만든 경험", [interviewMatch(5, 836)])],
    }),
  ].map((item) => [item.id, item]),
);

// --- 자소서 초안(F-008) 가짜 데이터: 문항 번호(공고 번호 × 10) → 초안 ---
const EVIDENCE_801 = {
  card_id: 801, card_title: "useEffect로 구독 정리", note_title: "React 정리", slot: "situation",
  quote: "useEffect는 그려진 뒤 부수 효과를 실행해요.", quote_source: "quote", added_by: "ai",
};
const draftSentence = (id, position, text, evidence, claimCheck = null) => ({
  id, position, text, origin: "ai", original_text: text, evidence_status: evidence ? "ok" : "none", evidence,
  claim_check: claimCheck, // '확인 필요'(D-028) — 서버는 읽을 때 규칙으로 계산한다. 가짜는 처음 값을 들고 다닌다
  needs_check: false, // withCounts가 채운다
});
// 가짜 서버의 '확인 필요' — 진짜 서버(draft_evidence.SentenceClaims.needs_check: 근거가 ok이고 규칙에 걸렸고 지금 이유를
// 확인하지 않음)와 같은 뜻. 서버 규칙이 바뀌면 backend tests/test_drafts.py의 test_needs_check_is_decided_by_the_server와
// 대조해 같이 고친다(9차 리뷰 R1).
const needsCheck = (item) => item.evidence_status === "ok" && item.claim_check !== null && !item.claim_check.confirmed;
const withCounts = (draft) => {
  const text = draft.sentences.map((item) => item.text).join(" ");
  const changed = draft.sentences.filter((item) => item.origin !== "ai").length;
  const sentences = draft.sentences.map((item) => ({ ...item, needs_check: needsCheck(item) }));
  return {
    ...draft, sentences, chars: Array.from(text).length, sentence_count: draft.sentences.length,
    unsupported_count: draft.sentences.filter((item) => item.evidence_status !== "ok").length,
    needs_check_count: draft.sentences.filter(needsCheck).length,
    edited_percent: draft.sentences.length ? Math.round((changed / draft.sentences.length) * 100) : 0,
  };
};
const mockDraft = (applicationId, sentences) => withCounts({
  id: applicationId, question_id: applicationId * 10, version: 1, completed_at: null, updated_at: "2026-11-14T06:24:00Z",
  char_limit: 700, sentences,
});
const MOCK_DRAFTS = new Map(
  [910, 914, 915, 916, 917, 918, 920].map((id) => [
    id * 10,
    mockDraft(id, [
      draftSentence(id * 100 + 1, 0, "React 화면에서 구독을 정리하는 일을 맡았습니다.", EVIDENCE_801),
      draftSentence(id * 100 + 2, 1, "그 결과 페이지 이탈률이 30% 줄었습니다.", null),
      draftSentence(id * 100 + 3, 2, "이 경험을 살려 팀에 기여하겠습니다.", EVIDENCE_801),
    ]),
  ]),
);
// 924: 상세에 needs_check_sentence_count가 없는 서버(배포가 어긋남) — 제출 확인창 앞에서 오류 문구(7차 리뷰 R3)
MOCK_DRAFTS.set(9240, mockDraft(924, [draftSentence(92401, 0, "React 화면에서 구독을 정리하는 일을 맡았습니다.", EVIDENCE_801)]));
// 925: claim_check 모양이 틀린 초안 — 자소서를 불러오지 못했다는 오류(7차 리뷰 R3)
MOCK_DRAFTS.set(9250, mockDraft(925, [
  draftSentence(92501, 0, "React 화면에서 구독을 정리하는 일을 맡았습니다.", EVIDENCE_801, { reasons: ["weird"], unknown_tokens: [], confirmed: false }),
]));
// 923: 근거는 있지만 카드에 없는 숫자 · 성과를 덧붙인 문장(D-028 '확인 필요')
// 926: [확인함] 첫 요청이 409(다른 탭이 먼저 바꿈) · 927: [확인함]이 404(문장이 사라짐) — 실패 경로(8차 리뷰 R3)
const CONFIRM_CONFLICT_APP = 926;
const CONFIRM_GONE_APP = 927;
const confirmConflicted = new Set();
for (const id of [923, CONFIRM_CONFLICT_APP, CONFIRM_GONE_APP]) {
  MOCK_DRAFTS.set(id * 10, mockDraft(id, [
    draftSentence(id * 100 + 1, 0, "React 화면에서 구독을 정리하는 일을 맡았습니다.", EVIDENCE_801),
    draftSentence(id * 100 + 2, 1, "구독을 정리해 메모리 사용량을 40% 줄였습니다.", EVIDENCE_801, {
      reasons: ["unknown_token", "result_without_record"], unknown_tokens: ["40"], confirmed: false,
    }),
  ]));
}
let nextSentenceId = 990_000;
const draftsCalls = new Map(); // 921: 공고별 자소서 목록 요청 수(첫 번째만 성공)
const countOf = (item, key) => item.questions.reduce((sum, question) => sum + (MOCK_DRAFTS.get(question.id)?.[key] ?? 0), 0);
const draftsView = (item) => ({
  application_id: item.id, analysis_done: item.matched_at !== null,
  matched_card_ids: [...new Set(item.requirements.flatMap((requirement) => requirement.matches.map((m) => m.card_id)))],
  checked_at: "2026-11-14T06:22:00Z",
  questions: item.questions.map((question) => ({ ...question, draft: MOCK_DRAFTS.get(question.id) ?? null })),
});

// 공고 분석이 끝난 자소서 공고의 역량(카드 801과 매칭)
function interviewMatch(id, cardId) {
  return { id, card_id: cardId, card_title: "카드", slot: "situation", quote: "상태를 바꾸면", quote_source: "quote", quote_start: 0, quote_end: 6, reason: "이유" };
}

// [면접 연습] 탭 응답(서버 get_application_interview와 같은 모양): 매칭된 저장 카드마다 한 번, 역량 이름은 태그
const interviewView = (item) => {
  const order = [...new Set(item.requirements.flatMap((requirement) => requirement.matches.map((match) => match.card_id)))];
  const cards = order
    .map((id) => MOCK_CARDS.get(id))
    .filter((card) => card && card.status === "saved")
    .map((card) => ({
      card_id: card.id, card_title: card.title, note_title: card.note_title,
      requirement_names: item.requirements.filter((r) => r.matches.some((m) => m.card_id === card.id)).map((r) => r.name),
      has_questions: (card.interview ?? []).length > 0,
      questions: card.interview ?? [],
    }));
  const questions = cards.flatMap((card) => card.questions);
  return {
    application_id: item.id, analysis_done: item.matched_at !== null, question_count: questions.length,
    answered_count: questions.filter((question) => question.answered_at !== null).length, cards,
  };
};

function matchedRequirements(id) {
  return [
    appRequirement(id * 10 + 1, "React 화면 개발", "required", POSTING_A, "React로 화면을 만든 경험", [
      { id: id * 10 + 1, card_id: 801, card_title: "useEffect로 구독 정리", slot: "situation", quote: "useEffect는 그려진 뒤 부수 효과를 실행해요.",
        quote_source: "quote", quote_start: 0, quote_end: 27, reason: "React 훅으로 화면을 다룬 경험이에요." },
    ]),
  ];
}

/** 자소서 API(F-008). 처리했으면 true. */
function handleDrafts(req, res, url, body) {
  // [확인함] · [확인 풀기](D-028): 문장 번호 · 완료 표시 그대로, version만 올림. 걸리지 않은 문장은 저장할 것이 없음
  const confirmMatch = req.method === "PATCH" ? url.pathname.match(/^\/api\/drafts\/(\d+)\/sentences\/(\d+)$/) : null;
  if (confirmMatch) {
    const draft = [...MOCK_DRAFTS.values()].find((item) => item.id === Number(confirmMatch[1]));
    const target = draft?.sentences.find((item) => item.id === Number(confirmMatch[2]));
    if (!draft || !target || draft.question_id === CONFIRM_GONE_APP * 10) {
      sendJson(res, 404, { detail: "문장을 찾을 수 없어요. 다른 곳에서 초안이 바뀌었을 수 있어요. 새로고침한 뒤 다시 시도해 주세요." });
      return true;
    }
    if (draft.question_id === CONFIRM_CONFLICT_APP * 10 && !confirmConflicted.has(draft.id)) {
      confirmConflicted.add(draft.id); // 다른 탭이 첫 문장을 먼저 고친 것처럼 바꾸고 409 — 화면이 새로 받은 걸 테스트가 볼 수 있게
      const [first, ...rest] = draft.sentences;
      MOCK_DRAFTS.set(draft.question_id, withCounts({
        ...draft, version: draft.version + 1, sentences: [{ ...first, text: "다른 탭에서 고친 문장입니다.", origin: "edited" }, ...rest],
      }));
      sendJson(res, 409, { detail: "다른 곳에서 이 초안이 먼저 바뀌었어요. 새로고침한 뒤 다시 고쳐 주세요." });
      return true;
    }
    if (body.version !== draft.version) {
      sendJson(res, 409, { detail: "다른 곳에서 이 초안이 먼저 바뀌었어요. 새로고침한 뒤 다시 고쳐 주세요." });
      return true;
    }
    const sentences = draft.sentences.map((item) =>
      item.id === target.id && item.claim_check ? { ...item, claim_check: { ...item.claim_check, confirmed: Boolean(body.confirmed) } } : item,
    );
    const saved = withCounts({ ...draft, sentences, version: draft.version + 1, updated_at: "2026-11-14T06:32:00Z" });
    MOCK_DRAFTS.set(draft.question_id, saved);
    sendJson(res, 200, saved);
    return true;
  }

  const draftMatch = url.pathname.match(/^\/api\/drafts\/(\d+)$/);
  if (draftMatch) {
    const draft = [...MOCK_DRAFTS.values()].find((item) => item.id === Number(draftMatch[1]));
    if (!draft) {
      sendJson(res, 404, { detail: "초안을 찾을 수 없어요." });
      return true;
    }
    if (req.method === "PATCH" && draft.question_id === 9200) {
      res.writeHead(500, { "Content-Type": "text/plain" });
      res.end("Internal Server Error");
      return true;
    }
    if (req.method === "PATCH") {
      const saved = { ...draft, completed_at: body.completed ? "2026-11-14T06:30:00Z" : null };
      MOCK_DRAFTS.set(draft.question_id, saved);
      sendJson(res, 200, saved);
      return true;
    }
    if (req.method === "PUT") {
      // 918용: 글에 "[422]"가 있으면 입력 오류, "[409]"가 있으면 다른 탭이 먼저 저장한 것처럼 바꾸고 409
      const texts = (body.sentences ?? []).map((edit) => String(edit.text ?? ""));
      if (texts.some((text) => text.includes("[422]"))) {
        sendJson(res, 422, { detail: "문장 하나는 500자까지 쓸 수 있어요." });
        return true;
      }
      if (texts.some((text) => text.includes("[409]"))) {
        const [first, ...rest] = draft.sentences;
        MOCK_DRAFTS.set(draft.question_id, withCounts({
          ...draft, version: draft.version + 1,
          sentences: [{ ...first, id: nextSentenceId++, text: "다른 탭에서 고친 문장입니다.", origin: "edited" }, ...rest],
        }));
        sendJson(res, 409, { detail: "다른 곳에서 이 초안이 먼저 바뀌었어요. 새로고침한 뒤 다시 고쳐 주세요." });
        return true;
      }
      if (body.version !== draft.version) {
        sendJson(res, 409, { detail: "다른 곳에서 이 초안이 먼저 바뀌었어요. 새로고침한 뒤 다시 고쳐 주세요." });
        return true;
      }
      const sentences = (body.sentences ?? []).map((edit, position) => {
        const old = draft.sentences.find((item) => item.id === edit.id);
        const text = String(edit.text ?? "").trim();
        let sentence = old
          ? { ...old, id: nextSentenceId++, position, text, origin: old.origin === "user" ? "user" : text === old.original_text ? "ai" : "edited" }
          : { id: nextSentenceId++, position, text, origin: "user", original_text: null, evidence_status: "none", evidence: null, claim_check: null };
        // [확인함]은 글 · 근거가 그대로인 문장에만 옮겨 온다(서버 update_draft와 같은 규칙). 가짜는 고쳐도 걸린 채로 둔다
        if (sentence.claim_check) {
          const unchanged = old && text === old.text && !edit.unlink && !edit.link;
          sentence = { ...sentence, claim_check: { ...sentence.claim_check, confirmed: Boolean(unchanged && old.claim_check?.confirmed) } };
        }
        if (edit.unlink) sentence = { ...sentence, evidence_status: "none", evidence: null, claim_check: null };
        if (edit.link) {
          const card = MOCK_CARDS.get(edit.link.card_id);
          const field = card?.fields.find((item) => item.slot === edit.link.slot);
          const quote = field?.[edit.link.quote_source];
          if (!card || card.status !== "saved" || !quote) return null;
          sentence = {
            ...sentence, evidence_status: "ok",
            evidence: { card_id: card.id, card_title: card.title, note_title: card.note_title, slot: field.slot, quote, quote_source: edit.link.quote_source, added_by: "user" },
          };
        }
        return sentence;
      });
      if (sentences.some((item) => item === null)) {
        sendJson(res, 422, { detail: "근거로 고른 카드를 찾을 수 없어요. 저장한 내 카드만 연결할 수 있어요." });
        return true;
      }
      const saved = withCounts({ ...draft, sentences, version: draft.version + 1, completed_at: null, updated_at: "2026-11-14T06:31:00Z" });
      MOCK_DRAFTS.set(draft.question_id, saved);
      sendJson(res, 200, saved);
      return true;
    }
    return false;
  }

  const interviewTab = req.method === "GET" ? url.pathname.match(/^\/api\/applications\/(\d+)\/interview$/) : null;
  if (interviewTab) {
    const target = MOCK_APPLICATIONS.get(Number(interviewTab[1]));
    if (target?.id === 934) sendJson(res, 500, { detail: "서버 오류" });
    else if (target) sendJson(res, 200, interviewView(target));
    else sendJson(res, 404, { detail: "공고를 찾을 수 없어요." });
    return true;
  }

  const appMatch = url.pathname.match(/^\/api\/applications\/(\d+)\/(drafts|questions|questions\/(\d+)\/draft)$/);
  if (!appMatch) return false;
  const item = MOCK_APPLICATIONS.get(Number(appMatch[1]));
  if (!item) {
    sendJson(res, 404, { detail: "공고를 찾을 수 없어요." });
    return true;
  }
  if (appMatch[2] === "drafts" && req.method === "GET") {
    const calls = (draftsCalls.get(item.id) ?? 0) + 1;
    draftsCalls.set(item.id, calls);
    if (item.id === 919 || (item.id === 921 && calls > 1)) {
      sendJson(res, 500, { detail: "서버 오류" });
      return true;
    }
    sendJson(res, 200, draftsView(item));
    return true;
  }
  if (appMatch[2] === "questions" && req.method === "PUT") {
    if ((body.questions ?? []).some((edit) => String(edit.text ?? "").includes("[422]"))) {
      sendJson(res, 422, { detail: "자소서 문항은 500자까지 쓸 수 있어요." });
      return true;
    }
    if ((body.questions ?? []).some((edit) => String(edit.text ?? "").includes("[409]"))) {
      // 922: 다른 탭이 문항을 먼저 넣은 것처럼 바꾸고 409
      item.questions = [...item.questions, { id: item.id * 10 + 99, position: item.questions.length, text: "다른 탭에서 넣은 문항", char_limit: null }];
      sendJson(res, 409, { detail: "다른 곳에서 문항이 먼저 바뀌었어요. 새로 불러온 목록을 확인하고 다시 고쳐 주세요." });
      return true;
    }
    const given = new Set((body.questions ?? []).map((edit) => edit.id).filter((id) => id != null));
    const removed = new Set(body.removed_ids ?? []);
    if (item.questions.some((question) => !given.has(question.id) && !removed.has(question.id))) {
      sendJson(res, 409, { detail: "다른 곳에서 문항이 먼저 바뀌었어요. 새로 불러온 목록을 확인하고 다시 고쳐 주세요." });
      return true;
    }
    const next = (body.questions ?? []).map((edit, position) => ({
      id: edit.id ?? item.id * 10 + 100 + position, position, text: String(edit.text ?? "").trim(), char_limit: edit.char_limit ?? null,
    }));
    if (next.some((question) => !question.text)) {
      sendJson(res, 422, { detail: "빈 문항이 있어요. 문항을 적거나 지워 주세요." });
      return true;
    }
    for (const question of item.questions) if (!next.some((other) => other.id === question.id)) MOCK_DRAFTS.delete(question.id);
    item.questions = next;
    sendJson(res, 200, draftsView(item));
    return true;
  }
  if (appMatch[3] && req.method === "POST") {
    const questionId = Number(appMatch[3]);
    if (item.id === 921) {
      sendJson(res, 404, { detail: "자소서 문항을 찾을 수 없어요." });
      return true;
    }
    if (item.id === 913) {
      sendJson(res, 503, { detail: "지금은 AI에 연결할 수 없어요. 잠시 뒤 다시 시도해 주세요." });
      return true;
    }
    if (MOCK_DRAFTS.has(questionId) && !body.overwrite) {
      sendJson(res, 409, { detail: "이 문항에는 이미 초안이 있어요. 다시 쓰면 지금 초안을 덮어써요." });
      return true;
    }
    // 1.5초 걸림 — 쓰는 중 화면 확인용
    setTimeout(() => {
      MOCK_DRAFTS.set(questionId, mockDraft(item.id, [
        draftSentence(nextSentenceId++, 0, "useEffect로 구독을 정리한 경험이 있습니다.", EVIDENCE_801),
        draftSentence(nextSentenceId++, 1, "팀의 배포 속도를 두 배로 올렸습니다.", null),
      ]));
      sendJson(res, 201, { question_id: questionId, written: true, sentences: 2, supported: 1, cards_sent: 1, drop_reasons: { quote_not_found: 1 }, remaining_today: 28 });
    }, 1500);
    return true;
  }
  sendJson(res, 405, { detail: "Method Not Allowed" });
  return true;
}
let nextApplicationId = 950;
const appSummary = (item) => ({
  id: item.id, company: item.company, role: item.role, deadline: item.deadline, days_left: item.days_left,
  status: item.status, url: item.url, requirement_count: item.requirements.length,
  matched_requirement_count: item.requirements.filter((requirement) => requirement.matches.length > 0).length,
  extracted: item.extracted_at !== null, matched: item.matched_at !== null, created_at: item.created_at, updated_at: item.updated_at,
});
const dDayOrder = (item) => (item.days_left === null ? [2, 0] : item.days_left < 0 ? [1, -item.days_left] : [0, item.days_left]);

function handleApplications(req, res, url, rawBody) {
  let body = {};
  try {
    body = rawBody ? JSON.parse(rawBody) : {};
  } catch {
    body = {};
  }
  if (handleDrafts(req, res, url, body)) return;
  if (req.method === "GET" && url.pathname === "/api/applications") {
    const list = [...MOCK_APPLICATIONS.values()].sort((a, b) => {
      const [ga, va] = dDayOrder(a);
      const [gb, vb] = dDayOrder(b);
      return ga - gb || va - vb;
    });
    sendJson(res, 200, { total: list.length, applications: list.map(appSummary) });
    return;
  }
  if (req.method === "POST" && url.pathname === "/api/applications") {
    if (!String(body.company ?? "").trim()) {
      sendJson(res, 422, { detail: "회사 이름을(를) 적어 주세요." });
      return;
    }
    const id = nextApplicationId++;
    const item = mockApplication(id, body.company.trim(), String(body.role ?? "").trim(), {
      posting_text: String(body.posting_text ?? "").trim() || POSTING_A, url: body.url ?? null, deadline: body.deadline ?? null,
    });
    MOCK_APPLICATIONS.set(id, item);
    sendJson(res, 201, item);
    return;
  }
  const match = url.pathname.match(/^\/api\/applications\/(\d+)(\/requirements|\/matches)?$/);
  const item = match ? MOCK_APPLICATIONS.get(Number(match[1])) : undefined;
  if (!item) {
    sendJson(res, 404, { detail: "공고를 찾을 수 없어요." });
    return;
  }
  const action = match[2];
  if (!action && req.method === "GET") {
    const detail = {
      ...item,
      unsupported_sentence_count: countOf(item, "unsupported_count"),
      needs_check_sentence_count: countOf(item, "needs_check_count"),
    };
    if (item.id === 924) delete detail.needs_check_sentence_count; // 배포가 어긋난 서버 흉내
    sendJson(res, 200, detail);
    return;
  }
  if (!action && (req.method === "PATCH" || req.method === "DELETE") && item.id === 907) {
    res.writeHead(500, { "Content-Type": "text/plain" });
    res.end("Internal Server Error");
    return;
  }
  if (!action && req.method === "PATCH") {
    if (body.status) item.status = body.status;
    sendJson(res, 200, item);
    return;
  }
  if (!action && req.method === "DELETE") {
    MOCK_APPLICATIONS.delete(item.id);
    res.writeHead(204);
    res.end();
    return;
  }
  if (action === "/requirements" && req.method === "POST") {
    if (item.id === 906) {
      sendJson(res, 201, { application_id: 906, requirement_count: 2, drop_reasons: {}, remaining_today: 29 });
      return;
    }
    if (item.id === 904) {
      sendJson(res, 429, { detail: "오늘 AI 사용량(30회)을 다 썼어요. 한국 시간 0시에 다시 쓸 수 있어요." });
      return;
    }
    const posting = item.posting_text;
    const lines = posting.split("\n").map((line) => line.replace(/^-\s*/, "").trim()).filter((line) => line.length >= 4).slice(1, 3);
    item.requirements = lines.map((line, index) => ({ ...appRequirement(item.id * 10 + index, line.slice(0, 12), "required", posting, line), position: index }));
    item.extracted_at = "2026-11-12T04:00:00Z";
    sendJson(res, 201, { application_id: item.id, requirement_count: item.requirements.length, drop_reasons: {}, remaining_today: 29 });
    return;
  }
  if (action === "/matches" && req.method === "POST") {
    if (item.id === 906) {
      setTimeout(() => sendJson(res, 201, { application_id: 906, matches: 0, matched_requirements: 0, requirements_sent: 0, cards_sent: 0, drop_reasons: {}, remaining_today: 29 }), 3000);
      return;
    }
    if (item.id === 903) {
      sendJson(res, 503, { detail: "지금은 AI에 연결할 수 없어요. 잠시 뒤 다시 시도해 주세요." });
      return;
    }
    item.requirements = item.requirements.map((requirement, index) => ({
      ...requirement,
      matches: index === 0
        ? [{ id: requirement.id, card_id: 801, card_title: "useEffect로 구독 정리", slot: "action", quote: "상태를 바꾸면 다시 그려져요.",
             quote_source: "quote", quote_start: 0, quote_end: 16, reason: "화면 상태를 다룬 경험이에요." }]
        : [],
    }));
    item.matched_at = "2026-11-12T04:01:00Z";
    sendJson(res, 201, { application_id: item.id, matches: 1, matched_requirements: 1, requirements_sent: 1, cards_sent: 1, drop_reasons: {}, remaining_today: 28 });
    return;
  }
  sendJson(res, 405, { detail: "Method Not Allowed" });
}

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
  // --- 면접 연습(F-009): 질문 만들기 · 메모 ---
  const makeMatch = req.method === "POST" ? url.pathname.match(/^\/api\/cards\/(\d+)\/interview-questions$/) : null;
  const memoMatch = req.method === "PATCH" ? url.pathname.match(/^\/api\/interview-questions\/(\d+)$/) : null;
  if (makeMatch || memoMatch) {
    if (!isLoggedIn(req)) {
      sendJson(res, 401, { detail: "로그인이 필요해요." });
      return;
    }
  }
  if (makeMatch) {
    const card = MOCK_CARDS.get(Number(makeMatch[1]));
    if (!card) {
      sendJson(res, 404, { detail: "카드를 찾을 수 없어요." });
    } else if (card.status !== "saved") {
      sendJson(res, 409, { detail: "저장한 카드에서만 면접 질문을 만들 수 있어요. 카드를 먼저 저장해 주세요." });
    } else if ((card.interview ?? []).length > 0) {
      sendJson(res, 409, { detail: "이 카드에는 이미 면접 질문이 있어요." });
    } else if (card.id === 833) {
      sendJson(res, 503, { detail: "AI 서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요." });
    } else if (card.id === 837 || card.id === 838) {
      card.interview = [interviewQuestion(card.id * 10 + 1, card.id, 0, "situation", "다른 탭에서 만든 질문인가요?", "useEffect는 그려진 뒤")];
      sendJson(res, 409, { detail: "이 카드에는 이미 면접 질문이 있어요." });
    } else {
      card.interview = [
        interviewQuestion(card.id * 10 + 1, card.id, 0, "situation", "그때 가장 먼저 확인한 것은 무엇인가요?", "useEffect는 그려진 뒤"),
        interviewQuestion(card.id * 10 + 2, card.id, 1, "action", "그 방법을 고른 이유는 무엇인가요?", "상태를 바꾸면"),
      ];
      sendJson(res, 201, { card_id: card.id, written: true, questions: 2, received: 3, fields_sent: 2, drop_reasons: { quote_not_found: 1 }, remaining_today: 28 });
    }
    return;
  }
  if (memoMatch) {
    const questionId = Number(memoMatch[1]);
    const owner = [...MOCK_CARDS.values()].find((card) => (card.interview ?? []).some((q) => q.id === questionId));
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      if (!owner) {
        sendJson(res, 404, { detail: "면접 질문을 찾을 수 없어요." });
        return;
      }
      if (questionId === 8323) {
        sendJson(res, 500, { detail: "메모를 저장하지 못했어요." });
        return;
      }
      const memo = String(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}").memo ?? "").trim() || null;
      owner.interview = owner.interview.map((q) =>
        q.id === questionId ? { ...q, memo, answered_at: memo ? "2026-11-15T04:00:00Z" : null, updated_at: "2026-11-15T04:00:00Z" } : q,
      );
      const saved = owner.interview.find((q) => q.id === questionId);
      setTimeout(() => sendJson(res, 200, saved), questionId === 8361 ? 1500 : 0);
    });
    return;
  }

  const cardMatch = url.pathname.match(/^\/api\/cards\/(\d+)(\/save|\/fields\/(\w+))?$/);
  if (cardMatch) {
    const card = MOCK_CARDS.get(Number(cardMatch[1]));
    if (!card) {
      sendJson(res, 404, { detail: "카드를 찾을 수 없어요." });
      return;
    }
    if (req.method === "GET" && !cardMatch[2] && (card.id === 835 || card.id === 838) && (card.interview ?? []).length > 0) {
      sendJson(res, 500, { detail: "카드를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요." });
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

  // --- 노션 연결(F-005) ---
  // 상황은 세션 토큰 뒤에 붙인 이름으로 고른다(서버 컴포넌트는 세션 쿠키만 넘기므로): 기본 = 연결됨,
  // "<토큰>-notion-none" 연결 안 됨 · "-notion-broken" 끊김 · "-notion-midbreak" 가져오는 중 끊김 ·
  // "-notion-empty" 공유 페이지 없음 · "-notion-many" 25개 + 100개 넘음(truncated) · "-notion-flaky" 목록 첫 요청 500 ·
  // "-notion-disconnectfail" 끊기 500 · "-notion-importfail" 가져오기 502
  // --- 지원 · 공고 분석(F-007) ---
  // 901: 분석 · 매칭 끝(역량 2개 — 하나는 카드 801, 하나는 근거 없음) / 902: 분석 전 → 뽑기 · 매칭 성공
  // 903: 분석 전 → 뽑기 성공, 매칭 503(뽑은 역량은 남음) / 904: 뽑기 429 / 905: 지울 공고 / 906: ① 직후(상세 늦음 · 매칭 3초) / 907: 상태 · 지우기 500 / 950~: [공고 추가]로 만든 공고(902처럼)
  // 면접 연습(F-009): 930 카드 832(질문 3 · 역량 2) · 834(질문 없음) 매칭 · 931 분석 전 · 932 매칭 없음 · 933 질문 없는 카드만 ·
  // 934 탭 500 · 935 느린 메모 — 카드 831 만들기 성공 · 833 만들기 503 · 835 만든 뒤 다시 받기 500
  // 자소서(F-008): 910 초안 있음 · 911 [초안 쓰기] 1.5초 · 912 매칭 카드 없음 · 913 쓰기 503 · 914 제출 확인 · 915 고치기 · 916 카드 연결 · 917 문항 고치기 · 918 저장 409 · 422 · 919 목록 500 · 920 완료 500 · 921 쓰기 404 뒤 다시 받기 500 · 922 문항 409 · 422 · 923 확인 필요(D-028) · 924 상세 개수 모양 틀림 · 925 claim_check 모양 틀림 · 926 [확인함] 409 한 번 · 927 [확인함] 404
  if (url.pathname === "/api/applications" || url.pathname.startsWith("/api/applications/") || url.pathname.startsWith("/api/drafts/")) {
    if (!isLoggedIn(req)) {
      sendJson(res, 401, { detail: "로그인이 필요해요." });
      return;
    }
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => handleApplications(req, res, url, Buffer.concat(chunks).toString("utf8")));
    return;
  }

  if (url.pathname.startsWith("/api/notion/")) {
    if (!isLoggedIn(req)) {
      sendJson(res, 401, { detail: "로그인이 필요해요." });
      return;
    }
    const cookie = req.headers.cookie ?? "";
    const notionCase = cookie.match(/-notion-([a-z]+)/)?.[1] ?? "connected";
    const status = notionCase === "none" || notionCase === "broken" ? notionCase : "connected";
    const pages =
      notionCase === "empty"
        ? []
        : notionCase === "many"
          ? Array.from({ length: 25 }, (_, index) => ({
              id: `000000${String(index).padStart(2, "0")}-0000-4000-8000-0000000000${String(index).padStart(2, "0")}`,
              title: `페이지 ${index + 1}`,
              last_edited_time: "2026-11-10T09:00:00.000Z",
              imported_note_id: null,
            }))
          : [
              { id: NOTION_PAGE_A, title: "트랜잭션 공부", last_edited_time: "2026-11-10T09:00:00.000Z", imported_note_id: null },
              { id: NOTION_PAGE_B, title: "네트워크 정리", last_edited_time: "2026-11-09T09:00:00.000Z", imported_note_id: null },
              { id: NOTION_PAGE_C, title: "이미 가져온 페이지", last_edited_time: "2026-11-08T09:00:00.000Z", imported_note_id: 5 },
            ];
    if (req.method === "GET" && url.pathname === "/api/notion/status") {
      sendJson(res, 200, { configured: true, status, workspace_name: status === "none" ? null : "디딤 워크스페이스" });
      return;
    }
    if (req.method === "DELETE" && url.pathname === "/api/notion/connection") {
      if (notionCase === "disconnectfail") {
        // 실제 FastAPI처럼 처리 못 한 오류의 500은 JSON이 아닌 글자 — 화면은 기본 문구를 보여 준다
        res.writeHead(500, { "Content-Type": "text/plain" });
        res.end("Internal Server Error");
        return;
      }
      res.writeHead(204);
      res.end();
      return;
    }
    if (status !== "connected") {
      const detail =
        status === "none"
          ? "노션이 연결되어 있지 않아요. 설정에서 연결해 주세요."
          : "노션 연결이 끊겼어요. 설정에서 다시 연결해 주세요."
      sendJson(res, 409, { detail });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/notion/pages") {
      // flaky: 같은 세션의 첫 요청만 실패 → [다시 불러오기]로 받아진다
      if (notionCase === "flaky" && !notionFlakySeen.has(cookie)) {
        notionFlakySeen.add(cookie);
        sendJson(res, 502, { detail: "노션이 잠시 응답하지 않아요. 잠시 후 다시 시도해 주세요." });
        return;
      }
      sendJson(res, 200, { pages, truncated: notionCase === "many" });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/notion/import") {
      if (notionCase === "importfail") {
        sendJson(res, 502, { detail: "노션이 잠시 응답하지 않아요. 잠시 후 다시 시도해 주세요." });
        return;
      }
      const chunks = [];
      req.on("data", (chunk) => chunks.push(chunk));
      req.on("end", () => {
        const { page_ids: pageIds = [] } = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
        const picked = pages.filter((page) => pageIds.includes(page.id));
        const ok = notionCase === "midbreak" ? picked.slice(0, 1) : picked;
        const rest = notionCase === "midbreak" ? picked.slice(1) : [];
        sendJson(res, 200, {
          summary: { notes: ok.length, chunks: ok.length * 3, duplicates: 0, failed: rest.length, skipped_blocks: 2 },
          imported: ok.map((page, index) => ({
            page_id: page.id, note_id: 100 + index, title: page.title, chunk_count: 3, skipped_blocks: 2,
          })),
          duplicates: [],
          failed: rest.map((page) => ({
            page_id: page.id, title: null, reason: "노션 연결이 끊겨서 가져오지 못했어요. 설정에서 다시 연결해 주세요.",
          })),
          connection_broken: notionCase === "midbreak",
        });
      });
      return;
    }
  }

  // 홈(F-012): 토큰 꼬리표로 경우를 나눈다 — 정상 = 다 갖춘 사용자, -home-empty = 처음 온 사람, -home-partial = 기록만, -home-error = 실패, -home-bad = 200인데 모양이 틀림
  if (req.method === "GET" && req.url === "/api/home") {
    const cookie = req.headers.cookie ?? "";
    if (!isLoggedIn(req)) {
      res.writeHead(401, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "로그인이 필요해요." }));
      return;
    }
    if (cookie.includes("-home-error")) {
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "실패" }));
      return;
    }
    const zero = { notes: 0, reviews_today: 0, cards: 0, applications: 0, drafted_applications: 0 };
    let body;
    if (cookie.includes("-home-empty")) body = { steps: zero, deadline_days: 7, deadlines: [], blank_cards: [] };
    else if (cookie.includes("-home-partial")) body = { steps: { ...zero, notes: 2 }, deadline_days: 7, deadlines: [], blank_cards: [] };
    else if (cookie.includes("-home-bad")) {
      body = {
        steps: zero, deadline_days: 7, blank_cards: [],
        deadlines: [{ id: 904, company: "지난마감", role: "백엔드", deadline: "2026-11-17", days_left: -1, status: "ready" }],
      };
    } else {
      body = {
        deadline_days: 7,
        steps: { notes: 12, reviews_today: 4, cards: 7, applications: 3, drafted_applications: 2 },
        deadlines: [
          { id: 902, company: "스텝랩", role: "백엔드", deadline: "2026-11-20", days_left: 2, status: "writing" },
          { id: 903, company: "바구니마켓", role: "Java 백엔드", deadline: "2026-11-24", days_left: 6, status: "ready" },
        ],
        blank_cards: [{ id: 801, title: "로그인이 30분마다 풀리던 버그", blank_slots: ["task", "result"] }],
      };
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
    return;
  }

  // 평가 리포트(F-010) · 랜딩 수치(F-011): 로그인 없이. 회차 두 개 — 최근 회차에는 판정 대기 · 실패 칸이 있다
  if (req.method === "GET" && req.url === "/api/report") {
    // display는 서버(eval_report.format_value)가 만든 글자 — 화면은 이것을 그대로 보인다
    const metric = (key, label, kind, value, display) => ({ key, label, kind, value, display });
    const run = (runId, model, quizDrop, pending) => ({
      run_id: runId, started_at: `${runId.slice(0, 4)}-${runId.slice(4, 6)}-${runId.slice(6, 8)}T10:00:00+09:00`,
      finished_at: null, provider: "nvidia", model, commit: "abc1234",
      data: { experiences: 20, postings: 10, draft_questions: 20 },
      data_items: [
        { key: "experiences", label: "심은 경험", count: 20, display: "심은 경험 20개" },
        { key: "postings", label: "공고", count: 10, display: "공고 10개" },
        { key: "draft_questions", label: "자소서 문항", count: 20, display: "자소서 문항 20개" },
      ],
      evals: [
        { key: "quiz", title: "퀴즈", status: "ok", error: null, model, labels_pending: 0,
          metrics: [metric("drop_rate", "버려진 문제 비율", "rate", quizDrop, `${(quizDrop * 100).toFixed(1)}%`)] },
        { key: "drafts_ai", title: "자소서 · AI 초안", status: "ok", error: null, model, labels_pending: pending,
          metrics: [metric("warn_rate", "지어낸 문장 경고율", "rate", pending ? null : 0.8, pending ? "판정 대기" : "80.0%"),
            metric("unsupported_per_draft", "초안당 근거 없는 문장", "per", 0.58, "0.58")] },
        { key: "cards", title: "경험 카드", status: runId.startsWith("20261117") ? "failed" : "ok", error: null, model,
          labels_pending: 0, metrics: runId.startsWith("20261117") ? [] : [metric("found_rate", "심은 경험 찾은 비율", "rate", 0.5, "50.0%")] },
        // 랜딩 첫 화면 수치(F-011)가 고르는 나머지 두 칸. 최근 회차는 공고 매칭을 돌리지 못함 — 랜딩은 그 칸을 뺀다
        { key: "postings", title: "공고 매칭", status: runId.startsWith("20261117") ? "failed" : "ok", error: null, model,
          labels_pending: 0, metrics: runId.startsWith("20261117") ? [] : [metric("false_matches", "없는 근거로 만든 매칭 수", "count", 5, "5개")] },
        { key: "interview_planted", title: "면접 · 심은 질문", status: "ok", error: null, model, labels_pending: 0,
          metrics: [metric("catch_rate", "심은 질문 잡은 비율", "rate", 0.75, "75.0%")] },
      ],
    });
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ runs: [run("20261117-090000", "ultra", 0.02, 3), run("20261116-090000", "exaone", 0.1, 0)] }));
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
          // 샘플 체험 세션(F-010, D-029): 정상 토큰 + "-sample" — 다른 가짜 응답은 로그인으로 그대로 본다
          is_sample: cookieHeader.includes(`didim_session=${VALID_TOKEN}-sample`),
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

  // 샘플 체험 열기(F-010): 샘플 세션 쿠키로 바꿔 끼운다
  if (req.method === "POST" && req.url === "/api/demo/session") {
    res.writeHead(204, { "Set-Cookie": `didim_session=${VALID_TOKEN}-sample; Path=/; HttpOnly; SameSite=Lax` });
    res.end();
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

// 고장 난 백엔드(F-011 · F-010 '리포트를 못 읽을 때 · 빈 회차'): 화면 서버가 백엔드를 직접 불러 page.route로는 못 가로채서,
// 같은 빌드의 두 번째 next start만 이쪽을 보게 한다(playwright.config.ts). 위 서버에 스위치를 두면 병렬로 도는 다른 테스트까지
// 바뀌어서 따로 띄운다. 이 서버는 tests/report-unavailable.spec.ts만 쓰고, 그 파일은 테스트를 차례로 돌린다(스위치를 같이 씀).
// 포트 기본값은 tests/helpers.ts 한 곳 — config가 넘겨 줄 때만 띄운다(따로 돌릴 때 값이 어긋나지 않게).
const FAILING_PORT = process.env.MOCK_BACKEND_FAILING_PORT;
// /api/report가 돌려줄 것: fail 500(기본) · empty 회차 0개 · not-json 200 + JSON 아닌 본문 · bad-run 200 + 회차에 칸이 빠짐
// · bad-metric 200 + 회차 · 평가는 맞는데 수치 값이 문자열
const BAD_METRIC_RUN = {
  run_id: "20261119-000000", started_at: null, finished_at: null, provider: null, model: null, commit: null,
  data: { experiences: 20 }, data_items: [{ key: "experiences", label: "심은 경험", count: 20, display: "심은 경험 20개" }],
  evals: [{ key: "interview_planted", title: "면접 · 심은 질문", status: "ok", error: null, model: null, labels_pending: 0,
    metrics: [{ key: "catch_rate", label: "심은 질문 잡은 비율", kind: "rate", value: "0.75", display: "75.0%" }] }],
};
const REPORT_MODES = {
  fail: { status: 500, type: "application/json", body: JSON.stringify({ detail: "mock backend failure" }) },
  empty: { status: 200, type: "application/json", body: JSON.stringify({ runs: [] }) },
  "not-json": { status: 200, type: "text/html", body: "<html>gateway page</html>" },
  "bad-run": { status: 200, type: "application/json", body: JSON.stringify({ runs: [{ run_id: "20261119-000000" }] }) },
  "bad-metric": { status: 200, type: "application/json", body: JSON.stringify({ runs: [BAD_METRIC_RUN] }) },
};
if (FAILING_PORT) {
  // 받은 /api/report 수 — 테스트가 '화면 서버가 정말 이 고장 난 백엔드를 봤는지' 확인한다(BACKEND_URL이 안 먹어 연결 실패로 통과하는 것을 막음)
  let reportRequests = 0;
  let reportMode = "fail";
  const sendJson = (res, status, body) => {
    res.writeHead(status, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
  };
  http
    .createServer((req, res) => {
      if (req.method === "GET" && req.url === "/api/health") return sendJson(res, 200, { status: "ok" });
      if (req.method === "GET" && req.url === "/__test/report-requests") return sendJson(res, 200, { count: reportRequests });
      const modeMatch = req.method === "POST" && req.url?.match(/^\/__test\/report-mode\/([a-z-]+)$/);
      if (modeMatch) {
        if (!(modeMatch[1] in REPORT_MODES)) return sendJson(res, 400, { detail: "unknown mode" });
        reportMode = modeMatch[1];
        return sendJson(res, 200, { mode: reportMode });
      }
      if (req.method === "GET" && req.url === "/api/report") {
        reportRequests += 1;
        const { status, type, body } = REPORT_MODES[reportMode];
        res.writeHead(status, { "Content-Type": type });
        res.end(body);
        return;
      }
      sendJson(res, 500, { detail: "mock backend failure" });
    })
    .listen(Number(FAILING_PORT), "127.0.0.1");
}
