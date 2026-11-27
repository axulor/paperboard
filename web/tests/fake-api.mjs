// Stand-in for the PaperBoard API in the smoke tests. Usage: node tests/fake-api.mjs <port>
//
// The fixtures are real API responses; arXiv metadata is CC0.

import { readFileSync } from "node:fs";
import { createServer } from "node:http";

const fixture = (name) =>
  JSON.parse(
    readFileSync(new URL(`fixtures/${name}`, import.meta.url), "utf8"),
  );

const mixtral = fixture("paper-2401.04088.json");
const old = fixture("paper-hep-th-9901001.json");
// Same paper, marked withdrawn and without full text, as a third case.
const withdrawn = {
  ...mixtral,
  facts: { ...mixtral.facts, source_id: "2402.00001", withdrawn: true },
  code_links: [],
  full_text_url: null,
  full_text_format: null,
  full_text_problem: "withdrawn",
};

const papers = new Map([
  ["2401.04088", mixtral],
  ["hep-th/9901001", old],
  ["2402.00001", withdrawn],
]);

const notes = new Map([["2401.04088", fixture("notes-2401.04088.json")]]);
const NO_NOTES = { counts: {}, latest: [], total: 0 };

const moe = {
  id: 3,
  title: "Mixture of experts",
  created_at: "2026-11-27T08:00:00Z",
  paper_count: 2,
  papers_with_notes: 1,
  papers_checked: 1,
  open_question_count: 1,
  papers: [
    {
      source: "arxiv",
      source_id: "2401.04088",
      title: "Mixtral of Experts",
      notes: 3,
      checked: true,
    },
    {
      source: "arxiv",
      source_id: "hep-th/9901001",
      title: "String Junctions\nfor Arbitrary Lie Algebra Representations",
      notes: 0,
      checked: false,
    },
  ],
  open_questions: [
    {
      id: 15,
      source_id: "2401.04088",
      version: 1,
      body: "## Assistant: 路由器的负载均衡损失\n用的是什么形式？",
      published_at: "2026-11-27T10:00:00Z",
    },
  ],
};
const empty = {
  ...moe,
  id: 4,
  title: "Empty topic",
  paper_count: 0,
  papers_with_notes: 0,
  papers_checked: 0,
  open_question_count: 0,
  papers: [],
  open_questions: [],
};
const topics = new Map([
  [3, moe],
  [4, empty],
]);

const PREFIX = "/api/papers/arxiv/";
const NOTES = "/notes";

const server = createServer((request, response) => {
  const url = new URL(request.url, "http://localhost");
  const path = url.pathname;
  if (path === "/api/health") return send(response, 200, { status: "ok" });
  if (request.method === "POST" && /^\/api\/notes\/\d+\/reports$/.test(path)) {
    const id = Number(path.split("/")[3]);
    if (id === 503) return send(response, 503, { detail: "unavailable" });
    return [12, 13, 14].includes(id)
      ? send(response, 201, { id: 1 })
      : send(response, 404, { detail: `there is no public note ${id}` });
  }
  if (path === "/api/sitemap")
    return send(response, 200, {
      papers: [
        {
          source: "arxiv",
          source_id: "2401.04088",
          updated: "2026-11-27T09:30:00Z",
        },
      ],
      topics: [{ id: 3, updated: "2026-11-27T10:00:00Z" }],
    });
  if (path === "/api/topics") {
    const query = (url.searchParams.get("q") ?? "").toLowerCase();
    if (query === "down")
      return send(response, 503, { detail: "database unavailable" });
    const all = [empty, moe];
    return send(
      response,
      200,
      query ? all.filter((t) => t.title.toLowerCase().includes(query)) : all,
    );
  }
  if (path.startsWith("/api/topics/")) {
    const id = Number(path.slice("/api/topics/".length));
    if (id === 503) return send(response, 503, { detail: "unavailable" });
    const topic = topics.get(id);
    return topic === undefined
      ? send(response, 404, { detail: `there is no topic ${id}` })
      : send(response, 200, topic);
  }
  if (!path.startsWith(PREFIX))
    return send(response, 404, { detail: "no route" });
  if (path.endsWith(NOTES)) {
    const id = path.slice(PREFIX.length, -NOTES.length).replace(/v\d+$/, "");
    // The withdrawn paper doubles as the case where notes cannot be read.
    if (id === "2402.00001")
      return send(response, 503, { detail: "database unavailable" });
    return send(response, 200, notes.get(id) ?? NO_NOTES);
  }
  const id = path.slice(PREFIX.length).replace(/v\d+$/, "");
  if (id === "2401.00503")
    return send(response, 503, { detail: "arXiv unavailable" });
  const paper = papers.get(id);
  if (paper === undefined)
    return send(response, 404, { detail: `arXiv has no paper ${id}` });
  send(response, 200, paper);
});

function send(response, status, body) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

server.listen(Number(process.argv[2] ?? 8765), "127.0.0.1");
