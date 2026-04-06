"""Tests for tracing_context — phase mapping and run-state dataclass."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tracing_context import TracingContext, source_to_phase  # noqa: E402


class TestSourceToPhase:
    def test_implementer_maps_to_implement(self):
        assert source_to_phase("implementer") == "implement"

    def test_planner_maps_to_plan(self):
        assert source_to_phase("planner") == "plan"

    def test_reviewer_and_review_fixer_map_to_review(self):
        assert source_to_phase("reviewer") == "review"
        assert source_to_phase("review_fixer") == "review"

    def test_triage_and_decomposition_map_to_triage(self):
        assert source_to_phase("triage") == "triage"
        assert source_to_phase("decomposition") == "triage"

    def test_hitl_maps_to_hitl(self):
        assert source_to_phase("hitl") == "hitl"

    def test_unknown_source_passes_through(self):
        assert source_to_phase("sentry_ingest") == "sentry_ingest"
        assert source_to_phase("custom_thing") == "custom_thing"


class TestTracingContext:
    def test_construction_defaults_subprocess_to_zero(self):
        ctx = TracingContext(
            issue_number=42,
            phase="implement",
            source="implementer",
            run_id=1,
        )
        assert ctx.subprocess_idx == 0

    def test_next_subprocess_increments_idx(self):
        ctx = TracingContext(
            issue_number=42,
            phase="implement",
            source="implementer",
            run_id=1,
        )
        next_ctx = ctx.next_subprocess()
        assert next_ctx.subprocess_idx == 1
        assert next_ctx.issue_number == 42
        assert next_ctx.phase == "implement"
        assert next_ctx.run_id == 1

    def test_next_subprocess_does_not_mutate_original(self):
        ctx = TracingContext(
            issue_number=42,
            phase="implement",
            source="implementer",
            run_id=1,
        )
        ctx.next_subprocess()
        assert ctx.subprocess_idx == 0

    def test_chained_next_subprocess(self):
        ctx = TracingContext(
            issue_number=1, phase="implement", source="implementer", run_id=1
        )
        chained = ctx.next_subprocess().next_subprocess().next_subprocess()
        assert chained.subprocess_idx == 3
