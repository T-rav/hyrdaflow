"""Background worker — periodic retrospective analysis via durable queue.

Producers (PostMergeHandler, ReviewPhase) append work items to the queue.
This loop polls the queue, runs analysis (pattern detection, proposal
verification), publishes dashboard events, and acknowledges processed items.
Unacknowledged items survive crashes for replay.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
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

# Window (#8988): once a HITL stale-insight issue is filed for a category,
# do not refile (or recomment) within this window even if the open-issue
# GitHub lookup races and returns 0.  An hour is much shorter than the
# 30-minute retrospective_interval default cadence, but long enough to
# survive back-to-back ticks that hit GitHub before its search index
# catches up to a freshly-created issue.
_HITL_DEDUP_WINDOW = timedelta(hours=1)


def _now_utc() -> datetime:
    """Indirection seam so tests can pin the clock."""
    return datetime.now(UTC)


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
        # Per-category last-filed timestamps for HITL stale-insight dedup
        # (#8988).  Lives in-memory; the open-issue GitHub lookup is the
        # cross-restart authority.  This dict is the race-safety net.
        self._hitl_filed_at: dict[str, datetime] = {}

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
        """Verify improvement proposal outcomes and escalate stale ones.

        Dedup rules (issue #8988):

        - **Open issue exists** for the same category → post a comment
          carrying the new tick's evidence instead of opening a duplicate.
        - **Closed issue exists** for the same category → treat the human
          close as a re-arm signal: clear the in-memory window-tracker so
          the next stale signal files fresh.  Mirrors
          ``FakeCoverageAuditorLoop._reconcile_closed_escalations``.
        - **In-memory window guard** (:data:`_HITL_DEDUP_WINDOW`): if this
          category was filed within the window, skip entirely.  Catches
          races where GitHub's search index has not caught up to a
          freshly-created issue.
        """
        from review_insights import (  # noqa: PLC0415
            _PROPOSAL_STALE_DAYS,
            CATEGORY_DESCRIPTIONS,
            verify_proposals,
        )

        records = self._insights.load_recent(50)
        stale = verify_proposals(self._insights, records)

        if not stale:
            return {"stale_proposals": 0}

        if self._prs is None:
            logger.warning("Retrospective: cannot file HITL issue — no PRPort")
            return {"stale_proposals": len(stale)}

        # Re-arm: any closed HITL stale-insight issue clears its category
        # from the in-memory window-tracker so the next stale tick files
        # fresh.  Cheap; runs once per verify-proposals tick.
        await self._reconcile_closed_hitl_issues()

        now = _now_utc()
        for category in stale:
            desc = CATEGORY_DESCRIPTIONS.get(category, category)
            title = f"[HITL] Stale review insight: {desc}"

            # 1. Window guard — protects against races where GitHub's
            #    search index has not surfaced our just-filed issue yet.
            last = self._hitl_filed_at.get(category)
            if last is not None and (now - last) < _HITL_DEDUP_WINDOW:
                logger.debug(
                    "Retrospective: skipping HITL stale-insight refile for "
                    "category=%s — within %s dedup window",
                    category,
                    _HITL_DEDUP_WINDOW,
                )
                continue

            # 2. Open-issue lookup — if one is open, comment instead of
            #    filing a duplicate.
            existing = await self._prs.find_existing_issue(title)
            if existing:
                tick_evidence = self._build_stale_tick_comment(
                    category, desc, _PROPOSAL_STALE_DAYS
                )
                await self._prs.post_comment(existing, tick_evidence)
                # Touch the window-tracker so we don't immediately re-comment.
                self._hitl_filed_at[category] = now
                continue

            # 3. File a fresh HITL issue. Set the window-tracker BEFORE
            #    the await so a crash between issue creation and the
            #    assignment doesn't strand the freshly-filed issue with
            #    no in-memory guard — protects against the cross-tick
            #    race where ``find_existing_issue`` may not yet see the
            #    just-filed issue via GitHub's search index.
            body = (
                f"## Stale Improvement Proposal\n\n"
                f"The improvement proposal for **{category}** ({desc}) "
                f"was filed over {_PROPOSAL_STALE_DAYS} days ago but the "
                f"pattern frequency has not decreased. Human intervention is "
                f"required to resolve this recurring feedback loop.\n\n"
                f"---\n*Auto-escalated by HydraFlow review insight verification.*"
            )
            hitl_labels = list(self._config.hitl_label)
            self._hitl_filed_at[category] = now
            try:
                await self._prs.create_issue(title, body, hitl_labels)
            except Exception:
                # Filing failed — clear the optimistic guard so the next
                # tick can retry. Re-raise to preserve normal error flow.
                self._hitl_filed_at.pop(category, None)
                raise

        return {"stale_proposals": len(stale)}

    @staticmethod
    def _build_stale_tick_comment(category: str, desc: str, stale_days: int) -> str:
        """Comment body posted to an existing open HITL stale-insight issue.

        Carries the tick context so a human grooming the issue can see the
        signal is still recurring rather than letting duplicates pile up.
        """
        return (
            f"Still stale — pattern frequency for **{category}** ({desc}) "
            f"has not decreased after {stale_days}+ days.  This is a "
            f"recurring tick from `RetrospectiveLoop`; the underlying "
            f"escalation remains open.\n\n"
            f"_Auto-comment by HydraFlow review insight verification._"
        )

    async def _reconcile_closed_hitl_issues(self) -> None:
        """Clear the in-memory window-tracker for closed HITL stale-insight issues.

        Mirrors :meth:`FakeCoverageAuditorLoop._reconcile_closed_escalations`:
        a human-closed HITL issue is the re-arm signal — the next stale
        tick should be free to file fresh.

        Only inspects closed issues carrying the configured ``hitl_label``;
        matches by title prefix ``[HITL] Stale review insight:`` to scope
        the clear to this loop's own escalations.
        """
        if self._prs is None:
            return
        if not self._hitl_filed_at:
            return  # Nothing to re-arm.

        hitl_labels = list(self._config.hitl_label)
        if not hitl_labels:
            return

        try:
            closed = await self._prs.list_closed_issues_by_label(hitl_labels[0])
        except Exception:  # noqa: BLE001
            # The lookup is best-effort; reraising would block the entire
            # verify-proposals tick on a transient GitHub fault.
            logger.debug(
                "Retrospective: could not list closed HITL issues for re-arm",
                exc_info=True,
            )
            return

        from review_insights import CATEGORY_DESCRIPTIONS  # noqa: PLC0415

        prefix = "[HITL] Stale review insight: "
        # Build desc → category reverse lookup once.
        desc_to_category = {
            CATEGORY_DESCRIPTIONS.get(cat, cat): cat
            for cat in list(self._hitl_filed_at.keys())
        }

        cleared: list[str] = []
        for entry in closed:
            title = entry.get("title", "") if isinstance(entry, dict) else ""
            if not title.startswith(prefix):
                continue
            desc = title[len(prefix) :]
            category = desc_to_category.get(desc) or desc
            if category in self._hitl_filed_at:
                del self._hitl_filed_at[category]
                cleared.append(category)

        if cleared:
            logger.info(
                "Retrospective: re-armed HITL stale-insight tracker for %s",
                cleared,
            )

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
