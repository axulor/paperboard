import { expect, test } from "@playwright/test";

test("sitemap.xml lists topics and papers with notes", async ({ request }) => {
  const response = await request.get("/sitemap.xml");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("xml");
  const xml = await response.text();
  for (const loc of [
    "/topics</loc>",
    "/topics/3</loc>",
    "/abs/2401.04088</loc>",
  ]) {
    expect(xml).toContain(loc);
  }
  expect(xml).toContain("<lastmod>2026-11-27T09:30:00");
  // Papers without notes are not listed.
  expect(xml).not.toContain("hep-th/9901001");
});

test("robots.txt points to the sitemap", async ({ request }) => {
  const text = await (await request.get("/robots.txt")).text();
  expect(text).toContain("Allow: /");
  expect(text).toMatch(/Sitemap: \S+\/sitemap\.xml/);
});
