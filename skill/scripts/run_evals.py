#!/usr/bin/env python3
"""Run real Claude Code routing evaluations, with isolated working directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from check_requests import SKILL_ROOT, load_requests

PREFIX = "mcp__plugin_paperboard_paperboard__"
READ_TOOLS = {"search_topic", "find_sources", "check_paper"}


def analyze_stream(raw: str, field: str | None) -> dict[str, Any]:
    """Treat missing/unknown init evidence as invalid, never as a routing failure."""
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError("Stream event must be an object")
        events.append(event)
    init = next(
        (e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None
    )
    result: dict[str, Any] = {
        "valid": False,
        "reason": "missing system/init",
        "triggered": None,
        "calls": [],
        "skill_inputs": [],
        "text": "",
        "cost_usd": None,
    }
    if init is None:
        return result
    plugins = init.get("plugins", [])
    mcps = init.get("mcp_servers", [])
    names = [p.get("name") for p in plugins if isinstance(p, dict)]
    if len(names) != 1 or names[0] not in {"paperboard", "paperboard@paperboard"}:
        result["reason"] = "expected only the paperboard plugin; inspect system/init"
        return result
    matching = [
        m for m in mcps if isinstance(m, dict) and m.get("name") == "plugin_paperboard_paperboard"
    ]
    if len(matching) != 1 or matching[0].get("status") != "connected" or len(mcps) != 1:
        result["reason"] = "expected only a connected plugin_paperboard_paperboard MCP"
        return result
    advertised = init.get("tools", [])
    if "Skill" not in advertised or not all(PREFIX + t in advertised for t in READ_TOOLS):
        result["reason"] = "Skill or first-stage read tools missing (check #9 and MCP startup)"
        return result
    if any(e.get("type") == "assistant" for e in events[: events.index(init)]):
        result["reason"] = "assistant output precedes system/init"
        return result
    seen: set[str] = set()
    relevant_ids: set[str] = set()
    for event in events:
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                result["text"] += str(block.get("text", "")) + "\n"
            if block.get("type") != "tool_use":
                continue
            identifier = block.get("id")
            if not isinstance(identifier, str):
                result["reason"] = "tool_use without id; inspect stream schema"
                return result
            if identifier in seen:
                continue
            seen.add(identifier)
            name, inputs = block.get("name", ""), block.get("input", {})
            if name == "Skill":
                relevant_ids.add(identifier)
                result["skill_inputs"].append(inputs)
            elif name.startswith(PREFIX):
                relevant_ids.add(identifier)
                result["calls"].append({"name": name[len(PREFIX) :], "input": inputs})
            elif name.startswith("mcp__"):
                result["reason"] = "unexpected external MCP call"
                return result
    for event in events:
        if event.get("type") != "user":
            continue
        for block in event.get("message", {}).get("content", []):
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and block.get("tool_use_id") in relevant_ids
                and block.get("is_error")
            ):
                result["reason"] = "Skill/MCP tool failed during execution; inspect raw tool_result"
                return result
    endings = [e for e in events if e.get("type") == "result"]
    if not endings:
        result["reason"] = "missing result event (incomplete stream)"
        return result
    ending = endings[-1]
    result["cost_usd"] = ending.get("total_cost_usd")
    result["completion"] = ending.get("subtype")
    if ending.get("subtype") not in {"success", "error_max_turns"}:
        result["reason"] = "CLI/model error: " + str(ending.get("subtype"))
        return result
    if ending.get("is_error") and ending.get("subtype") != "error_max_turns":
        result["reason"] = "CLI/model returned an error"
        return result
    if result["skill_inputs"] and field is None:
        result["reason"] = "pilot: confirm Skill input field from raw stream before scoring"
        return result
    values = [x.get(field) if isinstance(x, dict) else None for x in result["skill_inputs"]]
    if any(not isinstance(v, str) for v in values):
        result["reason"] = "Skill input field missing or changed; inspect raw stream"
        return result
    if any(v not in {"paperboard", "paperboard:paperboard"} for v in values):
        result["reason"] = "unexpected skill; remove other skills before evaluation"
        return result
    result.update(valid=True, reason="", triggered=bool(values))
    return result


def score(row: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    if not observed["valid"]:
        return {"trigger_pass": None, "first_tool_pass": None, "recent_sort_pass": None}
    calls, expected = observed["calls"], row["expected"]
    first = calls[0]["name"] if calls else None
    recent = None
    if expected["recent_sort"]:
        searches = [c["input"] for c in calls if c["name"] == "find_sources"]
        recent = bool(searches) and all(
            isinstance(s, dict)
            and s.get("sort") == "recent"
            and bool(s.get("submitted_from"))
            and bool(s.get("submitted_to"))
            for s in searches
        )
    return {
        "trigger_pass": (
            bool(observed["triggered"])
            if expected["trigger"]
            else not (observed["triggered"] or calls)
        ),
        "first_tool_pass": first == expected["first_tool"],
        "recent_sort_pass": recent,
    }


def command(executable: str, prompt: str, plugin: Path, turns: int, field: str | None) -> list[str]:
    # field is used by the parser only; never tell the model the expected routing.
    del field
    return [
        executable,
        "-p",
        prompt,
        "--plugin-dir",
        str(plugin.resolve()),
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        str(turns),
        "--allowedTools",
        "Skill,mcp__plugin_paperboard_paperboard__*",
        "--tools",
        "Skill,Read",
        "--setting-sources",
        "project,local",
        "--disallowedTools",
        PREFIX + "post_note," + PREFIX + "withdraw",
    ]


def run_case(row: dict[str, Any], args: argparse.Namespace, output: Path) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="paperboard-eval-") as temporary:
        # No repository AGENTS.md, CLAUDE.md, or .mcp.json in this directory.
        try:
            completed = subprocess.run(
                command(
                    args.claude, row["prompt"], args.plugin, args.max_turns, args.skill_input_field
                ),
                cwd=temporary,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=args.timeout,
                check=False,
            )
            raw, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            raw = exc.stdout or b""
            stderr = exc.stderr or b""
            raw = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            stderr = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
            returncode, timed_out = None, True
    (output / f"{row['id']}.jsonl").write_text(raw, encoding="utf-8")
    (output / f"{row['id']}.stderr.txt").write_text(stderr, encoding="utf-8")
    try:
        observed = analyze_stream(raw, args.skill_input_field)
    except (ValueError, TypeError, AttributeError) as exc:
        observed = {
            "valid": False,
            "reason": f"unrecognized stream: {exc}",
            "calls": [],
            "triggered": None,
        }
    if timed_out:
        observed.update(valid=False, reason="process timeout")
    elif returncode != 0 and observed.get("completion") != "error_max_turns":
        observed.update(
            valid=False, reason=f"process exit {returncode}: {observed.get('reason', '')}"
        )
    return {
        "id": row["id"],
        "category": row["category"],
        "language": row["language"],
        "expected": row["expected"],
        "observed": observed,
        "score": score(row, observed),
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "returncode": returncode,
    }


def verdict(records: list[dict[str, Any]]) -> str:
    positive = [r for r in records if r["expected"]["trigger"]]
    negative = [r for r in records if not r["expected"]["trigger"]]
    if (
        len(positive) != 100
        or len(negative) != 20
        or not all(r["observed"]["valid"] for r in records)
    ):
        return "未完成：缺少完整的 120 条有效实测，不能给出验收通过结论。"
    good = sum(r["score"]["trigger_pass"] for r in positive)
    false = sum(not r["score"]["trigger_pass"] for r in negative)
    if good < 90 or false > 2:
        return f"触发指标未达标：正例 {good}/100，负例误触发 {false}/20。"
    return f"触发指标达标：正例 {good}/100，负例误触发 {false}/20；流程与简报仍需单独验收。"


def report(records: list[dict[str, Any]], metadata: dict[str, Any], directory: Path) -> None:
    payload = {"metadata": metadata, "verdict": verdict(records), "records": records}
    (directory / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Claude Code 真实模型测试",
        "",
        verdict(records),
        "",
        "输入文件、版本、开始时间与原始输出保存在同目录；无效环境不计作技能误判。",
        "",
        "| 编号 | 类型 | 环境有效 | 技能触发 | 首工具符合 | 最新排序 | 工具次数 / 原因 |",
        "|---|---|---|---|---|---|---|",
    ]

    def cell(value: Any) -> str:
        return "—" if value is None else ("是" if value else "否")

    for record in records:
        obs, scores = record["observed"], record["score"]
        counts = dict(Counter(c["name"] for c in obs["calls"]))
        details = str(counts) if obs["valid"] else obs["reason"]
        details = details.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {record['id']} | {record['category']} | {cell(obs['valid'])} | "
            f"{cell(obs['triggered'])} | {cell(scores['first_tool_pass'])} | "
            f"{cell(scores['recent_sort_pass'])} | {details} |"
        )
    lines.extend(
        [
            "",
            "首工具、排序与触发分别统计，不能用触发率代替流程正确率。",
            "日期范围是否在简报开头写明、范围是否正确、引文是否逐句支持结论，需要查看原始输出人工核对。",
            "本轮是有限轮数的只读路由测试；不包含全文阅读、公开留言或完整调研验收。",
            "",
        ]
    )
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, default=SKILL_ROOT / "evals/requests.json")
    parser.add_argument("--plugin", type=Path, default=SKILL_ROOT / "claude-code")
    parser.add_argument("--claude", default="claude")
    parser.add_argument(
        "--pilot", action="store_true", help="Inspect one real stream before mapping Skill input"
    )
    parser.add_argument(
        "--skill-input-field", help="Field observed in the pilot's Skill input; do not guess"
    )
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--output", type=Path, help="New empty output directory (raw traces stay local)"
    )
    args = parser.parse_args()
    if args.max_turns < 1 or args.timeout < 1:
        parser.error("Turn and timeout limits must be positive")
    if not args.pilot and not args.skill_input_field:
        parser.error("Run --pilot first; inspect Skill tool input, then pass --skill-input-field")
    executable = shutil.which(args.claude)
    if not executable:
        parser.exit(2, "BLOCKED: Claude Code CLI not found; no model evaluations were run.\n")
    args.claude = str(Path(executable).resolve())
    rows = load_requests(args.requests)
    if args.pilot:
        rows = rows[:1]
    now = datetime.now().astimezone()
    directory = args.output or SKILL_ROOT / "evals/local-runs" / now.strftime("%Y%m%d-%H%M%S")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    version = subprocess.run(
        [args.claude, "--version"], capture_output=True, text=True, timeout=30, check=False
    )
    digest = hashlib.sha256()
    for path in sorted(args.plugin.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(args.plugin)).encode())
            digest.update(path.read_bytes())
    metadata = {
        "started_at": now.isoformat(),
        "claude_version": version.stdout.strip(),
        "request_sha256": hashlib.sha256(args.requests.read_bytes()).hexdigest(),
        "plugin_sha256": digest.hexdigest(),
        "max_turns": args.max_turns,
        "skill_input_field": args.skill_input_field,
        "pilot": args.pilot,
    }
    records: list[dict[str, Any]] = []
    report(records, metadata, directory)
    for row in rows:
        record = run_case(row, args, directory)
        records.append(record)
        report(records, metadata, directory)
        print(f"{row['id']}: {record['observed']['reason'] or 'recorded'}", flush=True)
        if not record["observed"]["valid"]:
            print("Stopped on invalid environment/schema; inspect raw output before retrying.")
            break
    print(f"Report: {directory / 'report.md'}")
    if args.pilot:
        return 0 if records and records[0]["observed"].get("skill_inputs") else 2
    return 0 if verdict(records).startswith("触发指标达标") else 1


if __name__ == "__main__":
    raise SystemExit(main())
