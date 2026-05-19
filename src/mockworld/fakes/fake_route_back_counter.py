"""FakeRouteBackCounter — RouteBackCounterPort impl for MockWorld and unit tests.

Mirrors ``state._route_back.RouteBackStateMixin`` semantics: get starts at 0,
increment returns the new value, decrement-to-zero clears the entry,
decrement-below-zero is a no-op.

Promoted from ``tests/helpers.InMemoryRouteBackCounter`` (ADR-0047) so the
fake-coverage auditor can discover it and scenario harnesses can use it
without importing from the test tree.
"""

from __future__ import annotations


class FakeRouteBackCounter:
    """In-memory ``RouteBackCounterPort`` implementation for MockWorld.

    Semantics match ``state._route_back.RouteBackStateMixin``:

    - :meth:`get_route_back_count` returns 0 for unknown issue IDs.
    - :meth:`increment_route_back_count` increments and returns the new value.
    - :meth:`decrement_route_back_count` decrements and returns the new value;
      decrementing to zero clears the entry; decrementing below zero is a
      no-op returning 0.
    """

    _is_fake_adapter = True

    def __init__(self) -> None:
        self._counts: dict[int, int] = {}

    def get_route_back_count(self, issue_id: int) -> int:
        """Return the current route-back count for *issue_id* (0 if unset)."""
        return self._counts.get(issue_id, 0)

    def increment_route_back_count(self, issue_id: int) -> int:
        """Increment and return the new route-back count for *issue_id*."""
        new = self._counts.get(issue_id, 0) + 1
        self._counts[issue_id] = new
        return new

    def decrement_route_back_count(self, issue_id: int) -> int:
        """Decrement and return the new route-back count for *issue_id*.

        Decrementing to zero clears the entry. Decrementing when the counter
        is already at 0 is a no-op and returns 0.
        """
        current = self._counts.get(issue_id, 0)
        if current <= 0:
            return 0
        new = current - 1
        if new == 0:
            self._counts.pop(issue_id, None)
        else:
            self._counts[issue_id] = new
        return new
