"""Triage phase — evaluate find-labeled issues and route them."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from adr_utils import (
    adr_validation_reasons,
    check_adr_duplicate,
    is_adr_issue_title,
)
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from models import Task, TriageResult
from phase_utils import (
    _sentry_transaction,
    park_issue,
    release_batch_in_flight,
    run_refilling_pool,
    store_lifecycle,
)
from state import StateTracker
from task_source import TaskTransitioner
from triage import TriageRunner

if TYPE_CHECKING:
    from epic import EpicManager
    from ports import IssueStorePort, PRPort

logger = logging.getLogger("hydraflow.triage_phase")

_SENTRY_MARKER = "<!-- [sentry:"


def _is_sentry_issue(issue: Task) -> bool:
    """Return True if the issue was filed by the Sentry ingest loop."""
    return _SENTRY_MARKER in (issue.body or "")


class TriagePhase:
    """Evaluates ``find_label`` issues and routes them to plan or HITL."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        store: IssueStorePort,
        triage: TriageRunner,
        prs: PRPort,
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

        Uses a slot-filling pool so new issues are picked up as soon
        as a triage slot frees, rather than waiting for the full batch.
        """

        async def _triage_one(_idx: int, issue: Task) -> int:
            if self._stop_event.is_set():
                return 0

            self._enrich_parent_epic(issue)

            with _sentry_transaction("pipeline.triage", f"triage:#{issue.id}"):
                async with store_lifecycle(self._store, issue.id, "find"):
                    try:
                        return await self._triage_single(issue)
                    finally:
                        release_batch_in_flight(self._store, {issue.id})

        results = await run_refilling_pool(
            supply_fn=lambda: self._store.get_triageable(1),
            worker_fn=_triage_one,
            max_concurrent=self._config.max_triagers,
            stop_event=self._stop_event,
        )
        return sum(results)

    async def _close_if_duplicate(self, issue: Task) -> bool:
        """Close *issue* if an open issue with the same title already exists.

        Returns True when the issue was closed as a duplicate.
        """
        if self._config.dry_run:
            return False
        existing = await self._prs.find_existing_issue(issue.title)
        if not existing or existing == issue.id:
            return False
        await self._prs.post_comment(
            issue.id,
            f"## Closing as Duplicate\n\n"
            f"An open issue with the same title already exists: #{existing}.\n\n"
            f"Closing this as a duplicate.",
        )
        await self._transitioner.close_task(issue.id)
        self._state.mark_issue(issue.id, "completed")
        logger.info("Issue #%d closed as duplicate of #%d", issue.id, existing)
        return True

    async def _triage_adr(self, issue: Task) -> None:
        """Handle ADR-specific triage: dedup, validate shape, route."""
        topic_key = check_adr_duplicate(issue.title, self._config.repo_root)
        if topic_key:
            await self._prs.post_comment(
                issue.id,
                f"## Closing as Duplicate\n\n"
                f"An ADR already exists for this topic in `docs/adr/`. "
                f"Normalized topic: *{topic_key}*",
            )
            await self._transitioner.close_task(issue.id)
            self._state.mark_issue(issue.id, "completed")
            logger.info(
                "Issue #%d ADR closed as duplicate — topic %r already in docs/adr/",
                issue.id,
                topic_key,
            )
            return
        reasons = adr_validation_reasons(issue.body)
        if reasons:
            await park_issue(
                self._prs,
                issue_number=issue.id,
                parked_label=self._config.parked_label[0],
                reasons=reasons,
            )
            logger.info(
                "Issue #%d ADR triage → parked (invalid ADR shape: %s)",
                issue.id,
                "; ".join(reasons),
            )
        else:
            self._store.enqueue_transition(issue, "ready")
            await self._transitioner.transition(issue.id, "ready")
            self._state.increment_session_counter("triaged")
            logger.info(
                "Issue #%d ADR triage → %s (validated ADR shape)",
                issue.id,
                self._config.ready_label[0],
            )

    async def _triage_single(self, issue: Task) -> int:
        """Core triage logic for a single issue."""
        if await self._close_if_duplicate(issue):
            return 1

        if is_adr_issue_title(issue.title):
            if not self._config.dry_run:
                await self._triage_adr(issue)
            return 1

        try:
            result = await self._triage.evaluate(issue)
        except RuntimeError as exc:
            # Infrastructure errors (empty LLM response, subprocess crash)
            # should NOT escalate to HITL.  Leave the issue in the find queue
            # so it gets retried on the next triage cycle.
            logger.warning(
                "Issue #%d triage skipped (infra error, will retry): %s",
                issue.id,
                exc,
            )
            return 0

        if self._config.dry_run:
            return 1

        if result.needs_discovery or (
            result.ready and result.clarity_score < self._config.clarity_threshold
        ):
            # Vague or broad issue — route to product discovery track
            self._store.enqueue_transition(issue, "discover")
            await self._transitioner.transition(issue.id, "discover")
            self._state.increment_session_counter("triaged")
            logger.info(
                "Issue #%d triaged → %s (needs product discovery, clarity=%d)",
                issue.id,
                self._config.discover_label[0],
                result.clarity_score,
            )
        elif result.ready:
            if not await self._maybe_decompose(issue, result):
                if result.enrichment:
                    await self._transitioner.post_comment(issue.id, result.enrichment)
                    logger.info(
                        "Issue #%d enriched by triage before promotion",
                        issue.id,
                    )
                self._store.enqueue_transition(issue, "plan")
                await self._transitioner.transition(issue.id, "plan")
                self._state.increment_session_counter("triaged")
                logger.info(
                    "Issue #%d triaged → %s (ready for planning)",
                    issue.id,
                    self._config.planner_label[0],
                )
        elif _is_sentry_issue(issue):
            # Sentry-originated issues that fail triage are noise — auto-close
            await self._prs.post_comment(
                issue.id,
                "## Auto-closed\n\nThis Sentry-originated issue did not pass triage "
                "evaluation. Likely a transient infrastructure error, not a code bug.\n\n"
                f"Reasons: {'; '.join(result.reasons)}",
            )
            await self._transitioner.close_task(issue.id)
            self._state.mark_issue(issue.id, "completed")
            logger.info(
                "Issue #%d Sentry noise auto-closed by triage: %s",
                issue.id,
                "; ".join(result.reasons),
            )
        else:
            # Park the issue instead of escalating to HITL — author needs
            # to provide more detail before the system can act on it.
            await park_issue(
                self._prs,
                issue_number=issue.id,
                parked_label=self._config.parked_label[0],
                reasons=result.reasons,
            )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_REROUTE,
                    data={
                        "issue": issue.id,
                        "action": "parked",
                        "reasons": result.reasons,
                    },
                )
            )
            logger.info(
                "Issue #%d triaged → parked (needs info: %s)",
                issue.id,
                "; ".join(result.reasons),
            )
        return 1

    async def _maybe_decompose(self, issue: Task, result: object) -> bool:
        """Auto-decompose a complex issue into an epic + children.

        Returns True if decomposition was performed (caller should skip
        normal label transition).
        """

        if (
            self._epic_manager is None
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
