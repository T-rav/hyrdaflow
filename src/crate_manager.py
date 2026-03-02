"""Active crate lifecycle management for the crate-gated pipeline."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from events import EventType, HydraFlowEvent

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from models import Task
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.crate_manager")


class CrateManager:
    """Manages the active crate lifecycle and gating logic.

    The pipeline processes one crate at a time.  ``is_in_active_crate``
    is the single gate: if a task does not belong to the active crate,
    it stays in the queue.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = pr_manager
        self._bus = event_bus

    @property
    def active_crate_number(self) -> int | None:
        """The currently active crate (milestone) number, or None."""
        return self._state.get_active_crate_number()

    def is_in_active_crate(self, task: Task) -> bool:
        """Return True if *task* belongs to the active crate.

        Returns False when there is no active crate or when the task
        has no milestone assigned.
        """
        active = self.active_crate_number
        if active is None:
            return False
        milestone = task.metadata.get("milestone_number")
        return milestone == active

    async def activate_crate(self, number: int) -> None:
        """Set *number* as the active crate, persist, and publish an event."""
        self._state.set_active_crate_number(number)
        logger.info("Activated crate #%d", number)
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.CRATE_ACTIVATED,
                data={"crate_number": number},
            )
        )

    async def check_and_advance(self) -> None:
        """If the active crate is done, advance to the next open crate.

        A crate is considered done when its ``open_issues`` count is 0.
        The next crate is the open milestone with the lowest number.
        If no next crate exists, the active crate is cleared and the
        pipeline idles.
        """
        active = self.active_crate_number
        if active is None:
            return

        try:
            crates = await self._prs.list_milestones(state="open")
        except Exception:
            logger.exception("Failed to list milestones during crate advancement")
            return

        current = next((c for c in crates if c.number == active), None)
        if current is None or current.open_issues > 0:
            return

        # Current crate is done
        logger.info("Crate #%d completed (0 open issues)", active)
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.CRATE_COMPLETED,
                data={"crate_number": active},
            )
        )

        # Find next open crate (lowest number, excluding the just-completed one)
        candidates = sorted(
            (c for c in crates if c.number != active and c.open_issues > 0),
            key=lambda c: c.number,
        )
        if candidates:
            await self.activate_crate(candidates[0].number)
        else:
            self._state.set_active_crate_number(None)
            logger.info("No more open crates — pipeline will idle")

    async def _next_crate_title(self) -> str:
        """Generate the next ``YYYY-MM-DD.N`` crate title.

        Inspects existing milestones to find the highest iteration for
        today's date prefix, then returns the next one.
        """
        date_prefix = datetime.now(UTC).strftime("%Y-%m-%d")
        max_iter = 0
        try:
            milestones = await self._prs.list_milestones(state="all")
            for m in milestones:
                t = (m.title or "").strip()
                if t == date_prefix:
                    max_iter = max(max_iter, 1)
                elif t.startswith(f"{date_prefix}."):
                    suffix = t[len(date_prefix) + 1 :]
                    if suffix.isdigit():
                        max_iter = max(max_iter, int(suffix))
        except Exception:
            logger.debug("Could not list milestones for title generation")
        return f"{date_prefix}.{max_iter + 1}"

    async def auto_package_if_needed(self, uncrated: list[Task]) -> None:
        """When ``auto_crate`` is enabled and there is no active crate, create one.

        Creates a milestone named ``YYYY-MM-DD.N``, assigns all
        *uncrated* issues to it, and activates it.
        """
        if not self._config.auto_crate:
            return
        if self.active_crate_number is not None:
            return
        if not uncrated:
            return

        title = await self._next_crate_title()
        try:
            crate = await self._prs.create_milestone(title)
        except Exception:
            logger.exception("Failed to create auto-crate milestone")
            return

        for task in uncrated:
            try:
                await self._prs.set_issue_milestone(task.id, crate.number)
            except Exception:
                logger.warning(
                    "Failed to assign issue #%d to crate #%d",
                    task.id,
                    crate.number,
                )

        await self.activate_crate(crate.number)
        logger.info(
            "Auto-packaged %d issues into crate #%d (%s)",
            len(uncrated),
            crate.number,
            title,
        )
