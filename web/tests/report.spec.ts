import { expect, test } from "@playwright/test";

test("every note has a report form that works without JavaScript", async ({
  request,
}) => {
  const html = await (await request.get("/abs/2401.04088")).text();
  expect(html).toContain('<summary class="cursor-pointer">举报</summary>');
  expect(html).toContain('action="/notes/12/report" method="post"');
  expect(html).toContain('name="paper" value="2401.04088"');
  for (const label of [
    "垃圾广告",
    "违法或有害",
    "泄露个人信息",
    "内容或引文造假",
  ]) {
    expect(html).toContain(label);
  }
});

test("a report is sent and the reader sees what happened", async ({
  request,
}) => {
  const sent = await request.post("/notes/12/report", {
    form: { reason: "spam", detail: "卖论文", paper: "2401.04088" },
    maxRedirects: 0,
  });
  expect(sent.status()).toBe(303);
  const location = sent.headers()["location"];
  expect(location).toBe("/reported?result=ok&paper=2401.04088&note=12");

  const page = await (await request.get(location)).text();
  expect(page).toContain("已收到举报");
  expect(page).toContain('href="/abs/2401.04088#note-12"');
  expect(page).toContain('name="robots" content="noindex"');
});

test("reports that cannot be taken", async ({ request }) => {
  const cases: [string, Record<string, string>, string][] = [
    ["/notes/99/report", { reason: "spam" }, "result=missing"],
    ["/notes/503/report", { reason: "spam" }, "result=unavailable"],
    ["/notes/12/report", { reason: "boring" }, "result=invalid"],
    [
      "/notes/12/report",
      { reason: "other", detail: "x".repeat(501) },
      "result=invalid",
    ],
    ["/notes/abc/report", { reason: "spam" }, "result=invalid"],
  ];
  for (const [path, form, expected] of cases) {
    const response = await request.post(path, { form, maxRedirects: 0 });
    expect(response.status(), path).toBe(303);
    expect(response.headers()["location"], path).toContain(expected);
  }
  const missing = await (await request.get("/reported?result=missing")).text();
  expect(missing).toContain("这条留言已经不在了");
  expect(missing).not.toContain("回到论文页");
});
