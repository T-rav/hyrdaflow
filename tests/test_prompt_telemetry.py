"""Tests for prompt_telemetry.py."""

from __future__ import annotations

from model_pricing import ModelPricingTable
from prompt_telemetry import PromptTelemetry, _as_float, parse_command_tool_model
from tests.helpers import ConfigFactory


class _InMemoryState:
    """Lightweight in-memory mock that supports the state methods used by PromptTelemetry."""

    def __init__(self):
        self._inferences: list[dict] = []
        self._stats: dict[str, dict] = {}
        self._model_pricing: list[dict] = []

    def append_inference(self, record: dict) -> None:
        self._inferences.append(record)

    def save_inference_stats(self, key: str, data: dict) -> None:
        self._stats[key] = data

    def load_inference_stats(self, key: str) -> dict | None:
        return self._stats.get(key)

    def count_inferences(self) -> int:
        return len(self._inferences)

    def load_recent_inferences(self, limit: int = 100) -> list[dict]:
        # Return newest first (like DoltStore)
        return list(reversed(self._inferences))[:limit]

    def load_all_inference_stats_by_prefix(self, prefix: str) -> dict[str, dict]:
        return {k: v for k, v in self._stats.items() if k.startswith(prefix)}

    def load_all_model_pricing(self) -> list[dict]:
        return self._model_pricing


def _make_telemetry(tmp_path, pricing_models=None):
    """Create a PromptTelemetry with an in-memory state backend.

    *pricing_models* is an optional dict of ``{model_id: {field: value}}``
    entries to seed the in-memory pricing table.
    """
    config = ConfigFactory.create(repo_root=tmp_path)
    state = _InMemoryState()
    if pricing_models:
        for model_id, fields in pricing_models.items():
            row = {"model_id": model_id, **fields}
            state._model_pricing.append(row)
    pricing = ModelPricingTable(state=state)
    telemetry = PromptTelemetry(config, pricing=pricing, state=state)
    return telemetry, state


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

    def test_parses_pi_model(self, tmp_path):
        tool, model = parse_command_tool_model(
            ["pi", "-p", "--mode", "json", "--model", "gpt-5.3-codex"]
        )
        assert tool == "pi"
        assert model == "gpt-5.3-codex"


