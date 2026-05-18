"""Background worker — periodic retrospective analysis via durable queue.

Producers (PostMergeHandler, ReviewPhase) append work items to the queue.
This loop polls the queue, runs analysis (pattern detection, proposal
verification), publishes dashboard events, and acknowledges processed items.
Unacknowledged items survive crashes for replay.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from events import EventType, HydraFlowEvent
from retrospective_queue import QueueKind

if TYPE_CHECKING:
    from ports import PRPort
    from retrospective import RetrospectiveCollector
    from retrospective_queue import QueueItem, RetrospectiveQueue
    from review_insights import ReviewInsightStore

logger = logging.getLogger("hydraflow.retrospective_loop")


class RetrospectiveLoop(BaseBackgroundLoop):
    """Polls the retrospective durable queue and runs analysis.

    Work items arrive from PostMergeHandler (retro patterns) and
    ReviewPhase (review patterns).  Processing runs out of sync
    with the main pipeline loops, keeping the factory floor clear.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        deps: LoopDeps,
        retrospective: RetrospectiveCollector,
        insights: ReviewInsightStore,
        queue: RetrospectiveQueue,
        prs: PRPort | None = None,
    ) -> None:
        super().__init__(worker_name="retrospective", config=config, deps=deps)
        self._retro = retrospective
        self._insights = insights
        self._queue = queue
        self._prs = prs

    def _get_default_interval(self) -> int:
        return self._config.retrospective_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.retrospective_loop_enabled:
            return {"status": "config_disabled"}
        items = self._queue.load()
        if not items:
            return {"processed": 0, "patterns_filed": 0, "stale_proposals": 0}

        acknowledged: list[str] = []
        patterns_filed = 0
        stale_proposals = 0

        for item in items:
            if self._stop_event.is_set():
                break
            try:
                result = await self._process_item(item)
                patterns_filed += result.get("patterns_filed", 0)
                stale_proposals += result.get("stale_proposals", 0)
                acknowledged.append(item.id)
                await self._publish_update(item, "processed")
            except Exception:
                logger.warning(
                    "Retrospective: failed to process %s item (id=%s) — will retry",
                    item.kind,
                    item.id,
                    exc_info=True,
                )

        if acknowledged:
            self._queue.acknowledge(acknowledged)

        return {
            "processed": len(acknowledged),
            "patterns_filed": patterns_filed,
            "stale_proposals": stale_proposals,
        }

    async def _process_item(self, item: QueueItem) -> dict[str, int]:
        """Dispatch a single queue item to the appropriate handler."""
        if item.kind == QueueKind.RETRO_PATTERNS:
            return await self._handle_retro_patterns()
        if item.kind == QueueKind.REVIEW_PATTERNS:
            return await self._handle_review_patterns()
        if item.kind == QueueKind.VERIFY_PROPOSALS:
            return await self._handle_verify_proposals()
        logger.warning("Unknown queue item kind: %s", item.kind)
        return {}

    async def _handle_retro_patterns(self) -> dict[str, int]:
        """Run retrospective pattern detection."""
        entries = self._retro._load_recent(self._config.retrospective_window)
        await self._retro._detect_patterns(entries)
        return {"patterns_filed": 0}

    async def _handle_review_patterns(self) -> dict[str, int]:
        """Run review insight pattern analysis and file issues for new patterns."""
        from review_insights import (  # noqa: PLC0415
            CATEGORY_DESCRIPTIONS,
            analyze_patterns,
            build_insight_issue_body,
        )

        records = self._insights.load_recent(self._config.review_insight_window)
        patterns = analyze_patterns(records, self._config.review_pattern_threshold)
        proposed = self._insights.get_proposed_categories()
        filed = 0

        for category, count, evidence in patterns:
            if category in proposed:
                continue
            if self._prs is None:
                logger.warning(
                    "Retrospective: cannot file review insight issue — no PRPort"
                )
                break
            body = build_insight_issue_body(category, count, len(records), evidence)
            desc = CATEGORY_DESCRIPTIONS.get(category, category)
            title = f"[Review Insight] Recurring feedback: {desc}"
            labels = self._config.find_label[:1]
            await self._prs.create_issue(title, body, labels)
            self._insights.mark_category_proposed(category)
            self._insights.record_proposal(category, pre_count=count)
            filed += 1

        return {"patterns_filed": filed}

    async def _handle_verify_proposals(self) -> dict[str, int]:
        """Verify improvement proposal outcomes and escalate stale ones."""
        from review_insights import (  # noqa: PLC0415
            _PROPOSAL_STALE_DAYS,
            CATEGORY_DESCRIPTIONS,
            verify_proposals,
        )

        records = self._insights.load_recent(50)
        stale = verify_proposals(self._insights, records)

        for category in stale:
            if self._prs is None:
                logger.warning("Retrospective: cannot file HITL issue — no PRPort")
                break
            desc = CATEGORY_DESCRIPTIONS.get(category, category)
            title = f"[HITL] Stale review insight: {desc}"
            body = (
                f"## Stale Improvement Proposal\n\n"
                f"The improvement proposal for **{category}** ({desc}) "
                f"was filed over {_PROPOSAL_STALE_DAYS} days ago but the "
                f"pattern frequency has not decreased. Human intervention is "
                f"required to resolve this recurring feedback loop.\n\n"
                f"---\n*Auto-escalated by HydraFlow review insight verification.*"
            )
            hitl_labels = list(self._config.hitl_label)
            await self._prs.create_issue(title, body, hitl_labels)

        return {"stale_proposals": len(stale)}

    async def _publish_update(self, item: QueueItem, status: str) -> None:
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.RETROSPECTIVE_UPDATE,
                data={
                    "kind": item.kind,
                    "issue": item.issue_number,
                    "pr": item.pr_number,
                    "status": status,
                },
            )
        )
