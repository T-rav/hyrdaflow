"""Tests for state._route_back.RouteBackStateMixin (#6423).

Exercises the per-issue route-back counter against a real
StateTracker backed by a tmp_path JSON file. Verifies get/increment/
reset semantics, restart persistence, and integration with the
RouteBackCoordinator via the RouteBackCounterPort protocol.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state import StateTracker
from tests.helpers import make_tracker

# ---------------------------------------------------------------------------
# get / increment / reset
# ---------------------------------------------------------------------------


class TestRouteBackCounter:
    def test_initial_count_is_zero(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_route_back_count(42) == 0

    def test_increment_returns_new_count(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.increment_route_back_count(42) == 1
        assert tracker.increment_route_back_count(42) == 2
        assert tracker.increment_route_back_count(42) == 3

    def test_get_reflects_incremented_value(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_route_back_count(42)
        tracker.increment_route_back_count(42)
        assert tracker.get_route_back_count(42) == 2

    def test_counters_independent_per_issue(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_route_back_count(1)
        tracker.increment_route_back_count(2)
        tracker.increment_route_back_count(1)
        assert tracker.get_route_back_count(1) == 2
        assert tracker.get_route_back_count(2) == 1

    def test_reset_clears_count(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_route_back_count(42)
        tracker.increment_route_back_count(42)
        tracker.reset_route_back_count(42)
        assert tracker.get_route_back_count(42) == 0

    def test_reset_unknown_issue_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        # Must not raise.
        tracker.reset_route_back_count(999)
        assert tracker.get_route_back_count(999) == 0

    def test_decrement_returns_new_count(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_route_back_count(42)
        tracker.increment_route_back_count(42)
        tracker.increment_route_back_count(42)
        assert tracker.decrement_route_back_count(42) == 2
        assert tracker.decrement_route_back_count(42) == 1
        assert tracker.decrement_route_back_count(42) == 0

    def test_decrement_below_zero_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        # Counter starts at 0; decrementing must not produce a negative.
        assert tracker.decrement_route_back_count(42) == 0
        assert tracker.decrement_route_back_count(42) == 0
        assert tracker.get_route_back_count(42) == 0

    def test_decrement_to_zero_clears_entry(self, tmp_path: Path) -> None:
        """Decrement-to-zero must remove the dict entry to keep the
        state JSON clean — leaving zero entries would bloat the state
        file over time as issues come and go."""
        tracker = make_tracker(tmp_path)
        tracker.increment_route_back_count(42)
        tracker.decrement_route_back_count(42)
        # Internal data dict should not have the key.
        assert "42" not in tracker._data.route_back_counts

    def test_decrement_persists_across_restart(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"

        tracker1 = StateTracker(state_file)
        tracker1.increment_route_back_count(42)
        tracker1.increment_route_back_count(42)
        tracker1.decrement_route_back_count(42)

        tracker2 = StateTracker(state_file)
        assert tracker2.get_route_back_count(42) == 1


# ---------------------------------------------------------------------------
# Persistence across restart
# ---------------------------------------------------------------------------


class TestRouteBackPersistence:
    def test_counter_survives_restart(self, tmp_path: Path) -> None:
        """Increment on one tracker, construct a fresh tracker against
        the same state file, counter is still there."""
        state_file = tmp_path / "state.json"

        tracker1 = StateTracker(state_file)
        tracker1.increment_route_back_count(42)
        tracker1.increment_route_back_count(42)

        tracker2 = StateTracker(state_file)
        assert tracker2.get_route_back_count(42) == 2

    def test_reset_survives_restart(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"

        tracker1 = StateTracker(state_file)
        tracker1.increment_route_back_count(42)
        tracker1.increment_route_back_count(42)
        tracker1.reset_route_back_count(42)

        tracker2 = StateTracker(state_file)
        assert tracker2.get_route_back_count(42) == 0

    def test_empty_state_file_has_no_counters(self, tmp_path: Path) -> None:
        tracker = StateTracker(tmp_path / "state.json")
        assert tracker.get_route_back_count(42) == 0


# ---------------------------------------------------------------------------
# RouteBackCounterPort satisfaction
# ---------------------------------------------------------------------------


class TestPortProtocolCompatibility:
    """StateTracker must satisfy RouteBackCounterPort so it can be
    passed to RouteBackCoordinator without an adapter class."""

    def test_state_tracker_has_port_methods(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert hasattr(tracker, "get_route_back_count")
        assert hasattr(tracker, "increment_route_back_count")
        # Both methods are callable and return int.
        assert isinstance(tracker.get_route_back_count(42), int)
        assert isinstance(tracker.increment_route_back_count(42), int)

    def test_state_tracker_is_structural_port(self, tmp_path: Path) -> None:
        """Use runtime_checkable Protocol to confirm structural match."""
        from route_back import RouteBackCounterPort

        tracker = make_tracker(tmp_path)
        assert isinstance(tracker, RouteBackCounterPort)
