"""Conformance and behavioral tests for FakeRouteBackCounter (ADR-0047).

Verifies:
1. Protocol conformance — isinstance check against RouteBackCounterPort.
2. _is_fake_adapter marker present.
3. Behavioral contract matching RouteBackStateMixin semantics.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mockworld.fakes.fake_route_back_counter import FakeRouteBackCounter
from route_back import RouteBackCounterPort


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


class TestFakeRouteBackCounterConformance:
    def test_satisfies_protocol(self) -> None:
        """isinstance check passes because RouteBackCounterPort is @runtime_checkable."""
        fake = FakeRouteBackCounter()
        assert isinstance(fake, RouteBackCounterPort)

    def test_is_fake_adapter_marker(self) -> None:
        """_is_fake_adapter must be True so the auditor can discover the fake."""
        assert FakeRouteBackCounter._is_fake_adapter is True


# ---------------------------------------------------------------------------
# Behavioral: get
# ---------------------------------------------------------------------------


class TestGetRouteBackCount:
    def test_unknown_issue_returns_zero(self) -> None:
        fake = FakeRouteBackCounter()
        assert fake.get_route_back_count(99) == 0

    def test_returns_current_count_after_increments(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(1)
        fake.increment_route_back_count(1)
        assert fake.get_route_back_count(1) == 2

    def test_independent_across_issue_ids(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(1)
        fake.increment_route_back_count(1)
        fake.increment_route_back_count(2)
        assert fake.get_route_back_count(1) == 2
        assert fake.get_route_back_count(2) == 1
        assert fake.get_route_back_count(3) == 0


# ---------------------------------------------------------------------------
# Behavioral: increment
# ---------------------------------------------------------------------------


class TestIncrementRouteBackCount:
    def test_first_increment_returns_one(self) -> None:
        fake = FakeRouteBackCounter()
        assert fake.increment_route_back_count(42) == 1

    def test_second_increment_returns_two(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(42)
        assert fake.increment_route_back_count(42) == 2

    def test_increments_are_per_issue(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(1)
        fake.increment_route_back_count(1)
        fake.increment_route_back_count(2)
        assert fake.increment_route_back_count(1) == 3
        assert fake.increment_route_back_count(2) == 2


# ---------------------------------------------------------------------------
# Behavioral: decrement
# ---------------------------------------------------------------------------


class TestDecrementRouteBackCount:
    def test_decrement_from_zero_is_noop_returns_zero(self) -> None:
        fake = FakeRouteBackCounter()
        assert fake.decrement_route_back_count(5) == 0

    def test_decrement_to_zero_clears_entry(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(7)
        result = fake.decrement_route_back_count(7)
        assert result == 0
        # After clearing, get should return 0
        assert fake.get_route_back_count(7) == 0

    def test_decrement_from_two_returns_one(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(3)
        fake.increment_route_back_count(3)
        assert fake.decrement_route_back_count(3) == 1
        assert fake.get_route_back_count(3) == 1

    def test_multiple_decrements_reach_zero(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(10)
        fake.increment_route_back_count(10)
        fake.increment_route_back_count(10)
        fake.decrement_route_back_count(10)
        fake.decrement_route_back_count(10)
        result = fake.decrement_route_back_count(10)
        assert result == 0
        assert fake.get_route_back_count(10) == 0

    def test_decrement_does_not_go_below_zero(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(20)
        fake.decrement_route_back_count(20)
        # Now at 0; further decrements must not produce negative values
        assert fake.decrement_route_back_count(20) == 0
        assert fake.decrement_route_back_count(20) == 0

    def test_decrement_is_per_issue(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(1)
        fake.increment_route_back_count(2)
        fake.increment_route_back_count(2)
        fake.decrement_route_back_count(2)
        assert fake.get_route_back_count(1) == 1
        assert fake.get_route_back_count(2) == 1


# ---------------------------------------------------------------------------
# Behavioral: rollback pattern (increment then decrement on failure)
# ---------------------------------------------------------------------------


class TestRollbackPattern:
    def test_rollback_undoes_increment(self) -> None:
        """Coordinator increments, label swap fails, coordinator decrements."""
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(99)
        assert fake.get_route_back_count(99) == 1
        fake.decrement_route_back_count(99)
        assert fake.get_route_back_count(99) == 0

    def test_two_increments_one_rollback_leaves_one(self) -> None:
        fake = FakeRouteBackCounter()
        fake.increment_route_back_count(99)
        fake.increment_route_back_count(99)
        fake.decrement_route_back_count(99)
        assert fake.get_route_back_count(99) == 1
