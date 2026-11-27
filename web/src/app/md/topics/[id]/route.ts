// Markdown version of a topic page. Served at /topics/{id}.md and for requests that accept
// text/markdown; src/proxy.ts rewrites those requests here.

import type { NextRequest } from "next/server";

import { ApiError, getTopic } from "@/lib/api/client";
import { siteUrl } from "@/lib/config";
import { parseTopicId, topicMarkdown } from "@/lib/topics";

const HEADERS = {
  "Content-Type": "text/markdown; charset=utf-8",
  // The HTML page is the one to index.
  "X-Robots-Tag": "noindex",
  Vary: "Accept",
};

export async function GET(
  _request: NextRequest,
  context: RouteContext<"/md/topics/[id]">,
) {
  const segment = (await context.params).id;
  const id = parseTopicId(segment);
  if (id === null) return markdown(404, `# 不是题目编号\n\n${segment}\n`);
  let topic;
  try {
    topic = await getTopic(id);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return markdown(503, "# 暂时取不到这个题目的数据\n\n请过一会儿再试。\n");
  }
  if (topic === null) return markdown(404, `# 没有这个题目\n\n#${id}\n`);
  return markdown(200, topicMarkdown(topic, siteUrl()));
}

function markdown(status: number, body: string): Response {
  return new Response(body, { status, headers: HEADERS });
}
