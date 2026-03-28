"""Discover phase — product research for vague/broad issues."""

from __future__ import annotations

import asyncio
import logging

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_store import IssueStore
from models import DiscoverResult, Task
from phase_utils import (
    _sentry_transaction,
    release_batch_in_flight,
    run_refilling_pool,
    store_lifecycle,
)
from pr_manager import PRManager
from state import StateTracker
from task_source import TaskTransitioner

logger = logging.getLogger("hydraflow.discover_phase")


class DiscoverPhase:
    """Runs product discovery research on vague issues.

    Fetches issues from the discover queue, runs research (competitors,
    market gaps, user needs), posts a research brief as a comment, and
    transitions the issue to the shape stage.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        store: IssueStore,
        prs: PRManager,
        event_bus: EventBus,
        stop_event: asyncio.Event,
    ) -> None:
        self._config = config
        self._state = state
        self._store = store
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._bus = event_bus
        self._stop_event = stop_event

    async def discover_issues(self) -> bool:
        """Process discover-labeled issues. Returns True if work was done."""
        return await run_refilling_pool(
            store=self._store,
            fetch_fn=self._store.get_discoverable,
            work_fn=self._discover_single,
            max_slots=self._config.max_triage_workers,
            stop_event=self._stop_event,
            stage_name="discover",
            release_fn=release_batch_in_flight,
        )

    async def _discover_single(self, issue: Task) -> int:
        """Run product discovery for a single issue."""
        with _sentry_transaction("pipeline.discover", f"discover:#{issue.id}"):
            async with store_lifecycle(self._store, issue.id, "discover"):
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.DISCOVER_UPDATE,
                        data={"issue": issue.id, "action": "started"},
                    )
                )

                result = DiscoverResult(
                    issue_number=issue.id,
                    research_brief=(
                        "Product discovery research is pending agent integration. "
                        "This issue has been routed to the product track for "
                        "competitive analysis, user need identification, and "
                        "opportunity mapping."
                    ),
                    opportunities=["Pending research agent integration"],
                )

                # Post research brief as structured comment
                comment = self._format_research_brief(issue, result)
                if not self._config.dry_run:
                    await self._transitioner.post_comment(issue.id, comment)
                    self._store.enqueue_transition(issue, "shape")
                    await self._transitioner.transition(issue.id, "shape")
                    self._state.increment_session_counter("discovered")

                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.DISCOVER_UPDATE,
                        data={"issue": issue.id, "action": "completed"},
                    )
                )
                logger.info(
                    "Issue #%d discovery complete → %s",
                    issue.id,
                    self._config.shape_label[0],
                )
                return 1

    def _format_research_brief(self, issue: Task, result: DiscoverResult) -> str:
        """Format a research brief as a structured GitHub comment."""
        lines = [
            "## Product Discovery Brief",
            "",
            f"**Issue:** #{issue.id} — {issue.title}",
            "",
            "### Research Summary",
            "",
            result.research_brief,
            "",
        ]
        if result.competitors:
            lines.extend(["### Competitors Analyzed", ""])
            for comp in result.competitors:
                lines.append(f"- {comp}")
            lines.append("")
        if result.user_needs:
            lines.extend(["### User Needs Identified", ""])
            for need in result.user_needs:
                lines.append(f"- {need}")
            lines.append("")
        if result.opportunities:
            lines.extend(["### Opportunities", ""])
            for opp in result.opportunities:
                lines.append(f"- {opp}")
            lines.append("")
        lines.append("---")
        lines.append(
            "*This issue will proceed to product shaping for direction selection.*"
        )
        return "\n".join(lines)
