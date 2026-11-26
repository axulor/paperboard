#!/usr/bin/env python3
"""Check portable package invariants without a model or third-party libraries."""

from __future__ import annotations

import json
import re
from pathlib import Path

from check_requests import SKILL_ROOT


def check_package(root: Path = SKILL_ROOT) -> list[str]:
    errors: list[str] = []
    plugin = root / "claude-code"
    manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    if manifest.get("name") != "paperboard" or not manifest.get("version"):
        errors.append("Plugin name/version missing")
    connector = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))
    expected = {"mcpServers": {"paperboard": {"type": "http", "url": "http://127.0.0.1:8000/mcp"}}}
    if connector != expected:
        errors.append("Default connector must be token-free and read-only localhost")
    skills = list(root.rglob("SKILL.md"))
    canonical = plugin / "skills/paperboard/SKILL.md"
    if skills != [canonical]:
        errors.append("Expected exactly one canonical SKILL.md within the plugin")
    text = canonical.read_text(encoding="utf-8")
    pieces = text.split("---", 2)
    if len(pieces) != 3 or pieces[0]:
        errors.append("Missing frontmatter")
    else:
        fields = re.findall(r"^([a-z_]+):", pieces[1], re.MULTILINE)
        if fields != ["name", "description"]:
            errors.append("Frontmatter must contain only name and description")
        tech = (root.parent / "reports/技术栈.md").read_text(encoding="utf-8")
        original = re.search(r"```yaml\n(---\nname: paperboard\n.*?\n---)\n```", tech, re.DOTALL)
        if original is None or not text.startswith(original.group(1) + "\n"):
            errors.append("Frontmatter differs from technical stack section 5.2")
    for target in re.findall(r"\]\((references/[^)]+)\)", text):
        path = canonical.parent / target
        if not path.is_file() or plugin.resolve() not in path.resolve().parents:
            errors.append(f"Missing or escaping reference: {target}")
    descriptions = (root / "tool-descriptions.md").read_text(encoding="utf-8")
    blocks = dict(re.findall(r"## (\w+)\n\n```text\n(.*?)\n```", descriptions, re.DOTALL))
    names = {"find_sources", "check_paper", "search_topic", "post_note", "withdraw", "instructions"}
    if set(blocks) != names:
        errors.append("Expected five tool descriptions and server instructions")
    for name, content in blocks.items():
        if not content.strip() or len(content) > 600:
            errors.append(f"Empty or over 600 characters: {name}")
        if name != "instructions":
            for keyword in ("paper", "arXiv", "citation", "论文", "文献", "引用", "复现"):
                if keyword not in content:
                    errors.append(f"Missing {keyword} in {name}")
    return errors


def main() -> int:
    errors = check_package()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: portable skill, source-matched description, read-only MCP, bilingual tool text")
    print("This structural check does not replace claude plugin validate or real model tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
