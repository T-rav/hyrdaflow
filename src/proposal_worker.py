"""Event-driven proposal worker — detects patterns and files improvement issues.

Subscribes to insight-recorded signals on the EventBus. When patterns exceed
thresholds, files GitHub issues for self-improvement. All data reads come from
Dolt; no file I/O.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from events import EventType, HydraFlowEvent

if TYPE_CHECKING:
    from events import EventBus
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.proposal_worker")

# Event types this worker reacts to
_SIGNAL_TYPES = frozenset(
    {
        EventType.REVIEW_INSIGHT_RECORDED,
        EventType.HARNESS_FAILURE_RECORDED,
        EventType.RETROSPECTIVE_RECORDED,
    }
)


class ProposalWorker:
    """Subscribes to insight signals, detects patterns, files proposals.

    Runs as an async task alongside the orchestrator.  On each signal it
    queries Dolt for recent records, runs pattern analysis, and files a
    GitHub issue when thresholds are exceeded.
    """

    def __init__(
        self,
        *,
        bus: EventBus,
        state: Any,
        prs: PRManager,
        improve_label: list[str] | None = None,
        review_insight_window: int = 20,
        harness_insight_window: int = 30,
        retro_threshold: int = 5,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self._bus = bus
        self._state = state
        self._prs = prs
        self._improve_labels = improve_label or ["hydraflow-improve"]
        self._review_window = review_insight_window
        self._harness_window = harness_insight_window
        self._retro_threshold = retro_threshold
        self._stop_event = stop_event or asyncio.Event()
        self._debounce_seconds = 5.0

    async def run(self) -> None:
        """Subscribe to signals and process them until stopped."""
        queue = self._bus.subscribe()
        try:
            await self._event_loop(queue)
        finally:
            self._bus.unsubscribe(queue)

    async def _event_loop(self, queue: asyncio.Queue[HydraFlowEvent]) -> None:
        """Consume events, debouncing rapid bursts."""
        pending: set[EventType] = set()

        while not self._stop_event.is_set():
            # Wait for an event or stop
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=self._debounce_seconds
                )
            except TimeoutError:
                # Debounce window expired — process pending signals
                if pending:
                    await self._process_signals(pending)
                    pending.clear()
                continue

            if event.type in _SIGNAL_TYPES:
                pending.add(event.type)

    async def _process_signals(self, signals: set[EventType]) -> None:
        """Run pattern detection for each signal type."""
        for signal in signals:
            try:
                if signal == EventType.REVIEW_INSIGHT_RECORDED:
                    await self._check_review_patterns()
                elif signal == EventType.HARNESS_FAILURE_RECORDED:
                    await self._check_harness_patterns()
                elif signal == EventType.RETROSPECTIVE_RECORDED:
                    await self._check_retro_patterns()
            except Exception:
                logger.warning(
                    "Proposal worker failed for %s", signal, exc_info=True
                )

    # ------------------------------------------------------------------
    # Review insight patterns
    # ------------------------------------------------------------------

    async def _check_review_patterns(self) -> None:
        """Detect recurring review feedback and file proposals."""
        from review_insights import (
            ReviewRecord,
            analyze_patterns,
        )

        if not hasattr(self._state, "load_recent_review_records"):
            return

        rows = self._state.load_recent_review_records(self._review_window)
        records = []
        for row in rows:
            try:
                records.append(ReviewRecord.model_validate(row))
            except Exception:  # noqa: BLE001
                continue

        if not records:
            return

        patterns = analyze_patterns(records, threshold=3)
        if not patterns:
            return

        # Check which categories already have proposals filed
        proposed = self._get_proposed_categories("review")
        for category, count, _examples in patterns:
            if category in proposed:
                continue
            title = f"[Review Insight] Recurring pattern: {category.replace('_', ' ')}"
            body = (
                f"The review insight system detected **{count}** occurrences "
                f"of `{category}` in the last {self._review_window} reviews.\n\n"
                f"Consider addressing this pattern to reduce review friction."
            )
            await self._file_proposal(title, body, "review", category)
            break  # Cap at 1 per cycle

    # ------------------------------------------------------------------
    # Harness failure patterns
    # ------------------------------------------------------------------

    async def _check_harness_patterns(self) -> None:
        """Detect recurring harness failures and file proposals."""
        from harness_insights import (
            FailureRecord,
            generate_suggestions,
        )

        if not hasattr(self._state, "load_recent_harness_failures"):
            return

        rows = self._state.load_recent_harness_failures(self._harness_window)
        records = []
        for row in rows:
            try:
                records.append(FailureRecord.model_validate(row))
            except Exception:  # noqa: BLE001
                continue

        if not records:
            return

        proposed = self._get_proposed_categories("harness")
        suggestions = generate_suggestions(records, proposed=proposed)
        if not suggestions:
            return

        for suggestion in suggestions:
            key = f"{suggestion.category}:{suggestion.subcategory}" if suggestion.subcategory else suggestion.category
            title = f"[Harness Insight] {suggestion.description}"
            body = suggestion.suggestion
            await self._file_proposal(title, body, "harness", key)
            break  # Cap at 1 per cycle

    # ------------------------------------------------------------------
    # Retrospective patterns
    # ------------------------------------------------------------------

    async def _check_retro_patterns(self) -> None:
        """Detect retrospective patterns and file proposals."""
        from retrospective import RetrospectiveEntry

        if not hasattr(self._state, "load_recent_retrospectives"):
            return

        rows = self._state.load_recent_retrospectives(self._retro_threshold * 2)
        entries = []
        for row in rows:
            try:
                entries.append(RetrospectiveEntry.model_validate(row))
            except Exception:  # noqa: BLE001
                continue

        if len(entries) < self._retro_threshold:
            return

        # Pattern: quality fix rounds > 50%
        quality_fix_count = sum(
            1 for e in entries if (e.quality_fix_rounds or 0) > 0
        )
        proposed = self._get_proposed_categories("retro")

        if quality_fix_count > len(entries) * 0.5 and "quality_fixes" not in proposed:
            await self._file_proposal(
                "[Retro] High quality-fix rate detected",
                f"{quality_fix_count}/{len(entries)} recent issues needed quality fixes. "
                "Consider improving pre-quality checks or implementation prompts.",
                "retro",
                "quality_fixes",
            )
            return

        # Pattern: low plan accuracy
        accuracies = [e.plan_accuracy_pct for e in entries if e.plan_accuracy_pct is not None]
        if accuracies:
            avg_accuracy = sum(accuracies) / len(accuracies)
            if avg_accuracy < 70 and "low_plan_accuracy" not in proposed:
                await self._file_proposal(
                    "[Retro] Low plan accuracy detected",
                    f"Average plan accuracy is {avg_accuracy:.0f}% across "
                    f"{len(accuracies)} recent issues. Consider improving the planner.",
                    "retro",
                    "low_plan_accuracy",
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_proposed_categories(self, domain: str) -> set[str]:
        """Load already-proposed category keys from Dolt."""
        if hasattr(self._state, "get_proposed_categories"):
            try:
                return self._state.get_proposed_categories(domain)
            except Exception:  # noqa: BLE001
                pass
        return set()

    async def _file_proposal(
        self, title: str, body: str, domain: str, category: str
    ) -> None:
        """File a GitHub issue and mark the category as proposed."""
        try:
            await self._prs.create_issue(title, body, self._improve_labels)
            logger.info("Filed proposal: %s [%s/%s]", title, domain, category)
            if hasattr(self._state, "mark_category_proposed"):
                self._state.mark_category_proposed(domain, category)
            try:
                self._state.db.commit(f"proposal: {title}")
            except Exception:
                logger.debug("Dolt commit failed", exc_info=True)
        except Exception:
            logger.warning(
                "Failed to file proposal: %s", title, exc_info=True
            )
