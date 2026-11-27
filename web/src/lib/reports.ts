// Reporting a note: the reasons a reader can pick, and what the confirmation page says.

import type { ReportReason } from "@/lib/api/client";

export const REPORT_REASONS: { value: ReportReason; label: string }[] = [
  { value: "spam", label: "垃圾广告" },
  { value: "illegal", label: "违法或有害" },
  { value: "privacy", label: "泄露个人信息" },
  { value: "misleading", label: "内容或引文造假" },
  { value: "other", label: "其他" },
];

export const MAX_REPORT_DETAIL = 500;

export function isReportReason(value: unknown): value is ReportReason {
  return REPORT_REASONS.some((reason) => reason.value === value);
}

export type ReportResult = "ok" | "missing" | "unavailable" | "invalid";

export const REPORT_MESSAGES: Record<ReportResult, string> = {
  ok: "已收到举报，我们会尽快处理。违反规则的留言会被下架。",
  missing: "这条留言已经不在了：可能已被撤回或下架。",
  unavailable: "暂时无法提交举报，请过一会儿再试。",
  invalid: "举报的内容不完整：请选择一个原因，补充说明不超过 500 字。",
};

export function reportResult(value: unknown): ReportResult {
  return value === "ok" ||
    value === "missing" ||
    value === "unavailable" ||
    value === "invalid"
    ? value
    : "invalid";
}
