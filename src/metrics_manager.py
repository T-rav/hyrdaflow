"""Metrics Manager — periodic snapshot aggregation and GitHub persistence."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from models import MetricsSnapshot, MetricsSyncResult, QueueStats
from pr_manager import PRManager
from state import StateTracker

logger = logging.getLogger("hydraflow.metrics_manager")


def get_metrics_cache_dir(config: HydraFlowConfig) -> Path:
    """Return the local metrics cache directory for a given config.

    Path: ``<state_dir>/metrics/{repo_slug}/`` where *repo_slug* is the repo
    name with ``/`` replaced by ``-`` (e.g. ``owner/repo`` → ``owner-repo``).
    """
    repo_slug = config.repo.replace("/", "-") or "unknown"
    return config.state_file.parent / "metrics" / repo_slug


class MetricsManager:
    """Aggregates metrics into timestamped snapshots and persists to GitHub.

    Each snapshot is posted as a comment on a ``hydraflow-metrics`` issue.
    Snapshots are also written to a local disk cache at
    ``.hydraflow/metrics/{repo_slug}/snapshots.jsonl`` for fast dashboard access.
    Hash-based change detection avoids posting duplicate comments.
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
        self._latest_snapshot: MetricsSnapshot | None = None

    @property
    def latest_snapshot(self) -> MetricsSnapshot | None:
        """Return the most recent in-memory snapshot."""
        return self._latest_snapshot

    @property
    def _cache_dir(self) -> Path:
        """Return the local metrics cache directory for the current repo."""
        return get_metrics_cache_dir(self._config)

    async def sync(self, queue_stats: QueueStats | None = None) -> MetricsSyncResult:
        """Aggregate, snapshot, and persist metrics. Returns status details."""
        snapshot = await self._build_snapshot(queue_stats)
        self._latest_snapshot = snapshot

        # Hash-compare to avoid posting unchanged data
        snapshot_json = snapshot.model_dump_json()
        snapshot_hash = hashlib.sha256(snapshot_json.encode()).hexdigest()[:16]

        _, last_hash, _ = self._state.get_metrics_state()
        if snapshot_hash == last_hash:
            logger.debug("Metrics snapshot unchanged — skipping post")
            return {
                "status": "unchanged",
                "snapshot_hash": snapshot_hash,
                "timestamp": snapshot.timestamp,
            }

        # Always write to local cache first
        self._save_to_local_cache(snapshot)

        if self._config.dry_run:
            logger.info("[dry-run] Would post metrics snapshot")
            self._state.update_metrics_state(snapshot_hash)
            return {
                "status": "dry_run",
                "snapshot_hash": snapshot_hash,
                "timestamp": snapshot.timestamp,
            }

        # Ensure the metrics issue exists
        issue_number = await self._ensure_metrics_issue()
        if issue_number == 0:
            logger.warning("Could not find or create metrics issue — skipping post")
            # Still update state since local cache was written
            self._state.update_metrics_state(snapshot_hash)
            return {"status": "cached_locally", "reason": "no_metrics_issue"}

        # Post snapshot as comment
        comment_body = self._format_snapshot_comment(snapshot)
        await self._prs.post_comment(issue_number, comment_body)

        # Update state and publish event
        self._state.update_metrics_state(snapshot_hash)
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.METRICS_UPDATE,
                data=snapshot.model_dump(),
            )
        )

        logger.info(
            "Metrics snapshot posted to issue #%d (hash=%s)",
            issue_number,
            snapshot_hash,
        )
        return {
            "status": "posted",
            "issue_number": issue_number,
            "snapshot_hash": snapshot_hash,
            "timestamp": snapshot.timestamp,
        }

    def _save_to_local_cache(self, snapshot: MetricsSnapshot) -> None:
        """Append a snapshot to the local JSONL cache file."""
        cache_dir = self._cache_dir
        snapshots_file = cache_dir / "snapshots.jsonl"
        try:
            from file_util import append_jsonl  # noqa: PLC0415

            cache_dir.mkdir(parents=True, exist_ok=True)
            append_jsonl(snapshots_file, snapshot.model_dump_json())
            logger.debug("Metrics snapshot cached locally at %s", snapshots_file)
        except OSError:
            logger.warning(
                "Failed to write metrics cache to %s",
                snapshots_file,
                exc_info=True,
            )

    def load_local_history(self, limit: int = 100) -> list[MetricsSnapshot]:
        """Load metrics snapshots from local disk cache.

        Returns up to *limit* snapshots, oldest-first.
        """
        snapshots_file = self._cache_dir / "snapshots.jsonl"
        if not snapshots_file.exists():
            return []

        snapshots: list[MetricsSnapshot] = []
        with open(snapshots_file) as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    snapshots.append(MetricsSnapshot.model_validate_json(stripped))
                except ValidationError:
                    logger.debug(
                        "Skipping corrupt metrics snapshot line",
                        exc_info=True,
                    )
                    continue

        # Return oldest-first, capped at limit
        return snapshots[-limit:]

    async def _build_snapshot(
        self, queue_stats: QueueStats | None = None
    ) -> MetricsSnapshot:
        """Read LifetimeStats, compute rates, fetch GitHub counts."""
        stats = self._state.get_lifetime_stats()
        now = datetime.now(UTC).isoformat()

        issues_completed = stats.issues_completed
        prs_merged = stats.prs_merged
        total_approvals = stats.total_review_approvals
        total_request_changes = stats.total_review_request_changes
        total_reviews = total_approvals + total_request_changes

        # Compute derived rates
        merge_rate = prs_merged / issues_completed if issues_completed > 0 else 0.0
        quality_fix_rate = (
            stats.total_quality_fix_rounds / issues_completed
            if issues_completed > 0
            else 0.0
        )
        hitl_escalation_rate = (
            stats.total_hitl_escalations / issues_completed
            if issues_completed > 0
            else 0.0
        )
        first_pass_approval_rate = (
            total_approvals / total_reviews if total_reviews > 0 else 0.0
        )
        avg_impl_seconds = (
            stats.total_implementation_seconds / issues_completed
            if issues_completed > 0
            else 0.0
        )

        # Queue snapshot
        queue_depth: dict[str, int] = {}
        if queue_stats:
            queue_depth = dict(queue_stats.queue_depth)

        # GitHub label counts
        github_open_by_label: dict[str, int] = {}
        github_total_closed = 0
        github_total_merged = 0
        try:
            counts = await self._prs.get_label_counts(self._config)
            github_open_by_label = counts["open_by_label"]
            github_total_closed = counts["total_closed"]
            github_total_merged = counts["total_merged"]
        except Exception:
            logger.warning("Could not fetch GitHub label counts for snapshot")

        return MetricsSnapshot(
            timestamp=now,
            issues_completed=issues_completed,
            prs_merged=prs_merged,
            issues_created=stats.issues_created,
            total_quality_fix_rounds=stats.total_quality_fix_rounds,
            total_ci_fix_rounds=stats.total_ci_fix_rounds,
            total_hitl_escalations=stats.total_hitl_escalations,
            total_review_approvals=total_approvals,
            total_review_request_changes=total_request_changes,
            total_reviewer_fixes=stats.total_reviewer_fixes,
            total_implementation_seconds=stats.total_implementation_seconds,
            total_review_seconds=stats.total_review_seconds,
            merge_rate=merge_rate,
            quality_fix_rate=quality_fix_rate,
            hitl_escalation_rate=hitl_escalation_rate,
            first_pass_approval_rate=first_pass_approval_rate,
            avg_implementation_seconds=avg_impl_seconds,
            queue_depth=queue_depth,
            github_open_by_label=github_open_by_label,
            github_total_closed=github_total_closed,
            github_total_merged=github_total_merged,
        )

    async def _ensure_metrics_issue(self) -> int:
        """Find or create the hydraflow-metrics issue. Returns issue number (0 on failure)."""
        # Check cached number first
        cached = self._state.get_metrics_issue_number()
        if cached is not None:
            return cached

        # Search by label
        if self._config.metrics_label:
            try:
                from issue_fetcher import IssueFetcher

                fetcher = IssueFetcher(self._config)
                issues = await fetcher.fetch_issues_by_labels(
                    self._config.metrics_label, limit=1
                )
                if issues:
                    self._state.set_metrics_issue_number(issues[0].number)
                    return issues[0].number
            except Exception:
                logger.warning("Could not search for metrics issue by label")

        # Create a new one
        title = "HydraFlow Metrics"
        body = (
            "## HydraFlow Metrics Tracking\n\n"
            "This issue stores timestamped metrics snapshots as comments.\n"
            "Each comment contains a Markdown summary table and a JSON details block.\n\n"
            "**Do not close or edit this issue** — HydraFlow uses it for historical "
            "metrics persistence.\n\n"
            "---\n*Managed by HydraFlow Metrics Manager*"
        )
        issue_number = await self._prs.create_issue(
            title, body, list(self._config.metrics_label)
        )
        if issue_number:
            self._state.set_metrics_issue_number(issue_number)
        return issue_number

    @staticmethod
    def _format_snapshot_comment(snapshot: MetricsSnapshot) -> str:
        """Format a snapshot as a Markdown table + JSON details block."""
        lines = [
            f"## Metrics Snapshot — {snapshot.timestamp}\n",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Issues Completed | {snapshot.issues_completed} |",
            f"| PRs Merged | {snapshot.prs_merged} |",
            f"| Issues Created | {snapshot.issues_created} |",
            f"| Merge Rate | {snapshot.merge_rate:.1%} |",
            f"| Quality Fix Rate | {snapshot.quality_fix_rate:.1%} |",
            f"| HITL Escalation Rate | {snapshot.hitl_escalation_rate:.1%} |",
            f"| First-Pass Approval Rate | {snapshot.first_pass_approval_rate:.1%} |",
            f"| Avg Implementation Time | {snapshot.avg_implementation_seconds:.0f}s |",
            f"| Quality Fix Rounds | {snapshot.total_quality_fix_rounds} |",
            f"| CI Fix Rounds | {snapshot.total_ci_fix_rounds} |",
            f"| HITL Escalations | {snapshot.total_hitl_escalations} |",
            f"| Review Approvals | {snapshot.total_review_approvals} |",
            f"| Review Changes Requested | {snapshot.total_review_request_changes} |",
            f"| Reviewer Fixes | {snapshot.total_reviewer_fixes} |",
            "",
            "<details>",
            "<summary>JSON Data</summary>",
            "",
            "```json",
            snapshot.model_dump_json(indent=2),
            "```",
            "",
            "</details>",
            "",
            "---",
            "*Generated by HydraFlow Metrics Manager*",
        ]
        return "\n".join(lines)

    async def fetch_history_from_issue(self) -> list[MetricsSnapshot]:
        """Parse JSON blocks from issue comments. Returns oldest-first.

        Falls back to local cache if the GitHub issue is unavailable.
        """
        issue_number = self._state.get_metrics_issue_number()
        if issue_number is None:
            return self.load_local_history()

        try:
            from issue_fetcher import IssueFetcher

            fetcher = IssueFetcher(self._config)
            comments = await fetcher.fetch_issue_comments(issue_number)
        except Exception:
            logger.warning(
                "Could not fetch comments for metrics issue #%s — falling back to local cache",
                issue_number,
            )
            return self.load_local_history()

        snapshots: list[MetricsSnapshot] = []
        json_pattern = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)

        for comment_body in comments:
            match = json_pattern.search(comment_body)
            if not match:
                continue
            try:
                data = json.loads(match.group(1))
                snapshots.append(MetricsSnapshot.model_validate(data))
            except Exception:  # JSON parse or Pydantic validation
                continue

        return snapshots
