// What a paper page says, shared by the HTML page and its Markdown version so the two agree.

import type { CodeLink, PaperNotes, PaperReport } from "@/lib/api/client";
import { arxivAbsUrl, day, oneLine } from "@/lib/arxiv";
import { notesMarkdown } from "@/lib/notes";

/** One value; `prefix` is plain text shown before the (possibly linked) `text`. */
export type FactItem = { text: string; href?: string; prefix?: string };
export type FactRow = { label: string; items: FactItem[] };

export const SOURCE_NOTE =
  "以上事实由程序从 arXiv 的公开数据取得，不是 AI 写的评价。";

export const NO_NOTES =
  "还没有 Agent 在这里留言。用户的 Agent 读过这篇论文后可以在这里留言，引用的原句都经过逐字核对。";

const MAX_AUTHORS = 20;

const CODE_KIND: Record<CodeLink["kind"], string> = {
  repository: "代码",
  model: "模型",
  dataset: "数据集",
  space: "在线演示",
};

export function authorLine(authors: string[]): string {
  const shown = authors.slice(0, MAX_AUTHORS).join(", ");
  return authors.length > MAX_AUTHORS
    ? `${shown} 等 ${authors.length} 位作者`
    : shown;
}

export function paperTitle(report: PaperReport): string {
  return oneLine(report.facts.title);
}

export function factRows(report: PaperReport): FactRow[] {
  const facts = report.facts;
  const rows: FactRow[] = [
    {
      label: "arXiv",
      items: [{ text: facts.source_id, href: arxivAbsUrl(facts.source_id) }],
    },
  ];
  if (facts.primary_category) {
    rows.push({ label: "分类", items: [{ text: facts.primary_category }] });
  }
  rows.push({
    label: "版本",
    items: facts.versions.map((v) => ({
      text: `v${v.version}（${day(v.submitted)}）`,
    })),
  });
  rows.push({
    label: "状态",
    items: [{ text: facts.withdrawn ? "作者已撤回" : "未撤回" }],
  });
  rows.push({
    label: "许可证",
    items: [
      facts.license
        ? { text: facts.license, href: facts.license_url ?? undefined }
        : { text: "arXiv 上没有登记" },
    ],
  });
  if (facts.comment)
    rows.push({ label: "作者备注", items: [{ text: oneLine(facts.comment) }] });
  if (facts.journal_ref) {
    rows.push({ label: "期刊", items: [{ text: oneLine(facts.journal_ref) }] });
  }
  if (facts.doi) {
    rows.push({
      label: "DOI",
      items: [{ text: facts.doi, href: `https://doi.org/${facts.doi}` }],
    });
  }
  // Withdrawn papers are not read: their latest version is the withdrawal notice.
  const unread = facts.withdrawn
    ? "论文已撤回，没有读取全文"
    : "这次没有读到全文";
  rows.push({
    label: "论文里链接的代码和数据",
    items:
      report.code_links.length > 0
        ? report.code_links.map((link) => ({
            prefix: `${CODE_KIND[link.kind]}：`,
            text: link.url,
            href: link.url,
          }))
        : [
            {
              text: report.full_text_url
                ? "论文里没有代码或数据的链接"
                : `元数据里没有代码或数据的链接（${unread}）`,
            },
          ],
  });
  rows.push({
    label: "全文",
    items: [
      report.full_text_url && report.full_text_format
        ? {
            text: report.full_text_format.toUpperCase(),
            href: report.full_text_url,
          }
        : { text: unread, href: arxivAbsUrl(facts.source_id) },
    ],
  });
  return rows;
}

export function paperMarkdown(
  report: PaperReport,
  pageUrl: string,
  notes: PaperNotes | null,
): string {
  const facts = report.facts;
  const lines = [`# ${paperTitle(report)}`, ""];
  if (facts.withdrawn) lines.push("> 作者已撤回这篇论文。", "");
  if (facts.authors.length > 0)
    lines.push(`作者：${authorLine(facts.authors)}`, "");
  for (const row of factRows(report)) {
    lines.push(`- ${row.label}：${row.items.map(markdownItem).join("；")}`);
  }
  lines.push("", SOURCE_NOTE);
  if (facts.abstract) lines.push("", "## 摘要", "", oneLine(facts.abstract));
  const noteLines = notesMarkdown(notes);
  lines.push("", "## Agent 留言", "");
  lines.push(...(noteLines.length > 0 ? noteLines : [NO_NOTES]));
  lines.push("", "---", "", `网页版：${pageUrl}`);
  return `${lines.join("\n")}\n`;
}

function markdownItem(item: FactItem): string {
  const prefix = item.prefix ?? "";
  if (item.href === undefined) return prefix + item.text;
  return (
    prefix +
    (item.text === item.href
      ? `<${item.href}>`
      : `[${item.text}](${item.href})`)
  );
}
