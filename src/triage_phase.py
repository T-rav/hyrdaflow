"""Triage phase — evaluate find-labeled issues and route them."""

from __future__ import annotations

import asyncio
import logging

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_store import IssueStore
from phase_utils import (
    adr_validation_reasons,
    escalate_to_hitl,
    is_adr_issue_title,
    store_lifecycle,
)
from pr_manager import PRManager
from state import StateTracker
from task_source import TaskTransitioner
from triage import TriageRunner

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
    ) -> None:
        self._config = config
        self._state = state
        self._store = store
        self._triage = triage
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._bus = event_bus
        self._stop_event = stop_event

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
        processed = 0
        for issue in issues:
            if self._stop_event.is_set():
                logger.info("Stop requested — aborting triage loop")
                return processed

            async with store_lifecycle(self._store, issue.id, "find"):
                # ADR draft issues are already scoped/planned; validate shape and
                # route directly to implementation (ready queue).
                if is_adr_issue_title(issue.title):
                    processed += 1
                    if self._config.dry_run:
                        continue
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
                        logger.info(
                            "Issue #%d ADR triage → %s (validated ADR shape)",
                            issue.id,
                            self._config.ready_label[0],
                        )
                    continue

                result = await self._triage.evaluate(issue)
                processed += 1

                if self._config.dry_run:
                    continue

                if result.ready:
                    await self._transitioner.transition(issue.id, "plan")
                    self._store.enqueue_transition(issue, "plan")
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
        return processed

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
