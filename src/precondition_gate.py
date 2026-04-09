"""Consumer-side precondition gate for pipeline phases (#6423).

Wraps :func:`stage_preconditions.check_preconditions` and
:class:`route_back.RouteBackCoordinator` into a single async primitive
that phases call before processing a batch of issues. The gate filters
out issues whose stage preconditions fail and routes them back to the
upstream stage in the same pass.

Why this is a separate class from ``IssueStore``:

- ``IssueStore.get_*`` methods are synchronous (in-memory queue ops).
- ``RouteBackCoordinator.route_back`` is async (label swaps + cache).
- Pushing the gate inside ``IssueStore`` would force its API async,
  cascading through every consumer.
- Keeping the gate as a separate concern means ``IssueStore`` stays
  pure data and the gate composes cleanly with the stage routing
  logic in ``implement_phase`` / ``review_phase``.

Usage in a phase::

    issues = self._store.get_implementable(max_count)
    issues = await self._gate.filter_and_route(issues, Stage.READY)
    # Only issues that passed all preconditions remain.
    for issue in issues:
        await self._process(issue)

The gate is opt-in via a constructor flag — phases can pass
``enabled=False`` (or omit the gate entirely) for environments where
the cache isn't populated yet, or for legacy code paths that haven't
been migrated.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from stage_preconditions import Stage, check_preconditions

if TYPE_CHECKING:
    from issue_cache import IssueCache
    from models import Task
    from route_back import RouteBackCoordinator

logger = logging.getLogger("hydraflow.precondition_gate")

__all__ = ["PreconditionGate"]


# Map of consumer Stage → upstream stage label to route back to on
# precondition failure. Used by the gate when constructing route_back
# arguments. Centralized here so phases don't need to know the
# pipeline topology.
_ROUTE_BACK_TARGETS: dict[Stage, str] = {
    Stage.READY: "plan",
    Stage.REVIEW: "ready",
}


class PreconditionGate:
    """Filter issues by stage preconditions, routing failures back upstream."""

    def __init__(
        self,
        *,
        cache: IssueCache,
        coordinator: RouteBackCoordinator,
        enabled: bool = True,
    ) -> None:
        """Build the gate.

        ``enabled=False`` makes :meth:`filter_and_route` a no-op pass-
        through — every issue is returned unchanged. Useful for the
        rollout period when the cache is partially populated and the
        gate would over-block legitimate work.
        """
        self._cache = cache
        self._coordinator = coordinator
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def filter_and_route(
        self,
        issues: Iterable[Task],
        stage: Stage,
    ) -> list[Task]:
        """Return only the issues that pass *stage*'s preconditions.

        Issues that fail are routed back via the coordinator. The
        route-back happens inline (awaited) so the next phase cycle
        sees the new label state. Errors during route-back are logged
        and the failing issue is dropped from the returned list — the
        caller never processes an issue that failed its gate, even
        if the route-back itself failed.
        """
        if not self._enabled:
            return list(issues)

        target_stage = _ROUTE_BACK_TARGETS.get(stage, "plan")
        passed: list[Task] = []
        for issue in issues:
            result = check_preconditions(self._cache, issue.id, stage)
            if result.ok:
                passed.append(issue)
                continue

            logger.info(
                "Precondition gate filtered issue #%d at stage %s: %s",
                issue.id,
                stage,
                result.reason,
            )
            try:
                await self._coordinator.route_back(
                    issue.id,
                    from_stage=str(stage),
                    to_stage=target_stage,
                    reason=result.reason,
                    feedback_context=result.reason,
                )
            except Exception:  # noqa: BLE001
                # Route-back coordinator already logs at warning. The
                # issue is still removed from this batch — the next
                # cycle will see the unchanged label and try the gate
                # again, which is the right retry behavior.
                logger.warning(
                    "PreconditionGate: route_back raised for issue #%d",
                    issue.id,
                    exc_info=True,
                )
        return passed
