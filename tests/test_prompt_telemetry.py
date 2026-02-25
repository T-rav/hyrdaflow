"""Tests for prompt_telemetry.py."""

from __future__ import annotations

import json

from prompt_telemetry import PromptTelemetry, parse_command_tool_model
from tests.helpers import ConfigFactory


class TestParseCommandToolModel:
    def test_parses_claude_model(self, tmp_path):
        tool, model = parse_command_tool_model(
            ["claude", "-p", "--model", "opus", "--verbose"]
        )
        assert tool == "claude"
        assert model == "opus"

    def test_parses_codex_model(self, tmp_path):
        tool, model = parse_command_tool_model(
            ["codex", "exec", "--json", "--model", "gpt-5"]
        )
        assert tool == "codex"
        assert model == "gpt-5"


class TestPromptTelemetry:
    def test_record_writes_inference_and_pr_rollup(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        telemetry = PromptTelemetry(config)

        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=42,
            pr_number=101,
            session_id="sess-1",
            prompt_chars=800,
            transcript_chars=400,
            duration_seconds=2.5,
            success=True,
            stats={
                "history_chars_before": 200,
                "history_chars_after": 100,
                "context_chars_before": 1200,
                "context_chars_after": 900,
                "cache_hits": 2,
                "cache_misses": 1,
            },
        )

        inf_file = config.data_path("metrics", "prompt", "inferences.jsonl")
        pr_file = config.data_path("metrics", "prompt", "pr_stats.json")
        assert inf_file.exists()
        assert pr_file.exists()

        rows = [ln for ln in inf_file.read_text().splitlines() if ln.strip()]
        assert len(rows) == 1
        row = json.loads(rows[0])
        assert row["source"] == "reviewer"
        assert row["pr_number"] == 101
        assert row["session_id"] == "sess-1"
        assert row["history_chars_saved"] == 100
        assert row["context_chars_saved"] == 300
        assert row["cache_hit_rate"] == 0.6667
        assert row["token_source"] == "estimated"
        assert row["total_tokens"] == row["total_est_tokens"]
        assert row["token_estimation_mode"] == "model-aware-chars-per-token"
        assert row["token_estimation_confidence"] in {"low", "medium"}

        rollup = json.loads(pr_file.read_text())
        pr = rollup["prs"]["101"]
        assert pr["inference_calls"] == 1
        assert pr["history_chars_saved"] == 100
        assert pr["context_chars_saved"] == 300
        assert pr["actual_usage_calls"] == 0

        lifetime = rollup["lifetime"]
        assert lifetime["inference_calls"] == 1
        assert lifetime["total_tokens"] == row["total_tokens"]
        session = rollup["sessions"]["sess-1"]
        assert session["inference_calls"] == 1
        assert session["total_tokens"] == row["total_tokens"]
        assert rollup["issues"]["42"]["inference_calls"] == 1
        assert rollup["sources"]["reviewer"]["inference_calls"] == 1

    def test_record_prefers_actual_usage_when_available(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        telemetry = PromptTelemetry(config)

        telemetry.record(
            source="implementer",
            tool="claude",
            model="opus",
            issue_number=7,
            pr_number=202,
            session_id="sess-2",
            prompt_chars=1000,
            transcript_chars=500,
            duration_seconds=1.0,
            success=True,
            stats={"input_tokens": 123, "output_tokens": 77, "total_tokens": 200},
        )

        inf_file = config.data_path("metrics", "prompt", "inferences.jsonl")
        row = json.loads(inf_file.read_text().strip())
        assert row["token_source"] == "actual"
        assert row["input_tokens"] == 123
        assert row["output_tokens"] == 77
        assert row["total_tokens"] == 200

        pr_file = config.data_path("metrics", "prompt", "pr_stats.json")
        rollup = json.loads(pr_file.read_text())
        pr = rollup["prs"]["202"]
        assert pr["total_tokens"] == 200
        assert pr["actual_usage_calls"] == 1
        assert rollup["lifetime"]["total_tokens"] == 200
        assert rollup["sessions"]["sess-2"]["total_tokens"] == 200

    def test_get_session_and_lifetime_totals(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=1,
            pr_number=0,
            session_id="sess-3",
            prompt_chars=200,
            transcript_chars=100,
            duration_seconds=0.2,
            success=True,
            stats={"total_tokens": 50},
        )
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=2,
            pr_number=300,
            session_id="sess-4",
            prompt_chars=200,
            transcript_chars=100,
            duration_seconds=0.2,
            success=True,
            stats={"total_tokens": 70},
        )
        assert telemetry.get_lifetime_totals()["total_tokens"] == 120
        assert telemetry.get_session_totals("sess-3")["total_tokens"] == 50
        assert telemetry.get_pr_totals(300)["total_tokens"] == 70
        assert telemetry.get_issue_totals()[2]["total_tokens"] == 70
        assert telemetry.get_source_totals()["reviewer"]["total_tokens"] == 70

    def test_load_inferences_reads_recent_rows(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=10,
            pr_number=0,
            session_id="sess-1",
            prompt_chars=120,
            transcript_chars=30,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 12},
        )
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=11,
            pr_number=400,
            session_id="sess-2",
            prompt_chars=200,
            transcript_chars=40,
            duration_seconds=0.2,
            success=True,
            stats={"total_tokens": 20},
        )

        rows = telemetry.load_inferences(limit=1)
        assert len(rows) == 1
        assert rows[0]["issue_number"] == 11

    def test_failed_empty_run_does_not_estimate_tokens(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=13,
            pr_number=0,
            session_id="sess-fail",
            prompt_chars=5000,
            transcript_chars=0,
            duration_seconds=0.05,
            success=False,
            stats={},
        )

        inf_file = config.data_path("metrics", "prompt", "inferences.jsonl")
        row = json.loads(inf_file.read_text().strip())
        assert row["status"] == "failed"
        assert row["token_source"] == "estimated"
        assert row["total_est_tokens"] == 0
        assert row["total_tokens"] == 0

    def test_record_prefers_explicit_pruned_counter_and_section_chars(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=44,
            pr_number=500,
            session_id="sess-prune",
            prompt_chars=120,
            transcript_chars=30,
            duration_seconds=0.1,
            success=True,
            stats={
                "history_chars_before": 1000,
                "history_chars_after": 700,
                "context_chars_before": 2000,
                "context_chars_after": 1800,
                "pruned_chars_total": 123,
                "section_chars": {"issue_body_before": 1000, "issue_body_after": 700},
            },
        )
        inf_file = config.data_path("metrics", "prompt", "inferences.jsonl")
        row = json.loads(inf_file.read_text().strip())
        assert row["pruned_chars_total"] == 123
        assert row["section_chars"]["issue_body_before"] == 1000

        pr_file = config.data_path("metrics", "prompt", "pr_stats.json")
        rollup = json.loads(pr_file.read_text())
        assert rollup["prs"]["500"]["pruned_chars_total"] == 123

    def test_record_derives_pruned_counter_when_explicit_missing(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=45,
            pr_number=501,
            session_id="sess-prune",
            prompt_chars=120,
            transcript_chars=30,
            duration_seconds=0.1,
            success=True,
            stats={
                "history_chars_before": 1000,
                "history_chars_after": 700,
                "context_chars_before": 2000,
                "context_chars_after": 1800,
            },
        )
        inf_file = config.data_path("metrics", "prompt", "inferences.jsonl")
        row = json.loads(inf_file.read_text().strip())
        assert row["pruned_chars_total"] == 500
