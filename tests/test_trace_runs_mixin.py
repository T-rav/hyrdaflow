"""Tests for TraceRunsMixin — run_id allocation and active-run tracking."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

from state import StateTracker  # noqa: E402


@pytest.fixture
def tracker(tmp_path: Path) -> StateTracker:
    state_file = tmp_path / "state.json"
    return StateTracker(state_file=state_file)


class TestTraceRunsMixin:
    def test_first_run_id_is_one(self, tracker: StateTracker):
        run_id = tracker.begin_trace_run(42, "implement")
        assert run_id == 1

    def test_second_run_id_increments(self, tracker: StateTracker):
        run_id_1 = tracker.begin_trace_run(42, "implement")
        tracker.end_trace_run(42, "implement")
        run_id_2 = tracker.begin_trace_run(42, "implement")
        assert run_id_1 == 1
        assert run_id_2 == 2

    def test_different_phases_independent_counters(self, tracker: StateTracker):
        impl_id = tracker.begin_trace_run(42, "implement")
        plan_id = tracker.begin_trace_run(42, "plan")
        assert impl_id == 1
        assert plan_id == 1

    def test_different_issues_independent_counters(self, tracker: StateTracker):
        id_42 = tracker.begin_trace_run(42, "implement")
        id_99 = tracker.begin_trace_run(99, "implement")
        assert id_42 == 1
        assert id_99 == 1

    def test_run_id_persists_across_state_reload(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        tracker_1 = StateTracker(state_file=state_file)
        tracker_1.begin_trace_run(42, "implement")
        tracker_1.end_trace_run(42, "implement")

        tracker_2 = StateTracker(state_file=state_file)
        next_id = tracker_2.begin_trace_run(42, "implement")
        assert next_id == 2
