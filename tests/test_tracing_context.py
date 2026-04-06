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
    def test_construction_stores_fields(self):
        ctx = TracingContext(
            issue_number=42,
            phase="implement",
            source="implementer",
            run_id=1,
        )
        assert ctx.issue_number == 42
        assert ctx.phase == "implement"
        assert ctx.source == "implementer"
        assert ctx.run_id == 1

    def test_context_is_frozen(self):
        ctx = TracingContext(
            issue_number=42,
            phase="implement",
            source="implementer",
            run_id=1,
        )
        import dataclasses

        with __import__("pytest").raises(dataclasses.FrozenInstanceError):
            ctx.run_id = 999  # type: ignore[misc]
