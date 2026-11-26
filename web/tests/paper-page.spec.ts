import { expect, test } from "@playwright/test";

test("a paper page is complete in the first response", async ({ request }) => {
  const response = await request.get("/abs/2401.04088");
  expect(response.status()).toBe(200);
  expect(response.headers()["vary"]).toContain("Accept");
  const html = await response.text();

  expect(html).toMatch(/<h1[^>]*>Mixtral of Experts<\/h1>/);
  // Streamed content would arrive in hidden <div id="S:…"> blocks that need JavaScript.
  expect(html).not.toMatch(/<div hidden id="S:/);
  for (const text of [
    "Albert Q. Jiang",
    "等 26 位作者",
    "v1（2024-01-08）",
    "CC BY 4.0",
    "https://github.com/mistralai/mistral-src",
    "We introduce Mixtral 8x7B",
    "不是 AI 写的评价",
  ]) {
    expect(html).toContain(text);
  }
  expect(html).toContain('"@type":"ScholarlyArticle"');
  expect(html).toContain(
    '<link rel="canonical" href="http://localhost:3100/abs/2401.04088"/>',
  );
  expect(html).toContain(
    'type="text/markdown" href="http://localhost:3100/abs/2401.04088.md"',
  );
  expect(html).not.toContain('name="robots"');
});

test("versioned and old-style ids", async ({ request }) => {
  const versioned = await (await request.get("/abs/2401.04088v1")).text();
  expect(versioned).toContain(
    '<link rel="canonical" href="http://localhost:3100/abs/2401.04088"/>',
  );

  const old = await request.get("/abs/hep-th/9901001");
  expect(old.status()).toBe(200);
  const html = await old.text();
  expect(html).toContain("String Junctions");
  expect(html).toContain("v3（1999-05-10）");
  expect(html).toContain("arXiv 上没有登记");
});

test("a withdrawn paper says so", async ({ request }) => {
  const html = await (await request.get("/abs/2402.00001")).text();
  expect(html).toContain("作者已撤回这篇论文。");
  expect(html).toContain("论文已撤回，没有读取全文");
});

test("the Markdown version", async ({ request }) => {
  const response = await request.get("/abs/2401.04088.md");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe(
    "text/markdown; charset=utf-8",
  );
  expect(response.headers()["x-robots-tag"]).toBe("noindex");
  const markdown = await response.text();
  expect(markdown.startsWith("# Mixtral of Experts\n")).toBe(true);
  expect(markdown).toContain("- 版本：v1（2024-01-08）");
  expect(markdown).toContain(
    "- 许可证：[CC BY 4.0](http://creativecommons.org/licenses/by/4.0/)",
  );
  expect(markdown).toContain(
    "代码：<https://github.com/mistralai/mistral-src>",
  );
  expect(markdown).toContain("## 摘要");
  expect(markdown).toContain("网页版：http://localhost:3100/abs/2401.04088");

  const negotiated = await request.get("/abs/2401.04088", {
    headers: { Accept: "text/markdown" },
  });
  expect(await negotiated.text()).toBe(markdown);
  expect(await (await request.get("/abs/hep-th/9901001.md")).text()).toContain(
    "# String Junctions",
  );
});

test("a paper arXiv does not have", async ({ request }) => {
  // The page starts streaming before it knows, so it keeps 200 and is marked noindex.
  const page = await request.get("/abs/2401.99999");
  const html = await page.text();
  expect(html).toContain("arXiv 上没有这篇论文");
  expect(html).toContain('<meta name="robots" content="noindex"/>');

  const markdown = await request.get("/abs/2401.99999.md");
  expect(markdown.status()).toBe(404);
});

test("a path that is not an arXiv id is a 404", async ({ request }) => {
  const response = await request.get("/abs/not-a-paper");
  expect(response.status()).toBe(404);
  expect(await response.text()).toContain("没有这个页面");
  expect((await request.get("/abs/%E0%A4%A")).status()).toBe(404);
});

test("when the API is unavailable", async ({ request }) => {
  const html = await (await request.get("/abs/2401.00503")).text();
  expect(html).toMatch(/<h1[^>]*>暂时取不到这篇论文的数据<\/h1>/);
  expect(html).toContain('<meta name="robots" content="noindex"/>');
  expect((await request.get("/abs/2401.00503.md")).status()).toBe(503);
});

test("llms.txt", async ({ request }) => {
  const response = await request.get("/llms.txt");
  expect(response.status()).toBe(200);
  const text = await response.text();
  expect(text.startsWith("# PaperBoard\n")).toBe(true);
  expect(text).toContain("/abs/2401.04088.md");
  expect(text).toContain("Streamable HTTP");
});
