"""Triage phase — evaluate find-labeled issues and route them."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_store import IssueStore
from models import Task
from phase_utils import (
    adr_validation_reasons,
    escalate_to_hitl,
    is_adr_issue_title,
    release_batch_in_flight,
    run_concurrent_batch,
    store_lifecycle,
)
from pr_manager import PRManager
from state import StateTracker
from task_source import TaskTransitioner
from triage import TriageRunner

if TYPE_CHECKING:
    from epic import EpicManager

logger = logging.getLogger("hydraflow.triage_phase")


class TriagePhase:
    """Evaluates ``find_label`` issues and routes them to plan or HITL."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        store: IssueStore,
        triage: TriageRunner,
        prs: PRManager,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        epic_manager: EpicManager | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._store = store
        self._triage = triage
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._bus = event_bus
        self._stop_event = stop_event
        self._epic_manager = epic_manager

    def _enrich_parent_epic(self, issue: Task) -> None:
        """Set the parent_epic field if this issue belongs to a tracked epic."""
        if self._epic_manager is None:
            return
        parents = self._epic_manager.find_parent_epics(issue.id)
        if parents:
            issue.parent_epic = parents[0]

    async def triage_issues(self) -> int:
        """Evaluate ``find_label`` issues and route them.

        Issues with enough context go to ``planner_label`` (planning).
        Issues lacking detail are escalated to ``hitl_label`` with a
        comment explaining what is missing so the dashboard surfaces
        them as "needs attention".
        """
        issues = self._store.get_triageable(self._config.batch_size)
        if not issues:
            return 0

        logger.info("Triaging %d found issues", len(issues))
        semaphore = asyncio.Semaphore(self._config.max_triagers)

        async def _triage_one(idx: int, issue: Task) -> int:
            if self._stop_event.is_set():
                return 0

            async with semaphore:
                if self._stop_event.is_set():
                    return 0

                # Enrich with parent epic reference if this is a child issue
                self._enrich_parent_epic(issue)

                async with store_lifecycle(self._store, issue.id, "find"):
                    # ADR draft issues are already scoped/planned; validate shape and
                    # route directly to implementation (ready queue).
                    if is_adr_issue_title(issue.title):
                        if self._config.dry_run:
                            return 1
                        reasons = adr_validation_reasons(issue.body)
                        if reasons:
                            await self._escalate_triage_issue(issue.id, reasons)
                            logger.info(
                                "Issue #%d ADR triage → %s (invalid ADR shape: %s)",
                                issue.id,
                                self._config.hitl_label[0],
                                "; ".join(reasons),
                            )
                        else:
                            await self._transitioner.transition(issue.id, "ready")
                            self._store.enqueue_transition(issue, "ready")
                            self._state.increment_session_counter("triaged")
                            logger.info(
                                "Issue #%d ADR triage → %s (validated ADR shape)",
                                issue.id,
                                self._config.ready_label[0],
                            )
                        return 1

                    result = await self._triage.evaluate(issue)

                    if self._config.dry_run:
                        return 1

                    if result.ready:
                        # Check if auto-decomposition should trigger
                        if not await self._maybe_decompose(issue, result):
                            await self._transitioner.transition(issue.id, "plan")
                            self._store.enqueue_transition(issue, "plan")
                            self._state.increment_session_counter("triaged")
                            logger.info(
                                "Issue #%d triaged → %s (ready for planning)",
                                issue.id,
                                self._config.planner_label[0],
                            )
                    else:
                        await self._escalate_triage_issue(issue.id, result.reasons)
                        self._store.enqueue_transition(issue, "hitl")
                        await self._bus.publish(
                            HydraFlowEvent(
                                type=EventType.HITL_UPDATE,
                                data={
                                    "issue": issue.id,
                                    "action": "escalated",
                                },
                            )
                        )
                        logger.info(
                            "Issue #%d triaged → %s (needs attention: %s)",
                            issue.id,
                            self._config.hitl_label[0],
                            "; ".join(result.reasons),
                        )
                    return 1

        try:
            results = await run_concurrent_batch(issues, _triage_one, self._stop_event)
        finally:
            release_batch_in_flight(self._store, {i.id for i in issues})
        return sum(results)

    async def _escalate_triage_issue(self, issue_id: int, reasons: list[str]) -> None:
        await escalate_to_hitl(
            self._state,
            self._prs,
            issue_id,
            cause="Insufficient issue detail for triage",
            origin_label=self._config.find_label[0],
            hitl_label=self._config.hitl_label[0],
        )
        note = (
            "## Needs More Information\n\n"
            "This issue was picked up by HydraFlow but doesn't have "
            "enough detail to begin planning.\n\n"
            "**Missing:**\n" + "\n".join(f"- {r}" for r in reasons) + "\n\n"
            "Please update the issue with more context and re-apply "
            f"the `{self._config.find_label[0]}` label when ready.\n\n"
            "---\n*Generated by HydraFlow Triage*"
        )
        await self._transitioner.post_comment(issue_id, note)

    async def _maybe_decompose(self, issue: Task, result: object) -> bool:
        """Auto-decompose a complex issue into an epic + children.

        Returns True if decomposition was performed (caller should skip
        normal label transition).
        """
        from models import TriageResult

        if (
            not self._config.epic_auto_decompose
            or self._epic_manager is None
            or not isinstance(result, TriageResult)
            or result.complexity_score
            < self._config.epic_decompose_complexity_threshold
        ):
            return False

        logger.info(
            "Issue #%d scored %d complexity — attempting auto-decomposition",
            issue.id,
            result.complexity_score,
        )

        decomp = await self._triage.run_decomposition(issue)
        if not decomp.should_decompose or len(decomp.children) < 2:
            logger.info(
                "Issue #%d decomposition declined (should_decompose=%s, children=%d)",
                issue.id,
                decomp.should_decompose,
                len(decomp.children),
            )
            return False

        epic_label = self._config.epic_label[0]
        epic_child_label = self._config.epic_child_label[0]
        find_label = self._config.find_label[0]

        # Create the epic issue
        epic_number = await self._prs.create_issue(
            decomp.epic_title,
            decomp.epic_body,
            [epic_label],
        )
        if epic_number <= 0:
            logger.warning(
                "Failed to create epic issue for decomposition of #%d",
                issue.id,
            )
            return False

        # Create child issues
        child_numbers: list[int] = []
        for child_spec in decomp.children:
            child_body = child_spec.body + f"\n\nParent Epic #{epic_number}"
            child_num = await self._prs.create_issue(
                child_spec.title,
                child_body,
                [epic_child_label, find_label],
            )
            if child_num > 0:
                child_numbers.append(child_num)
                self._state.record_issue_created()

        # Register with EpicManager
        await self._epic_manager.register_epic(
            epic_number,
            decomp.epic_title,
            child_numbers,
            auto_decomposed=True,
        )

        # Close the original issue with a link to the epic
        await self._prs.post_comment(
            issue.id,
            f"## Auto-Decomposed into Epic\n\n"
            f"This issue was automatically decomposed into epic #{epic_number} "
            f"with {len(child_numbers)} child issue(s).\n\n"
            f"**Reason:** {decomp.reasoning}\n\n"
            f"---\n*Generated by HydraFlow Triage*",
        )
        await self._prs.close_issue(issue.id)
        self._state.mark_issue(issue.id, "decomposed")

        logger.info(
            "Issue #%d decomposed into epic #%d with %d children: %s",
            issue.id,
            epic_number,
            len(child_numbers),
            child_numbers,
        )
        return True
