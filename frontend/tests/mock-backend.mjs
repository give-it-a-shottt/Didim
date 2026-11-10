import http from "node:http";

const PORT = Number(process.env.MOCK_BACKEND_PORT ?? 8100);
const VALID_TOKEN = "playwright-valid-session-token";

const server = http.createServer((req, res) => {
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
