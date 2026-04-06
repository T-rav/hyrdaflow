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

    def test_get_active_returns_run_id(self, tracker: StateTracker):
        tracker.begin_trace_run(42, "implement")
        assert tracker.get_active_trace_run(42, "implement") == 1

    def test_get_active_returns_none_when_not_started(self, tracker: StateTracker):
        assert tracker.get_active_trace_run(42, "implement") is None

    def test_get_active_returns_none_after_end(self, tracker: StateTracker):
        tracker.begin_trace_run(42, "implement")
        tracker.end_trace_run(42, "implement")
        assert tracker.get_active_trace_run(42, "implement") is None

    def test_run_id_persists_across_state_reload(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        tracker_1 = StateTracker(state_file=state_file)
        tracker_1.begin_trace_run(42, "implement")
        tracker_1.end_trace_run(42, "implement")

        tracker_2 = StateTracker(state_file=state_file)
        next_id = tracker_2.begin_trace_run(42, "implement")
        assert next_id == 2

    def test_active_runs_persist_across_reload(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        tracker_1 = StateTracker(state_file=state_file)
        tracker_1.begin_trace_run(42, "implement")

        tracker_2 = StateTracker(state_file=state_file)
        active = tracker_2.get_active_trace_run(42, "implement")
        assert active == 1

    def test_list_active_runs(self, tracker: StateTracker):
        tracker.begin_trace_run(42, "implement")
        tracker.begin_trace_run(99, "plan")
        active = tracker.list_active_trace_runs()
        assert (42, "implement", 1) in active
        assert (99, "plan", 1) in active
        assert len(active) == 2


class TestPurgeStaleTraceRuns:
    def _backdate_active(
        self,
        tracker: StateTracker,
        issue: int,
        phase: str,
        seconds_ago: float,
    ) -> None:
        from datetime import UTC, datetime, timedelta

        key = f"{issue}:{phase}"
        active = tracker._data.trace_runs["active"]  # type: ignore[index]
        backdated = datetime.now(UTC) - timedelta(seconds=seconds_ago)
        active[key]["started_at"] = backdated.isoformat()  # type: ignore[index]
        tracker.save()

    def test_purge_evicts_stale_entries(self, tracker: StateTracker):
        tracker.begin_trace_run(42, "implement")
        self._backdate_active(tracker, 42, "implement", seconds_ago=3600)

        evicted = tracker.purge_stale_trace_runs(max_age_seconds=600.0)

        assert evicted == [(42, "implement", 1)]
        assert tracker.get_active_trace_run(42, "implement") is None

    def test_purge_preserves_fresh_entries(self, tracker: StateTracker):
        tracker.begin_trace_run(42, "implement")
        # Started just now — well under any reasonable max age
        evicted = tracker.purge_stale_trace_runs(max_age_seconds=600.0)
        assert evicted == []
        assert tracker.get_active_trace_run(42, "implement") == 1

    def test_purge_evicts_only_stale_subset(self, tracker: StateTracker):
        tracker.begin_trace_run(42, "implement")
        tracker.begin_trace_run(99, "plan")
        self._backdate_active(tracker, 42, "implement", seconds_ago=7200)

        evicted = tracker.purge_stale_trace_runs(max_age_seconds=600.0)

        assert evicted == [(42, "implement", 1)]
        assert tracker.get_active_trace_run(42, "implement") is None
        assert tracker.get_active_trace_run(99, "plan") == 1

    def test_purge_persists_to_state_file(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        tracker_1 = StateTracker(state_file=state_file)
        tracker_1.begin_trace_run(42, "implement")
        self._backdate_active(tracker_1, 42, "implement", seconds_ago=7200)
        tracker_1.purge_stale_trace_runs(max_age_seconds=600.0)

        # Reload and verify the stale entry stayed evicted
        tracker_2 = StateTracker(state_file=state_file)
        assert tracker_2.get_active_trace_run(42, "implement") is None

    def test_purge_drops_malformed_entry(self, tracker: StateTracker):
        tracker.begin_trace_run(42, "implement")
        # Corrupt the started_at field
        active = tracker._data.trace_runs["active"]  # type: ignore[index]
        active["42:implement"]["started_at"] = "not-a-date"  # type: ignore[index]
        tracker.save()

        tracker.purge_stale_trace_runs(max_age_seconds=600.0)
        assert tracker.get_active_trace_run(42, "implement") is None

    def test_purge_tolerates_naive_datetime(self, tracker: StateTracker):
        """Hand-edited or migrated state files may carry a naive ISO string.
        Subtracting an aware ``now`` from a naive ``started`` raises
        TypeError; the purge must coerce naive → UTC instead of crashing
        and leaking remaining keys.
        """
        from datetime import datetime, timedelta

        tracker.begin_trace_run(42, "implement")
        tracker.begin_trace_run(99, "plan")  # second key must still be processed

        active = tracker._data.trace_runs["active"]  # type: ignore[index]
        # Naive datetime, well past any stale window
        naive_old = datetime.now() - timedelta(hours=24)  # noqa: DTZ005
        active["42:implement"]["started_at"] = naive_old.isoformat()  # type: ignore[index]
        tracker.save()

        evicted = tracker.purge_stale_trace_runs(max_age_seconds=600.0)

        assert (42, "implement", 1) in evicted
        assert tracker.get_active_trace_run(42, "implement") is None
        # The fresh second entry must survive — proves the loop did not
        # abort partway through.
        assert tracker.get_active_trace_run(99, "plan") == 1
