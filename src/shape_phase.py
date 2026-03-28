"""Shape phase — propose product directions and await human selection."""

from __future__ import annotations

import asyncio
import logging
import re

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_store import IssueStore
from models import ProductDirection, ShapeResult, Task
from phase_utils import (
    _sentry_transaction,
    release_batch_in_flight,
    run_refilling_pool,
    store_lifecycle,
)
from pr_manager import PRManager
from state import StateTracker
from task_source import TaskTransitioner

logger = logging.getLogger("hydraflow.shape_phase")

# Marker comment prefix so we can detect shape options vs other comments
_SHAPE_OPTIONS_MARKER = "## Product Directions"
_DIRECTION_SELECTED_RE = re.compile(r"(?:direction|option)\s+([A-E])\b", re.IGNORECASE)


class ShapePhase:
    """Proposes product directions and waits for human/agent selection.

    Two-part loop:
    - Part A (generate): For issues newly in Shape, generate direction
      options and post as a structured comment.
    - Part B (poll): For issues awaiting a decision, poll for reply
      comments containing a selection. When found, parse the selection,
      enrich the issue, and transition to plan.
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
        # Track issues that have had options posted (awaiting selection)
        self._awaiting_selection: set[int] = set()

    async def shape_issues(self) -> bool:
        """Process shape-labeled issues. Returns True if work was done."""
        return await run_refilling_pool(
            store=self._store,
            fetch_fn=self._store.get_shapeable,
            work_fn=self._shape_single,
            max_slots=self._config.max_triage_workers,
            stop_event=self._stop_event,
            stage_name="shape",
            release_fn=release_batch_in_flight,
        )

    async def _shape_single(self, issue: Task) -> int:
        """Shape a single issue — generate options or check for selection."""
        with _sentry_transaction("pipeline.shape", f"shape:#{issue.id}"):
            async with store_lifecycle(self._store, issue.id, "shape"):
                # Check if options have already been posted
                enriched = await self._store.enrich_with_comments(issue)
                has_options = any(
                    _SHAPE_OPTIONS_MARKER in c for c in (enriched.comments or [])
                )

                if not has_options:
                    # Part A: Generate and post direction options
                    return await self._generate_options(issue)

                # Part B: Check for a selection in comments after the options
                selection = self._find_selection(enriched.comments or [])
                if selection:
                    return await self._process_selection(issue, selection)

                # No selection yet — re-enqueue for polling on next cycle
                self._store.enqueue_transition(issue, "shape")
                logger.debug("Issue #%d shape — awaiting direction selection", issue.id)
                return 0

    async def _generate_options(self, issue: Task) -> int:
        """Generate product direction options and post them."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SHAPE_UPDATE,
                data={"issue": issue.id, "action": "generating_options"},
            )
        )

        # Placeholder directions — will be replaced by multi-agent debate
        result = ShapeResult(
            issue_number=issue.id,
            directions=[
                ProductDirection(
                    name="Direction A",
                    approach="Pending shape agent integration",
                    tradeoffs="To be determined by shape agent",
                    effort="TBD",
                    risk="TBD",
                ),
            ],
            recommendation="Shape agent integration pending — manual direction selection required.",
        )

        comment = self._format_options(issue, result)
        if not self._config.dry_run:
            await self._transitioner.post_comment(issue.id, comment)
            self._awaiting_selection.add(issue.id)

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SHAPE_UPDATE,
                data={"issue": issue.id, "action": "options_posted"},
            )
        )
        logger.info(
            "Issue #%d shape — direction options posted, awaiting selection",
            issue.id,
        )
        # Re-enqueue so the poll part picks it up next cycle
        self._store.enqueue_transition(issue, "shape")
        return 1

    def _find_selection(self, comments: list[str]) -> str | None:
        """Look for a direction selection in comments after the options marker.

        Returns the selected direction letter (A-E) or None.
        """
        found_options = False
        for comment in comments:
            if _SHAPE_OPTIONS_MARKER in comment:
                found_options = True
                continue
            if found_options:
                match = _DIRECTION_SELECTED_RE.search(comment)
                if match:
                    return match.group(1).upper()
        return None

    async def _process_selection(self, issue: Task, selection: str) -> int:
        """Process a direction selection and transition to plan."""
        self._awaiting_selection.discard(issue.id)

        enrichment = (
            f"## Selected Product Direction\n\n"
            f"Direction {selection} was selected during product shaping.\n\n"
            f"This issue has been through the product discovery and shaping "
            f"track. The selected direction should inform the implementation plan."
        )

        if not self._config.dry_run:
            await self._transitioner.post_comment(issue.id, enrichment)
            self._store.enqueue_transition(issue, "plan")
            await self._transitioner.transition(issue.id, "plan")
            self._state.increment_session_counter("shaped")

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SHAPE_UPDATE,
                data={
                    "issue": issue.id,
                    "action": "direction_selected",
                    "direction": selection,
                },
            )
        )
        logger.info(
            "Issue #%d shape — direction %s selected → %s",
            issue.id,
            selection,
            self._config.planner_label[0],
        )
        return 1

    def _format_options(self, issue: Task, result: ShapeResult) -> str:
        """Format direction options as a structured GitHub comment."""
        lines = [
            f"{_SHAPE_OPTIONS_MARKER} for #{issue.id}",
            "",
        ]
        for i, direction in enumerate(result.directions):
            letter = chr(65 + i)  # A, B, C, ...
            lines.extend(
                [
                    f"### Direction {letter}: {direction.name}",
                    "",
                    f"**Approach:** {direction.approach}",
                    f"**Tradeoffs:** {direction.tradeoffs}",
                    f"**Effort:** {direction.effort} | **Risk:** {direction.risk}",
                ]
            )
            if direction.differentiator:
                lines.append(f"**Differentiator:** {direction.differentiator}")
            lines.append("")

        if result.recommendation:
            lines.extend(
                [
                    "### Recommendation",
                    "",
                    result.recommendation,
                    "",
                ]
            )

        lines.extend(
            [
                "---",
                "Reply with your selection (e.g. `Direction A`) and any refinements.",
                "The selected direction will be used to inform the implementation plan.",
            ]
        )
        return "\n".join(lines)