class TestPromptTelemetry:
    def test_record_writes_inference_and_pr_rollup(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path)

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

        # Verify inference was appended
        assert len(state._inferences) == 1
        row = state._inferences[0]
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

        # Verify PR rollup stats
        pr = state.load_inference_stats("pr:101")
        assert pr is not None
        assert pr["inference_calls"] == 1
        assert pr["history_chars_saved"] == 100
        assert pr["context_chars_saved"] == 300
        assert pr["actual_usage_calls"] == 0

        lifetime = state.load_inference_stats("lifetime")
        assert lifetime is not None
        assert lifetime["inference_calls"] == 1
        assert lifetime["total_tokens"] == row["total_tokens"]

        session = state.load_inference_stats("session:sess-1")
        assert session is not None
        assert session["inference_calls"] == 1
        assert session["total_tokens"] == row["total_tokens"]

        issue = state.load_inference_stats("issue:42")
        assert issue is not None
        assert issue["inference_calls"] == 1

        source = state.load_inference_stats("source:reviewer")
        assert source is not None
        assert source["inference_calls"] == 1

    def test_record_prefers_actual_usage_when_available(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path)

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

        row = state._inferences[0]
        assert row["token_source"] == "actual"
        assert row["input_tokens"] == 123
        assert row["output_tokens"] == 77
        assert row["total_tokens"] == 200

        pr = state.load_inference_stats("pr:202")
        assert pr is not None
        assert pr["total_tokens"] == 200
        assert pr["actual_usage_calls"] == 1
        assert pr["usage_unavailable_calls"] == 0

        lifetime = state.load_inference_stats("lifetime")
        assert lifetime is not None
        assert lifetime["total_tokens"] == 200

        session = state.load_inference_stats("session:sess-2")
        assert session is not None
        assert session["total_tokens"] == 200

    def test_record_marks_usage_unavailable_when_backend_reports_none(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path)

        telemetry.record(
            source="triage",
            tool="pi",
            model="gpt-5.3-codex",
            issue_number=9,
            pr_number=0,
            session_id="sess-none",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=0.3,
            success=True,
            stats={
                "usage_status": "unavailable",
                "usage_available": False,
                "raw_usage": [
                    {"backend": "pi", "event_type": "agent_end", "payload": {}}
                ],
            },
        )

        row = state._inferences[0]
        assert row["usage_status"] == "unavailable"
        assert row["usage_available"] is False
        assert isinstance(row["raw_usage"], list)

        lifetime = state.load_inference_stats("lifetime")
        assert lifetime is not None
        assert lifetime["usage_unavailable_calls"] == 1

    def test_get_session_and_lifetime_totals(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path)
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
        pr_totals = telemetry.get_pr_totals(300)
        assert pr_totals is not None
        assert pr_totals["total_tokens"] == 70
        assert telemetry.get_issue_totals()[2]["total_tokens"] == 70
        assert telemetry.get_source_totals()["reviewer"]["total_tokens"] == 70

    def test_load_inferences_reads_recent_rows(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path)
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
        telemetry, state = _make_telemetry(tmp_path)
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

        row = state._inferences[0]
        assert row["status"] == "failed"
        assert row["token_source"] == "estimated"
        assert row["total_est_tokens"] == 0
        assert row["total_tokens"] == 0

    def test_record_prefers_explicit_pruned_counter_and_section_chars(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path)
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
        row = state._inferences[0]
        assert row["pruned_chars_total"] == 123
        assert row["section_chars"]["issue_body_before"] == 1000

        pr = state.load_inference_stats("pr:500")
        assert pr is not None
        assert pr["pruned_chars_total"] == 123

    def test_record_derives_pruned_counter_when_explicit_missing(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path)
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
        row = state._inferences[0]
        assert row["pruned_chars_total"] == 500

    def test_get_mtime_returns_zero_when_no_file(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path)
        assert telemetry.get_mtime() == 0.0

    def test_get_mtime_returns_positive_after_record(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path)
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=1,
            pr_number=0,
            session_id="s1",
            prompt_chars=10,
            transcript_chars=5,
            duration_seconds=0.1,
            success=True,
            stats={},
        )
        mtime = telemetry.get_mtime()
        assert mtime > 0.0

    def test_record_includes_estimated_cost_for_known_model(self, tmp_path):
        telemetry, state = _make_telemetry(
            tmp_path,
            pricing_models={
                "claude-sonnet-4-20250514": {
                    "input_cost_per_million": 3.0,
                    "output_cost_per_million": 15.0,
                    "aliases": ["sonnet"],
                }
            },
        )
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=50,
            pr_number=600,
            session_id="sess-cost",
            prompt_chars=800,
            transcript_chars=400,
            duration_seconds=1.0,
            success=True,
            stats={"input_tokens": 1000, "output_tokens": 500},
        )
        row = state._inferences[0]
        assert row["estimated_cost_usd"] is not None
        assert row["estimated_cost_usd"] > 0
        expected = (3.0 * 1000 + 15.0 * 500) / 1_000_000
        assert abs(row["estimated_cost_usd"] - expected) < 1e-6

    def test_record_cost_none_for_unknown_model(self, tmp_path):
        telemetry, state = _make_telemetry(tmp_path, pricing_models={})
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="unknown-model",
            issue_number=51,
            pr_number=601,
            session_id="sess-nocost",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=0.5,
            success=True,
            stats={},
        )
        row = state._inferences[0]
        assert row["estimated_cost_usd"] is None

    def test_cost_accumulates_across_records(self, tmp_path):
        telemetry, state = _make_telemetry(
            tmp_path,
            pricing_models={
                "claude-opus-4-20250514": {
                    "input_cost_per_million": 15.0,
                    "output_cost_per_million": 75.0,
                    "aliases": ["opus"],
                }
            },
        )
        for _ in range(3):
            telemetry.record(
                source="implementer",
                tool="claude",
                model="opus",
                issue_number=52,
                pr_number=700,
                session_id="sess-accum",
                prompt_chars=100,
                transcript_chars=50,
                duration_seconds=0.1,
                success=True,
                stats={"input_tokens": 1000, "output_tokens": 200},
            )
        pr = state.load_inference_stats("pr:700")
        assert pr is not None
        pr_cost = pr["estimated_cost_usd"]
        single_cost = (15.0 * 1000 + 75.0 * 200) / 1_000_000
        assert abs(pr_cost - round(single_cost * 3, 6)) < 1e-6


class TestAsFloat:
    def test_int_value(self):
        assert _as_float(42) == 42.0

    def test_float_value(self):
        assert _as_float(3.14) == 3.14

    def test_string_value(self):
        assert _as_float("2.5") == 2.5

    def test_invalid_string(self):
        assert _as_float("not_a_number") == 0.0

    def test_bool_value(self):
        assert _as_float(True) == 1.0

    def test_none_value(self):
        assert _as_float(None) == 0.0
