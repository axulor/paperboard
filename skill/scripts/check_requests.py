#!/usr/bin/env python3
"""Validate the request dataset offline; safe to run in CI."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("找文献", "查有没有", "看最新", "调研", "查一篇", "不触发")


def load_requests(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != 120:
        raise ValueError("Expected a list of exactly 120 requests")
    ids: set[str] = set()
    prompts: set[str] = set()
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "language",
            "category",
            "prompt",
            "expected",
        }:
            raise ValueError("Invalid request fields")
        identifier, prompt = row["id"], row["prompt"]
        if not isinstance(identifier, str) or not re.fullmatch(r"\d{2}-(zh|en)-\d{2}", identifier):
            raise ValueError("Invalid request id")
        if identifier in ids or not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"Duplicate id or empty prompt: {identifier}")
        if prompt.strip() in prompts:
            raise ValueError(f"Duplicate prompt: {identifier}")
        ids.add(identifier)
        prompts.add(prompt.strip())
        category, language = row["category"], row["language"]
        if category not in CATEGORIES or language not in ("zh", "en"):
            raise ValueError(f"Unknown category/language: {identifier}")
        counts[category, language] += 1
        expected = {
            "trigger": category != "不触发",
            "first_tool": None
            if category == "不触发"
            else ("check_paper" if category == "查一篇" else "search_topic"),
            "recent_sort": category == "看最新",
            "state_date_range": category == "看最新",
        }
        actual = row["expected"]
        if not isinstance(actual, dict) or actual != expected:
            raise ValueError(f"Wrong expectations: {identifier}")
        if any(
            type(actual[key]) is not bool for key in ("trigger", "recent_sort", "state_date_range")
        ):
            raise ValueError(f"Expectations must use JSON booleans: {identifier}")
    if any(counts[category, lang] != 10 for category in CATEGORIES for lang in ("zh", "en")):
        raise ValueError("Each category/language pair must contain exactly 10 requests")
    for language in ("zh", "en"):
        single = [
            r["prompt"] for r in rows if r["category"] == "查一篇" and r["language"] == language
        ]
        if not any("arxiv.org/" in p for p in single) or not any("arXiv:" in p for p in single):
            raise ValueError("Single-paper cases need both arXiv ids and links")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, default=SKILL_ROOT / "evals/requests.json")
    args = parser.parse_args()
    try:
        rows = load_requests(args.requests)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print(f"PASS: {len(rows)} requests; five positive categories, 20 negatives; balanced zh/en")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
