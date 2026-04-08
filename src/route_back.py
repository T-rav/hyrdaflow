"""Route-back coordinator — pipeline state-machine route-back primitive (#6423).

When a precondition gate fails (``stage_preconditions.check_preconditions``
returns not-ok), the affected issue must NOT be silently dropped from
the work queue. Instead, it gets routed back to its previous stage with
the failure reason as feedback context, so the upstream phase can fix
its output and try again.

This module provides ``RouteBackCoordinator``, a small coordinator that
ties together the four things a route-back has to do:

  1. **Swap pipeline labels** on the GitHub issue (e.g. ``hydraflow-ready``
     → ``hydraflow-plan``) so the upstream phase will pick it up next
     cycle.
  2. **Write a structured ``route_back`` record** to the issue cache so
     the audit trail and the upstream phase can read the feedback context.
  3. **Increment a per-issue route-back counter**, persisted via the
     state tracker so the counter survives restarts.
  4. **Escalate to HITL** when the counter exceeds ``max_route_backs`` —
     prevents an issue from oscillating between stages forever.

The coordinator is independent of any specific phase: ``plan_phase``,
``implement_phase``, and ``review_phase`` all call the same
``route_back()`` method with their stage labels. This keeps the routing
policy in one place.

Companion to ``stage_preconditions``, ``IssueCache``, and ``PRPort``.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from issue_cache import IssueCache
    from ports import PRPort

logger = logging.getLogger("hydraflow.route_back")

__all__ = [
    "RouteBackCoordinator",
    "RouteBackCounterPort",
    "RouteBackOutcome",
    "RouteBackResult",
]


class RouteBackOutcome(StrEnum):
    """The disposition of a route-back attempt."""

    # The issue was routed back to the upstream stage; the counter is
    # below the cap and the upstream phase will pick it up next cycle.
    ROUTED = "routed"
    # The route-back counter exceeded ``max_route_backs``; the issue
    # was escalated to HITL instead of being routed back again.
    ESCALATED = "escalated"
    # An unexpected failure during the route-back itself (label swap
    # raised, cache write raised). Logged at warning, returned for
    # caller awareness — the issue stays in its current state.
    FAILED = "failed"


class RouteBackResult:
    """Outcome of a route-back attempt + the new counter value."""

    __slots__ = ("outcome", "counter", "reason")

    def __init__(
        self,
        outcome: RouteBackOutcome,
        counter: int,
        reason: str = "",
    ) -> None:
        self.outcome = outcome
        self.counter = counter
        self.reason = reason

    def __repr__(self) -> str:
        return (
            f"RouteBackResult(outcome={self.outcome}, "
            f"counter={self.counter}, reason={self.reason!r})"
        )


@runtime_checkable
class RouteBackCounterPort(Protocol):
    """Port for the per-issue route-back counter store.

    Lets the coordinator stay decoupled from ``StateTracker`` so it
    can be tested with a tiny in-memory dict implementation. The full
    StateTracker integration lives in the phase wiring follow-up.
    """

    def get_route_back_count(self, issue_id: int) -> int:
        """Return the current route-back count for *issue_id*."""
        ...

    def increment_route_back_count(self, issue_id: int) -> int:
        """Increment and return the new route-back count for *issue_id*."""
        ...

    def decrement_route_back_count(self, issue_id: int) -> int:
        """Decrement and return the new route-back count for *issue_id*.

        Used by the coordinator to undo an increment when a label swap
        fails after the counter was already incremented — without this
        rollback, transient ``gh`` network blips would burn through the
        route-back budget without any actual route-back happening.

        Must be a no-op (return 0) when the counter is already at 0.
        """
        ...


class RouteBackCoordinator:
    """Coordinates label swap + cache record + counter + escalation."""

    def __init__(
        self,
        *,
        cache: IssueCache,
        prs: PRPort,
        counter: RouteBackCounterPort,
        hitl_label: str,
        max_route_backs: int = 2,
    ) -> None:
        """Build the coordinator.

        ``hitl_label`` is the GitHub label applied when the counter
        exceeds the cap (e.g. ``"hydraflow-hitl"``). ``max_route_backs``
        is the soft cap — once an issue has been routed back this many
        times, the next route-back attempt escalates instead.
        """
        self._cache = cache
        self._prs = prs
        self._counter = counter
        self._hitl_label = hitl_label
        self._max_route_backs = max_route_backs

    @property
    def max_route_backs(self) -> int:
        return self._max_route_backs

    async def route_back(
        self,
        issue_id: int,
        *,
        from_stage: str,
        to_stage: str,
        reason: str,
        feedback_context: str = "",
    ) -> RouteBackResult:
        """Route *issue_id* from ``from_stage`` back to ``to_stage``.

        Returns a :class:`RouteBackResult` describing the outcome:

        - ``ROUTED``: the issue was routed back; the upstream phase
          will pick it up on its next cycle. The cache has a
          ``route_back`` record with the feedback context.
        - ``ESCALATED``: the counter is now above ``max_route_backs``;
          the issue was labeled HITL instead of being routed back
          again. The cache record still gets written so the audit
          trail records the attempted route-back.
        - ``FAILED``: an exception fired during the label swap or
          cache write. The issue is left in its current state and
          the caller can retry next cycle.

        The counter is incremented before the cap check, so the very
        first route-back gets count=1; ``max_route_backs=2`` means the
        third attempt escalates.
        """
        try:
            new_count = self._counter.increment_route_back_count(issue_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "route_back: counter increment failed for issue #%d: %s",
                issue_id,
                exc,
            )
            return RouteBackResult(
                RouteBackOutcome.FAILED,
                counter=0,
                reason=f"counter increment failed: {exc}",
            )

        # Always record the route-back attempt in the audit trail —
        # whether it advances or escalates, the upstream phase needs
        # to see the feedback context on the next cycle.
        try:
            self._cache.record_route_back(
                issue_id,
                from_stage=from_stage,
                to_stage=to_stage,
                reason=reason,
                feedback_context=feedback_context,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "route_back: cache write failed for issue #%d: %s",
                issue_id,
                exc,
            )
            # Cache write is best-effort — proceed with the label swap
            # even if the audit trail couldn't be persisted. Phase code
            # already logs failures via the cache module itself.

        if new_count > self._max_route_backs:
            # Cap exceeded — escalate to HITL instead of routing back.
            return await self._escalate(
                issue_id,
                from_stage=from_stage,
                reason=reason,
                counter=new_count,
            )

        # Under the cap — perform the label swap and return ROUTED.
        try:
            await self._prs.swap_pipeline_labels(issue_id, to_stage)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "route_back: label swap failed for issue #%d: %s",
                issue_id,
                exc,
            )
            # Undo the counter increment — the label swap was the
            # action being counted, and it didn't happen. Without
            # this rollback, two consecutive label-swap failures
            # (e.g. transient `gh` network blips) would burn through
            # the route-back budget and trigger spurious HITL escalation.
            try:
                rolled_back = self._counter.decrement_route_back_count(issue_id)
            except Exception as decrement_exc:  # noqa: BLE001
                logger.warning(
                    "route_back: counter rollback failed for issue #%d: %s",
                    issue_id,
                    decrement_exc,
                )
                rolled_back = new_count
            return RouteBackResult(
                RouteBackOutcome.FAILED,
                counter=rolled_back,
                reason=f"label swap failed: {exc}",
            )

        logger.info(
            "Issue #%d routed back %s → %s (count=%d/%d): %s",
            issue_id,
            from_stage,
            to_stage,
            new_count,
            self._max_route_backs,
            reason,
        )
        return RouteBackResult(
            RouteBackOutcome.ROUTED,
            counter=new_count,
            reason=reason,
        )

    async def _escalate(
        self,
        issue_id: int,
        *,
        from_stage: str,
        reason: str,
        counter: int,
    ) -> RouteBackResult:
        """Apply the HITL label and return an ESCALATED result."""
        try:
            await self._prs.swap_pipeline_labels(issue_id, self._hitl_label)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "route_back: HITL escalation label swap failed for issue #%d: %s",
                issue_id,
                exc,
            )
            return RouteBackResult(
                RouteBackOutcome.FAILED,
                counter=counter,
                reason=f"escalation label swap failed: {exc}",
            )

        escalation_reason = (
            f"route-back cap exceeded after {counter} attempts "
            f"(max={self._max_route_backs}); last reason from "
            f"{from_stage}: {reason}"
        )
        logger.warning(
            "Issue #%d escalated to HITL after %d route-backs: %s",
            issue_id,
            counter,
            reason,
        )
        return RouteBackResult(
            RouteBackOutcome.ESCALATED,
            counter=counter,
            reason=escalation_reason,
        )
