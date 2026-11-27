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

const PREFIX = "/api/papers/arxiv/";

const server = createServer((request, response) => {
  const path = new URL(request.url, "http://localhost").pathname;
  if (path === "/api/health") return send(response, 200, { status: "ok" });
  if (!path.startsWith(PREFIX))
    return send(response, 404, { detail: "no route" });
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
