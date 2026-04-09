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
    from bug_reproducer import BugReproducer
    from epic import EpicManager
    from issue_cache import IssueCache
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
        issue_cache: IssueCache | None = None,
        bug_reproducer: BugReproducer | None = None,
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
        self._issue_cache = issue_cache
        self._bug_reproducer = bug_reproducer

    def _enrich_parent_epic(self, issue: Task) -> None:
        """Set the parent_epic field if this issue belongs to a tracked epic."""
        if self._epic_manager is None:
            return
        parents = self._epic_manager.find_parent_epics(issue.id)
        if parents:
            issue.parent_epic = parents[0]

    def _complexity_rank(self, score: int) -> str:
        """Convert a 0-10 complexity score into a coarse rank label.

        The ``"high"`` boundary is tied to
        ``epic_decompose_complexity_threshold`` so the cache rank
        agrees with the epic-decomposition routing decision. If an
        operator lowers the epic threshold, issues at that score
        level will be marked ``"high"`` in the cache, matching the
        decomposition behavior instead of drifting out of sync.
        """
        high_threshold = self._config.epic_decompose_complexity_threshold
        if score >= high_threshold:
            return "high"
        if score >= 5:
            return "medium"
        if score >= 2:
            return "low"
        return "trivial"

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

        from trace_rollup import write_phase_rollup  # noqa: PLC0415
        from tracing_context import (  # noqa: PLC0415
            TracingContext,
            source_to_phase,
        )

        trace_phase = source_to_phase("triage")
        run_id = self._state.begin_trace_run(issue.id, trace_phase)
        self._triage.set_tracing_context(
            TracingContext(
                issue_number=issue.id,
                phase=trace_phase,
                source="triage",
                run_id=run_id,
            )
        )

        try:
            return await self._triage_single_traced(issue)
        finally:
            self._triage.clear_tracing_context()
            try:
                write_phase_rollup(
                    config=self._config,
                    issue_number=issue.id,
                    phase=trace_phase,
                    run_id=run_id,
                )
            except Exception:
                logger.warning(
                    "Phase rollup failed for issue #%d",
                    issue.id,
                    exc_info=True,
                )
            self._state.end_trace_run(issue.id, trace_phase)

    async def _triage_single_traced(self, issue: Task) -> int:
        """Inner triage logic — called with tracing context already set."""
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

        routing_outcome: str = "unknown"
        if result.needs_discovery or (
            result.ready and result.clarity_score < self._config.clarity_threshold
        ):
            # Vague or broad issue — route to product discovery track
            self._store.enqueue_transition(issue, "discover")
            await self._transitioner.transition(issue.id, "discover")
            self._state.increment_session_counter("triaged")
            routing_outcome = "discover"
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
                # IMPORTANT: do NOT swap the label yet. We need to write
                # the classification record AND run the bug reproducer
                # (for bug-classified issues) BEFORE the plan loop can
                # observe the new label and start work. The swap happens
                # below after the cache writes complete. Setting
                # routing_outcome here marks the intent for the
                # post-cache transition block.
                routing_outcome = "plan"
                logger.info(
                    "Issue #%d triaged → %s (ready for planning, "
                    "deferred swap until cache records written)",
                    issue.id,
                    self._config.planner_label[0],
                )
            else:
                # Auto-decomposed into an epic; children are the real work.
                routing_outcome = "epic_decomposed"
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
            routing_outcome = "sentry_noise_closed"
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
            routing_outcome = "parked"
            logger.info(
                "Issue #%d triaged → parked (needs info: %s)",
                issue.id,
                "; ".join(result.reasons),
            )

        # Mirror classification into the local JSONL cache with the
        # final routing outcome captured. Writing AFTER the routing
        # decision prevents the READY-stage precondition gate from
        # accepting a classification whose issue was parked or sent
        # to discover — the gate checks routing_outcome == "plan".
        # Best-effort: cache failures never raise into the domain layer.
        if self._issue_cache is not None:
            self._issue_cache.record_classification(
                issue.id,
                issue_type=str(result.issue_type),
                complexity_score=result.complexity_score,
                complexity_rank=self._complexity_rank(result.complexity_score),
                routing_outcome=routing_outcome,
                reasoning="; ".join(result.reasons) if result.reasons else "",
            )

        # Reproduce bug-classified issues that were routed to plan
        # (#6424). The reproducer writes a failing test under
        # tests/regressions/ when possible, and the result is mirrored
        # to the cache as a reproduction_stored record. The downstream
        # READY-stage precondition gate (has_reproduction_for_bug)
        # blocks bug-routed-to-plan issues that lack a successful
        # reproduction and routes them back to triage with the
        # investigation as feedback. This method just produces the
        # data the gate consumes — the gate handles enforcement.
        #
        # CRITICAL: this MUST run before the label swap to plan
        # below. Otherwise the plan loop can pick up the issue
        # before the reproduction record exists, the READY gate
        # finds nothing, and the issue ping-pongs forever.
        if (
            self._bug_reproducer is not None
            and self._issue_cache is not None
            and routing_outcome == "plan"
            and str(result.issue_type) == "bug"
        ):
            try:
                repro = await self._bug_reproducer.reproduce(issue)
                self._issue_cache.record_reproduction_stored(
                    issue.id,
                    outcome=str(repro.outcome),
                    test_path=repro.test_path,
                    details=repro.investigation or repro.failing_output,
                )
                if str(repro.outcome) == "unable":
                    logger.warning(
                        "Bug reproduction unable for issue #%d — READY "
                        "gate will route back to triage: %s",
                        issue.id,
                        repro.investigation,
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Bug reproducer raised for issue #%d — leaving issue "
                    "without a reproduction record",
                    issue.id,
                    exc_info=True,
                )

        # Deferred plan-stage label swap. Now that the classification
        # record + reproduction record (if applicable) are written, the
        # implement loop's READY gate has data to check when the issue
        # eventually transitions through plan → ready. The discover/
        # parked/sentry paths swapped their labels inline above because
        # they have no race window with downstream consumers.
        if routing_outcome == "plan":
            self._store.enqueue_transition(issue, "plan")
            await self._transitioner.transition(issue.id, "plan")
            self._state.increment_session_counter("triaged")

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
