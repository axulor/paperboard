import { expect, test } from "@playwright/test";

test("a topic page summarises its papers and open questions", async ({
  request,
}) => {
  const response = await request.get("/topics/3");
  expect(response.status()).toBe(200);
  expect(response.headers()["vary"]).toContain("Accept");
  const html = await response.text();
  expect(html).toMatch(/<h1[^>]*>Mixture of experts<\/h1>/);
  expect(html).not.toMatch(/<div hidden id="S:/);
  for (const text of [
    "相关论文 2 篇：有留言的 1 篇，引文核对过的 1 篇；没人回答的问题 1 个。",
    "不是 AI 写的评价",
    'href="/abs/2401.04088">Mixtral of Experts</a>',
    "arXiv 2401.04088 · 留言 3 条 · 引文核对过",
    "String Junctions for Arbitrary Lie Algebra Representations",
    "arXiv hep-th/9901001 · 留言 0 条",
    'href="/abs/2401.04088#note-15">#15</a>',
    "用的是什么形式？",
  ]) {
    expect(html).toContain(text);
  }
  expect(html).toContain(
    '<link rel="canonical" href="http://localhost:3100/topics/3"/>',
  );
  expect(html).toContain(
    'type="text/markdown" href="http://localhost:3100/topics/3.md"',
  );

  const emptyTopic = await (await request.get("/topics/4")).text();
  expect(emptyTopic).toContain("这个题目下还没有论文。");
  expect(emptyTopic).toContain("目前没有待回答的问题。");
});

test("the Markdown version of a topic page", async ({ request }) => {
  const response = await request.get("/topics/3.md");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe(
    "text/markdown; charset=utf-8",
  );
  expect(response.headers()["x-robots-tag"]).toBe("noindex");
  const markdown = await response.text();
  expect(markdown.startsWith("# Mixture of experts\n")).toBe(true);
  expect(markdown).toContain(
    "- [Mixtral of Experts](http://localhost:3100/abs/2401.04088)：arXiv 2401.04088 · 留言 3 条 · 引文核对过",
  );
  // The question's heading marker and role prefix are dropped; its lines are joined.
  expect(markdown).toContain(
    "- “路由器的负载均衡损失 用的是什么形式？”（[#15](http://localhost:3100/abs/2401.04088#note-15)，arXiv 2401.04088v1，2026-11-27）",
  );
  expect(markdown).not.toContain("Assistant:");
  expect(markdown).toContain("网页版：http://localhost:3100/topics/3");

  const negotiated = await request.get("/topics/3", {
    headers: { Accept: "text/markdown" },
  });
  expect(await negotiated.text()).toBe(markdown);
  expect((await request.get("/topics/99.md")).status()).toBe(404);
  expect((await request.get("/topics/503.md")).status()).toBe(503);
});

test("topic ids that are not numbers are a 404", async ({ request }) => {
  for (const path of [
    "/topics/abc",
    "/topics/0",
    "/topics/3/x",
    "/topics/-1",
  ]) {
    expect((await request.get(path)).status(), path).toBe(404);
  }
  const missing = await request.get("/topics/99");
  expect(missing.status()).toBe(200);
  expect(await missing.text()).toContain('name="robots" content="noindex"');
});

test("when the API cannot give the topic", async ({ request }) => {
  const html = await (await request.get("/topics/503")).text();
  expect(html).toContain("暂时取不到这个题目的数据");
});

test("the topic list and search", async ({ request }) => {
  const newest = await (await request.get("/topics")).text();
  expect(newest).toContain("最新的题目");
  expect(newest).toContain('href="/topics/3">Mixture of experts</a>');
  expect(newest).toContain('href="/topics/4">Empty topic</a>');
  expect(newest).toContain('name="q"');

  const found = await (await request.get("/topics?q=mixture")).text();
  expect(found).toContain("和「mixture」相近的题目");
  expect(found).toContain('href="/topics/3"');
  expect(found).not.toContain('href="/topics/4"');

  const none = await (await request.get("/topics?q=protein")).text();
  expect(none).toContain("还没有和「protein」相近的题目。");
  const down = await (await request.get("/topics?q=down")).text();
  expect(down).toContain("暂时取不到题目");
});
