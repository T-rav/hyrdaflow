"""Route-back counter state (#6423).

Implements the :class:`~route_back.RouteBackCounterPort` protocol
against the existing JSON-backed ``StateTracker`` so the per-issue
route-back counter survives restart. Without persistence, a crash
mid-pipeline would reset the counter and let an issue oscillate
between stages indefinitely.

Minimal mixin: two methods (get + increment) and a clear method for
test cleanup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class RouteBackStateMixin:
    """Per-issue route-back counter — satisfies RouteBackCounterPort."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker; noqa: ARG004

    def get_route_back_count(self, issue_id: int) -> int:
        """Return the current route-back count for *issue_id* (0 if none)."""
        return self._data.route_back_counts.get(self._key(issue_id), 0)

    def increment_route_back_count(self, issue_id: int) -> int:
        """Increment and return the new route-back count for *issue_id*.

        Persists to the state JSON file immediately so the counter
        survives a crash between the increment and any downstream
        label swap. If the coordinator later fails its label swap,
        the counter stays incremented — the next route-back attempt
        will see a count one higher, which nudges the issue toward
        HITL escalation faster. That's the conservative choice:
        better to escalate prematurely than to loop forever.
        """
        key = self._key(issue_id)
        new = self._data.route_back_counts.get(key, 0) + 1
        self._data.route_back_counts[key] = new
        self.save()
        return new

    def decrement_route_back_count(self, issue_id: int) -> int:
        """Decrement and return the new route-back count for *issue_id*.

        No-op when the counter is already at 0. Used by
        :class:`~route_back.RouteBackCoordinator` to undo an increment
        when the label swap that the counter was tracking fails — see
        ``RouteBackCounterPort.decrement_route_back_count`` for the
        rationale.
        """
        key = self._key(issue_id)
        current = self._data.route_back_counts.get(key, 0)
        if current <= 0:
            return 0
        new = current - 1
        if new == 0:
            self._data.route_back_counts.pop(key, None)
        else:
            self._data.route_back_counts[key] = new
        self.save()
        return new

    def reset_route_back_count(self, issue_id: int) -> None:
        """Clear the route-back counter for *issue_id*.

        Called after a successful phase transition (e.g. a plan passes
        its review) so a subsequent unrelated route-back on the same
        issue starts fresh at 1.
        """
        if self._key(issue_id) in self._data.route_back_counts:
            self._data.route_back_counts.pop(self._key(issue_id))
            self.save()
