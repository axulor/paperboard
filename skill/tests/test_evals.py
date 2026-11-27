"""Synthetic stream and subprocess tests; these are not model evaluations."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_package import check_package
from check_requests import SKILL_ROOT, load_requests
from run_evals import PREFIX, analyze_stream, command, run_case, score, verdict


def init_event() -> dict:
    """Shape of a real Claude Code 2.1.220 init: the HTTP connector is still connecting."""
    return {
        "type": "system",
        "subtype": "init",
        "plugins": [{"name": "paperboard", "path": "/tmp/plugin", "source": "paperboard@inline"}],
        "mcp_servers": [{"name": "plugin:paperboard:paperboard", "status": "pending"}],
        "tools": ["Read", "Skill"],
        "skills": ["deep-research", "paperboard:paperboard"],
    }


def use(name: str, inputs: dict, identifier: str = "call-1") -> dict:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "id": identifier, "name": name, "input": inputs}]
        },
    }


def stream(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


END = {"type": "result", "subtype": "success", "is_error": False}


class DatasetTests(unittest.TestCase):
    def test_dataset_and_package(self) -> None:
        self.assertEqual(len(load_requests(SKILL_ROOT / "evals/requests.json")), 120)
        self.assertEqual(check_package(), [])

    def test_rejects_duplicates_and_bad_expectations(self) -> None:
        rows = load_requests(SKILL_ROOT / "evals/requests.json")
        for mutation in ("duplicate", "expectation", "count", "boolean"):
            changed = copy.deepcopy(rows)
            if mutation == "duplicate":
                changed[1]["id"] = changed[0]["id"]
            elif mutation == "expectation":
                changed[0]["expected"]["first_tool"] = "find_sources"
            elif mutation == "boolean":
                changed[0]["expected"]["trigger"] = 1
            else:
                changed.pop()
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "requests.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_requests(path)


class StreamTests(unittest.TestCase):
    def test_counts_target_skill_and_deduplicates_calls(self) -> None:
        call = use(PREFIX + "search_topic", {"query": "oscillators"}, "call-2")
        observed = analyze_stream(
            stream(init_event(), use("Skill", {"skill": "paperboard:paperboard"}), call, call, END),
            "skill",
        )
        self.assertTrue(observed["valid"])
        self.assertTrue(observed["triggered"])
        self.assertEqual(len(observed["calls"]), 1)

    def test_no_skill_is_valid_negative_only_with_valid_init(self) -> None:
        self.assertFalse(analyze_stream(stream(init_event(), END), "skill")["triggered"])
        self.assertFalse(analyze_stream(stream(END), "skill")["valid"])

    def test_connector_may_still_be_connecting(self) -> None:
        for status in ("pending", "connected"):
            init = init_event()
            init["mcp_servers"][0]["status"] = status
            with self.subTest(status=status):
                self.assertTrue(analyze_stream(stream(init, END))["valid"])

    def test_wrong_field_is_invalid(self) -> None:
        observed = analyze_stream(
            stream(init_event(), use("Skill", {"name": "paperboard"}), END), "skill"
        )
        self.assertFalse(observed["valid"])

    def test_other_skill_counts_as_not_triggered(self) -> None:
        observed = analyze_stream(
            stream(init_event(), use("Skill", {"skill": "deep-research"}), END), "skill"
        )
        self.assertTrue(observed["valid"])
        self.assertFalse(observed["triggered"])
        self.assertEqual(observed["other_skills"], ["deep-research"])
        self.assertIn("paperboard:paperboard", observed["available_skills"])

    def test_bad_startup_is_not_counted_as_skill_failure(self) -> None:
        for kind in ("connection", "plugin", "tools", "extra_plugin", "extra_mcp"):
            init = init_event()
            if kind == "connection":
                init["mcp_servers"][0]["status"] = "failed"
            elif kind == "plugin":
                init["plugins"] = []
            elif kind == "tools":
                init["tools"].remove("Skill")
            elif kind == "extra_plugin":
                init["plugins"].append({"name": "other"})
            else:
                init["mcp_servers"].append({"name": "other", "status": "connected"})
            with self.subTest(kind=kind):
                observed = analyze_stream(stream(init, END), "skill")
                self.assertFalse(observed["valid"])
                self.assertIsNone(observed["triggered"])

    def test_truncated_or_error_stream_is_invalid(self) -> None:
        self.assertFalse(analyze_stream(stream(init_event()), "skill")["valid"])
        error = {"type": "result", "subtype": "error_during_execution", "is_error": True}
        self.assertFalse(analyze_stream(stream(init_event(), error), "skill")["valid"])
        with self.assertRaises(ValueError):
            analyze_stream("not json", "skill")

    def test_max_turns_keeps_observed_routing(self) -> None:
        end = {"type": "result", "subtype": "error_max_turns", "is_error": True}
        self.assertTrue(analyze_stream(stream(init_event(), end), "skill")["valid"])

    def test_tool_failure_after_connected_init_is_invalid(self) -> None:
        failed = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-2",
                        "is_error": True,
                        "content": "MCP connection closed",
                    }
                ]
            },
        }
        observed = analyze_stream(
            stream(
                init_event(),
                use("Skill", {"skill": "paperboard"}),
                use(PREFIX + "search_topic", {}, "call-2"),
                failed,
                END,
            ),
            "skill",
        )
        self.assertFalse(observed["valid"])
        self.assertIn("tool failed", observed["reason"])

    def test_wrong_first_tool_is_separate_from_trigger(self) -> None:
        row = load_requests(SKILL_ROOT / "evals/requests.json")[0]
        observed = analyze_stream(
            stream(
                init_event(),
                use("Skill", {"skill": "paperboard"}),
                use(PREFIX + "find_sources", {}, "call-2"),
                END,
            ),
            "skill",
        )
        scores = score(row, observed)
        self.assertTrue(scores["trigger_pass"])
        self.assertFalse(scores["first_tool_pass"])

    def test_latest_requires_dates_and_recent_sort(self) -> None:
        row = next(
            r
            for r in load_requests(SKILL_ROOT / "evals/requests.json")
            if r["category"] == "看最新"
        )
        for inputs, expected in (
            ({"sort": "recent"}, False),
            (
                {"sort": "recent", "submitted_from": "2025-11-26", "submitted_to": "2026-11-26"},
                True,
            ),
        ):
            observed = analyze_stream(
                stream(init_event(), use(PREFIX + "find_sources", inputs), END), "skill"
            )
            self.assertEqual(score(row, observed)["recent_sort_pass"], expected)

    def test_subset_never_claims_threshold_pass(self) -> None:
        self.assertTrue(verdict([]).startswith("未完成"))

    def test_threshold_and_invalid_cases(self) -> None:
        records = []
        for row in load_requests(SKILL_ROOT / "evals/requests.json"):
            observed = {"valid": True, "triggered": row["expected"]["trigger"], "calls": []}
            records.append(
                {"expected": row["expected"], "observed": observed, "score": score(row, observed)}
            )
        self.assertTrue(verdict(records).startswith("触发指标达标"))
        records[0]["observed"]["valid"] = False
        self.assertTrue(verdict(records).startswith("未完成"))
        records[0]["observed"]["valid"] = True
        for record in records[:11]:
            record["score"]["trigger_pass"] = False
        self.assertTrue(verdict(records).startswith("触发指标未达标"))

    def test_negative_direct_mcp_calls_count_as_false_positives(self) -> None:
        records = []
        for row in load_requests(SKILL_ROOT / "evals/requests.json"):
            positive = row["expected"]["trigger"]
            observed = {
                "valid": True,
                "triggered": positive,
                "calls": [] if positive else [{"name": "find_sources", "input": {}}],
            }
            records.append(
                {
                    "expected": row["expected"],
                    "observed": observed,
                    "score": score(row, observed),
                }
            )
        self.assertTrue(verdict(records).startswith("触发指标未达标"))
        self.assertIn("20/20", verdict(records))


class ExecutionTests(unittest.TestCase):
    def test_command_preserves_prompt_and_restricts_writes(self) -> None:
        prompt = "Find papers; $(touch /tmp/not-a-command) `whoami`"
        cmd = command("claude", prompt, SKILL_ROOT / "claude-code", 4, "skill")
        self.assertEqual(cmd[2], prompt)
        self.assertNotIn("--bare", cmd)
        self.assertIn("--max-turns", cmd)
        self.assertIn(PREFIX + "post_note," + PREFIX + "withdraw", cmd)

    def test_each_run_uses_empty_temporary_directory(self) -> None:
        row = load_requests(SKILL_ROOT / "evals/requests.json")[0]
        args = argparse.Namespace(
            claude="claude",
            plugin=SKILL_ROOT / "claude-code",
            max_turns=4,
            skill_input_field="skill",
            timeout=1,
        )

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            cwd = Path(str(kwargs["cwd"]))
            self.assertNotEqual(cwd, SKILL_ROOT.parent)
            self.assertEqual(list(cwd.iterdir()), [])
            self.assertNotIn("shell", kwargs)
            return subprocess.CompletedProcess(cmd, 0, stream(init_event(), END), "")

        with (
            tempfile.TemporaryDirectory() as output,
            patch("run_evals.subprocess.run", side_effect=fake_run),
        ):
            record = run_case(row, args, Path(output))
            self.assertTrue(record["observed"]["valid"])
            self.assertTrue((Path(output) / f"{row['id']}.jsonl").exists())

    def test_timeout_is_invalid_even_with_partial_output(self) -> None:
        row = load_requests(SKILL_ROOT / "evals/requests.json")[0]
        args = argparse.Namespace(
            claude="claude",
            plugin=SKILL_ROOT / "claude-code",
            max_turns=4,
            skill_input_field="skill",
            timeout=1,
        )
        error = subprocess.TimeoutExpired("claude", 1, output=stream(init_event(), END).encode())
        with (
            tempfile.TemporaryDirectory() as output,
            patch("run_evals.subprocess.run", side_effect=error),
        ):
            record = run_case(row, args, Path(output))
            self.assertFalse(record["observed"]["valid"])
            self.assertIsNone(record["score"]["trigger_pass"])


if __name__ == "__main__":
    unittest.main()
