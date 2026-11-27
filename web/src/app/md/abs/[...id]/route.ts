// Markdown version of a paper page. Served at /abs/{id}.md and for requests that accept
// text/markdown; src/proxy.ts rewrites those requests here.

import type { NextRequest } from "next/server";

import { ApiError, getPaper } from "@/lib/api/client";
import { idFromSegments, parseArxivId } from "@/lib/arxiv";
import { siteUrl } from "@/lib/config";
import { paperMarkdown } from "@/lib/paper";

const HEADERS = {
  "Content-Type": "text/markdown; charset=utf-8",
  // The HTML page is the one to index.
  "X-Robots-Tag": "noindex",
  Vary: "Accept",
};

export async function GET(
  _request: NextRequest,
  context: RouteContext<"/md/abs/[...id]">,
) {
  const path = idFromSegments((await context.params).id);
  const id = parseArxivId(path);
  if (id === null) return markdown(404, `# 不是 arXiv 编号\n\n${path}\n`);
  let report;
  try {
    report = await getPaper(id.base);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return markdown(503, "# 暂时取不到这篇论文的数据\n\n请过一会儿再试。\n");
  }
  if (report === null)
    return markdown(404, `# arXiv 上没有这篇论文\n\n${id.base}\n`);
  return markdown(
    200,
    paperMarkdown(report, `${siteUrl()}/abs/${report.facts.source_id}`),
  );
}

function markdown(status: number, body: string): Response {
  return new Response(body, { status, headers: HEADERS });
}
