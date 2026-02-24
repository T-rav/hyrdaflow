"""Tests for metrics_manager.py — MetricsManager class."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import HydraFlowConfig
from events import EventType
from metrics_manager import MetricsManager
from models import MetricsSnapshot, QueueStats

if TYPE_CHECKING:
    from events import EventBus
    from state import StateTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(**overrides: Any) -> HydraFlowConfig:
    """Return a HydraFlowConfig with sensible test defaults."""
    defaults: dict[str, Any] = {
        "repo": "test-owner/test-repo",
        "dry_run": False,
        "metrics_label": ["hydraflow-metrics"],
    }
    defaults.update(overrides)
    return HydraFlowConfig(**defaults)


def make_pr_manager() -> MagicMock:
    """Return a mock PRManager."""
    pr = MagicMock()
    pr.post_comment = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.get_label_counts = AsyncMock(
        return_value={
            "open_by_label": {"hydraflow-plan": 3, "hydraflow-review": 1},
            "total_closed": 10,
            "total_merged": 8,
        }
    )
    return pr


def make_manager(
    state: StateTracker, event_bus: EventBus, **config_overrides: Any
) -> tuple[MetricsManager, StateTracker, MagicMock, EventBus]:
    """Create a fully-wired MetricsManager with test dependencies."""
    config = make_config(**config_overrides)
    prs = make_pr_manager()
    mgr = MetricsManager(config, state, prs, event_bus)
    return mgr, state, prs, event_bus


# ---------------------------------------------------------------------------
# TestMetricsManagerBuildSnapshot
# ---------------------------------------------------------------------------


class TestBuildSnapshot:
    @pytest.mark.asyncio
    async def test_builds_from_lifetime_stats(self, state, event_bus) -> None:
        """Snapshot includes lifetime stats and computed rates."""
        mgr, state, _, _ = make_manager(state, event_bus)
        # Record some lifetime data
        state.record_issue_completed()
        state.record_issue_completed()
        state.record_pr_merged()

        snapshot = await mgr._build_snapshot()
        assert snapshot.issues_completed == 2
        assert snapshot.prs_merged == 1
        assert snapshot.merge_rate == pytest.approx(0.5)
        assert snapshot.timestamp  # non-empty

    @pytest.mark.asyncio
    async def test_handles_zero_issues(self, state, event_bus) -> None:
        """Rates are 0.0 when no issues have been completed."""
        mgr, _, _, _ = make_manager(state, event_bus)
        snapshot = await mgr._build_snapshot()
        assert snapshot.merge_rate == 0.0
        assert snapshot.quality_fix_rate == 0.0
        assert snapshot.hitl_escalation_rate == 0.0
        assert snapshot.first_pass_approval_rate == 0.0
        assert snapshot.avg_implementation_seconds == 0.0

    @pytest.mark.asyncio
    async def test_includes_queue_stats(self, state, event_bus) -> None:
        """Queue depth is captured from the provided QueueStats."""
        mgr, _, _, _ = make_manager(state, event_bus)
        queue = QueueStats(queue_depth={"plan": 5, "implement": 2})
        snapshot = await mgr._build_snapshot(queue)
        assert snapshot.queue_depth == {"plan": 5, "implement": 2}

    @pytest.mark.asyncio
    async def test_includes_github_label_counts(self, state, event_bus) -> None:
        """GitHub label counts are fetched and included."""
        mgr, _, _, _ = make_manager(state, event_bus)
        snapshot = await mgr._build_snapshot()
        assert snapshot.github_open_by_label == {
            "hydraflow-plan": 3,
            "hydraflow-review": 1,
        }
        assert snapshot.github_total_closed == 10
        assert snapshot.github_total_merged == 8

    @pytest.mark.asyncio
    async def test_handles_github_api_failure(self, state, event_bus) -> None:
        """GitHub label counts default to empty on API failure."""
        mgr, _, prs, _ = make_manager(state, event_bus)
        prs.get_label_counts = AsyncMock(side_effect=RuntimeError("API down"))
        snapshot = await mgr._build_snapshot()
        assert snapshot.github_open_by_label == {}
        assert snapshot.github_total_closed == 0
        assert snapshot.github_total_merged == 0

    @pytest.mark.asyncio
    async def test_computes_derived_rates(self, state, event_bus) -> None:
        """All derived rates are computed correctly."""
        mgr, state, _, _ = make_manager(state, event_bus)
        for _ in range(10):
            state.record_issue_completed()
        for _ in range(8):
            state.record_pr_merged()
        state.record_quality_fix_rounds(3)
        state.record_hitl_escalation()
        state.record_review_verdict("approve", False)
        state.record_review_verdict("approve", False)
        state.record_review_verdict("request-changes", False)
        state.record_implementation_duration(600.0)

        snapshot = await mgr._build_snapshot()
        assert snapshot.merge_rate == pytest.approx(0.8)
        assert snapshot.quality_fix_rate == pytest.approx(0.3)
        assert snapshot.hitl_escalation_rate == pytest.approx(0.1)
        assert snapshot.first_pass_approval_rate == pytest.approx(2 / 3)
        assert snapshot.avg_implementation_seconds == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# TestMetricsManagerSync
# ---------------------------------------------------------------------------


class TestSync:
    @pytest.mark.asyncio
    async def test_first_run_creates_issue_and_posts(self, state, event_bus) -> None:
        """First sync creates the metrics issue and posts a snapshot comment."""
        mgr, state, prs, bus = make_manager(state, event_bus)
        state.record_issue_completed()

        with patch.object(
            mgr, "_ensure_metrics_issue", new_callable=AsyncMock, return_value=42
        ):
            result = await mgr.sync()

        assert result["status"] == "posted"
        assert result["issue_number"] == 42
        assert result["snapshot_hash"]
        prs.post_comment.assert_called_once()

    @pytest.mark.asyncio
    async def test_unchanged_skips_post(self, state, event_bus) -> None:
        """When snapshot hash matches, no comment is posted."""
        mgr, state, prs, _ = make_manager(state, event_bus)

        # Fix the timestamp so the hash is stable between calls
        fixed_snapshot = MetricsSnapshot(timestamp="2025-01-01T00:00:00")
        with (
            patch.object(
                mgr, "_ensure_metrics_issue", new_callable=AsyncMock, return_value=42
            ),
            patch.object(
                mgr,
                "_build_snapshot",
                new_callable=AsyncMock,
                return_value=fixed_snapshot,
            ),
        ):
            result1 = await mgr.sync()
            assert result1["status"] == "posted"

            result2 = await mgr.sync()
            assert result2["status"] == "unchanged"

        # Only one comment posted (first call)
        prs.post_comment.assert_called_once()

    @pytest.mark.asyncio
    async def test_detects_change_and_posts(self, state, event_bus) -> None:
        """When data changes between syncs, a new comment is posted."""
        mgr, state, prs, _ = make_manager(state, event_bus)

        with patch.object(
            mgr, "_ensure_metrics_issue", new_callable=AsyncMock, return_value=42
        ):
            await mgr.sync()
            state.record_issue_completed()
            result = await mgr.sync()

        assert result["status"] == "posted"
        assert prs.post_comment.call_count == 2

    @pytest.mark.asyncio
    async def test_publishes_metrics_update_event(self, state, event_bus) -> None:
        """A METRICS_UPDATE event is published on successful post."""
        mgr, state, _, bus = make_manager(state, event_bus)
        published_events: list = []
        bus.publish = AsyncMock(side_effect=published_events.append)

        with patch.object(
            mgr, "_ensure_metrics_issue", new_callable=AsyncMock, return_value=42
        ):
            await mgr.sync()

        metrics_events = [
            e for e in published_events if e.type == EventType.METRICS_UPDATE
        ]
        assert len(metrics_events) == 1

    @pytest.mark.asyncio
    async def test_dry_run_skips_post(self, state, event_bus) -> None:
        """In dry-run mode, no comment is posted."""
        mgr, state, prs, _ = make_manager(state, event_bus, dry_run=True)
        result = await mgr.sync()
        assert result["status"] == "dry_run"
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_metrics_issue_returns_cached_locally(
        self, state, event_bus
    ) -> None:
        """When metrics issue cannot be created, returns cached_locally status."""
        mgr, state, _, _ = make_manager(state, event_bus)
        state.record_issue_completed()

        with patch.object(
            mgr, "_ensure_metrics_issue", new_callable=AsyncMock, return_value=0
        ):
            result = await mgr.sync()

        assert result["status"] == "cached_locally"
        assert result["reason"] == "no_metrics_issue"

    @pytest.mark.asyncio
    async def test_stores_latest_snapshot(self, state, event_bus) -> None:
        """The latest snapshot is cached in memory."""
        mgr, _, _, _ = make_manager(state, event_bus)
        assert mgr.latest_snapshot is None

        with patch.object(
            mgr, "_ensure_metrics_issue", new_callable=AsyncMock, return_value=42
        ):
            await mgr.sync()

        assert mgr.latest_snapshot is not None
        assert isinstance(mgr.latest_snapshot, MetricsSnapshot)


# ---------------------------------------------------------------------------
# TestEnsureMetricsIssue
# ---------------------------------------------------------------------------


class TestEnsureMetricsIssue:
    @pytest.mark.asyncio
    async def test_uses_cached_number(self, state, event_bus) -> None:
        """If issue number is already cached, returns it immediately."""
        mgr, state, prs, _ = make_manager(state, event_bus)
        state.set_metrics_issue_number(99)

        result = await mgr._ensure_metrics_issue()
        assert result == 99
        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_finds_by_label(self, state, event_bus) -> None:
        """Searches by label and caches the found issue number."""
        mgr, state, _, _ = make_manager(state, event_bus)

        mock_issue = MagicMock()
        mock_issue.number = 77

        with patch("issue_fetcher.IssueFetcher") as MockFetcher:
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch_issues_by_labels = AsyncMock(return_value=[mock_issue])
            result = await mgr._ensure_metrics_issue()

        assert result == 77
        assert state.get_metrics_issue_number() == 77

    @pytest.mark.asyncio
    async def test_creates_when_none_exists(self, state, event_bus) -> None:
        """When no issue exists, creates one and caches the number."""
        mgr, state, prs, _ = make_manager(state, event_bus)
        prs.create_issue = AsyncMock(return_value=55)

        with patch("issue_fetcher.IssueFetcher") as MockFetcher:
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
            result = await mgr._ensure_metrics_issue()

        assert result == 55
        assert state.get_metrics_issue_number() == 55
        prs.create_issue.assert_called_once()


# ---------------------------------------------------------------------------
# TestFormatComment
# ---------------------------------------------------------------------------


class TestFormatComment:
    def test_contains_markdown_table(self) -> None:
        """Output includes a Markdown table with key metrics."""
        snapshot = MetricsSnapshot(
            timestamp="2025-01-01T00:00:00",
            issues_completed=10,
            prs_merged=8,
            merge_rate=0.8,
        )
        comment = MetricsManager._format_snapshot_comment(snapshot)
        assert "| Issues Completed | 10 |" in comment
        assert "| PRs Merged | 8 |" in comment
        assert "| Merge Rate | 80.0% |" in comment

    def test_contains_json_block(self) -> None:
        """Output includes a JSON details block."""
        snapshot = MetricsSnapshot(
            timestamp="2025-01-01T00:00:00",
            issues_completed=5,
        )
        comment = MetricsManager._format_snapshot_comment(snapshot)
        assert "```json" in comment
        assert "```" in comment
        # Verify the JSON is parseable
        json_start = comment.index("```json") + 7
        json_end = comment.index("```", json_start)
        data = json.loads(comment[json_start:json_end].strip())
        assert data["issues_completed"] == 5

    def test_contains_timestamp(self) -> None:
        """Output includes the snapshot timestamp."""
        snapshot = MetricsSnapshot(timestamp="2025-06-15T12:30:00")
        comment = MetricsManager._format_snapshot_comment(snapshot)
        assert "2025-06-15T12:30:00" in comment


# ---------------------------------------------------------------------------
# TestFetchHistory
# ---------------------------------------------------------------------------


class TestFetchHistory:
    @pytest.mark.asyncio
    async def test_parses_json_from_comments(self, state, event_bus) -> None:
        """Parses MetricsSnapshot JSON from issue comments."""
        mgr, state, _, _ = make_manager(state, event_bus)
        state.set_metrics_issue_number(42)

        snap_json = MetricsSnapshot(
            timestamp="2025-01-01T00:00:00",
            issues_completed=5,
        ).model_dump_json(indent=2)
        comment = f"## Metrics\n\n```json\n{snap_json}\n```\n\n---"

        with patch("issue_fetcher.IssueFetcher") as MockFetcher:
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch_issue_comments = AsyncMock(return_value=[comment])
            result = await mgr.fetch_history_from_issue()

        assert len(result) == 1
        assert result[0].issues_completed == 5

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_issue_and_no_cache(
        self, state, event_bus, tmp_path
    ) -> None:
        """Returns empty list when no metrics issue and no local cache exist."""
        mgr, _, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        result = await mgr.fetch_history_from_issue()
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_invalid_json(self, state, event_bus) -> None:
        """Skips comments with invalid JSON gracefully."""
        mgr, state, _, _ = make_manager(state, event_bus)
        state.set_metrics_issue_number(42)

        comments = [
            "```json\n{invalid json}\n```",
            "No JSON here at all",
        ]

        with patch("issue_fetcher.IssueFetcher") as MockFetcher:
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch_issue_comments = AsyncMock(return_value=comments)
            result = await mgr.fetch_history_from_issue()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_oldest_first(self, state, event_bus) -> None:
        """Snapshots are returned in oldest-first order."""
        mgr, state, _, _ = make_manager(state, event_bus)
        state.set_metrics_issue_number(42)

        snap1 = MetricsSnapshot(timestamp="2025-01-01T00:00:00").model_dump_json()
        snap2 = MetricsSnapshot(timestamp="2025-01-02T00:00:00").model_dump_json()
        comments = [
            f"```json\n{snap1}\n```",
            f"```json\n{snap2}\n```",
        ]

        with patch("issue_fetcher.IssueFetcher") as MockFetcher:
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch_issue_comments = AsyncMock(return_value=comments)
            result = await mgr.fetch_history_from_issue()

        assert len(result) == 2
        assert result[0].timestamp == "2025-01-01T00:00:00"
        assert result[1].timestamp == "2025-01-02T00:00:00"

    @pytest.mark.asyncio
    async def test_falls_back_to_local_cache_on_api_failure(
        self, state, event_bus, tmp_path
    ) -> None:
        """Falls back to local cache when GitHub API fails."""
        mgr, state, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        state.set_metrics_issue_number(42)

        # Write a snapshot to local cache
        snap = MetricsSnapshot(timestamp="2025-01-01T00:00:00", issues_completed=7)
        mgr._save_to_local_cache(snap)

        with patch("issue_fetcher.IssueFetcher") as MockFetcher:
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch_issue_comments = AsyncMock(
                side_effect=RuntimeError("API down")
            )
            result = await mgr.fetch_history_from_issue()

        assert len(result) == 1
        assert result[0].issues_completed == 7

    @pytest.mark.asyncio
    async def test_skips_comment_with_valid_json_but_invalid_schema(
        self, state, event_bus
    ) -> None:
        """Skips comments with valid JSON that fails Pydantic validation."""
        mgr, state, _, _ = make_manager(state, event_bus)
        state.set_metrics_issue_number(42)

        # Valid JSON but missing required MetricsSnapshot fields
        comments = ['```json\n{"unexpected_field": true}\n```']

        with patch("issue_fetcher.IssueFetcher") as MockFetcher:
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch_issue_comments = AsyncMock(return_value=comments)
            result = await mgr.fetch_history_from_issue()

        assert result == []

    @pytest.mark.asyncio
    async def test_falls_back_to_local_cache_when_no_issue(
        self, state, event_bus, tmp_path
    ) -> None:
        """Falls back to local cache when no metrics issue number is configured."""
        mgr, _, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        # No issue number set — should return local cache
        snap = MetricsSnapshot(timestamp="2025-03-01T00:00:00", prs_merged=3)
        mgr._save_to_local_cache(snap)

        result = await mgr.fetch_history_from_issue()
        assert len(result) == 1
        assert result[0].prs_merged == 3


# ---------------------------------------------------------------------------
# TestLocalCache
# ---------------------------------------------------------------------------


class TestLocalCache:
    def test_save_creates_cache_file(self, state, event_bus, tmp_path) -> None:
        """_save_to_local_cache creates the JSONL file and parent directories."""
        mgr, _, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        snap = MetricsSnapshot(timestamp="2025-01-01T00:00:00")
        mgr._save_to_local_cache(snap)

        cache_file = tmp_path / "metrics" / "test-owner-test-repo" / "snapshots.jsonl"
        assert cache_file.exists()

    def test_save_appends_to_cache(self, state, event_bus, tmp_path) -> None:
        """Multiple saves append to the same JSONL file."""
        mgr, _, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        mgr._save_to_local_cache(MetricsSnapshot(timestamp="2025-01-01T00:00:00"))
        mgr._save_to_local_cache(MetricsSnapshot(timestamp="2025-01-02T00:00:00"))

        cache_file = tmp_path / "metrics" / "test-owner-test-repo" / "snapshots.jsonl"
        lines = [ln for ln in cache_file.read_text().strip().split("\n") if ln.strip()]
        assert len(lines) == 2

    def test_load_local_history_returns_snapshots(
        self, state, event_bus, tmp_path
    ) -> None:
        """load_local_history reads back saved snapshots."""
        mgr, _, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        mgr._save_to_local_cache(
            MetricsSnapshot(timestamp="2025-01-01T00:00:00", issues_completed=1)
        )
        mgr._save_to_local_cache(
            MetricsSnapshot(timestamp="2025-01-02T00:00:00", issues_completed=2)
        )

        result = mgr.load_local_history()
        assert len(result) == 2
        assert result[0].issues_completed == 1
        assert result[1].issues_completed == 2

    def test_load_local_history_empty_when_no_file(
        self, state, event_bus, tmp_path
    ) -> None:
        """load_local_history returns empty list when no cache file exists."""
        mgr, _, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        result = mgr.load_local_history()
        assert result == []

    def test_load_local_history_respects_limit(
        self, state, event_bus, tmp_path
    ) -> None:
        """load_local_history caps results at the given limit."""
        mgr, _, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        for i in range(5):
            mgr._save_to_local_cache(
                MetricsSnapshot(timestamp=f"2025-01-0{i + 1}T00:00:00")
            )

        result = mgr.load_local_history(limit=3)
        assert len(result) == 3
        # Should return the 3 most recent (oldest-first)
        assert result[0].timestamp == "2025-01-03T00:00:00"

    def test_load_local_history_skips_corrupt_lines(
        self, state, event_bus, tmp_path, caplog
    ) -> None:
        """Corrupt JSONL lines are skipped with debug logging."""
        import logging

        mgr, _, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        cache_dir = tmp_path / "metrics" / "test-owner-test-repo"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "snapshots.jsonl"

        valid = MetricsSnapshot(timestamp="2025-01-01T00:00:00", issues_completed=5)
        with open(cache_file, "w") as f:
            f.write("{ corrupt }\n")
            f.write(valid.model_dump_json() + "\n")
            f.write("also broken\n")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.metrics_manager"):
            result = mgr.load_local_history()

        assert len(result) == 1
        assert result[0].issues_completed == 5
        assert "Skipping corrupt metrics snapshot line" in caplog.text

    def test_cache_dir_uses_repo_slug(self, state, event_bus, tmp_path) -> None:
        """Cache directory path is based on repo slug."""
        mgr, _, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        assert mgr._cache_dir == tmp_path / "metrics" / "test-owner-test-repo"

    @pytest.mark.asyncio
    async def test_sync_writes_to_local_cache(self, state, event_bus, tmp_path) -> None:
        """sync() writes snapshot to local cache before posting to GitHub."""
        mgr, state, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        state.record_issue_completed()

        with patch.object(
            mgr, "_ensure_metrics_issue", new_callable=AsyncMock, return_value=42
        ):
            await mgr.sync()

        cache_file = tmp_path / "metrics" / "test-owner-test-repo" / "snapshots.jsonl"
        assert cache_file.exists()
        lines = [ln for ln in cache_file.read_text().strip().split("\n") if ln.strip()]
        assert len(lines) == 1

    def test_save_to_local_cache_handles_mkdir_oserror(
        self, state, event_bus, tmp_path, caplog
    ) -> None:
        """When mkdir raises OSError, warning is logged and no exception raised."""
        import logging

        mgr, state, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        state.record_issue_completed()

        snapshot = MetricsSnapshot(timestamp="2025-01-01T00:00:00", issues_completed=1)

        with (
            patch.object(Path, "mkdir", side_effect=OSError("permission denied")),
            caplog.at_level(logging.WARNING, logger="hydraflow.metrics_manager"),
        ):
            mgr._save_to_local_cache(snapshot)  # should not raise

        assert "Failed to write metrics cache" in caplog.text

    def test_save_to_local_cache_handles_open_oserror(
        self, state, event_bus, tmp_path, caplog
    ) -> None:
        """When open() raises OSError (e.g. dir deleted between mkdir and open), warning is logged."""
        import logging

        mgr, state, _, _ = make_manager(
            state, event_bus, state_file=tmp_path / "state.json"
        )
        state.record_issue_completed()

        snapshot = MetricsSnapshot(timestamp="2025-01-01T00:00:00", issues_completed=1)

        with (
            patch("builtins.open", side_effect=OSError("no such file or directory")),
            caplog.at_level(logging.WARNING, logger="hydraflow.metrics_manager"),
        ):
            mgr._save_to_local_cache(snapshot)  # should not raise

        assert "Failed to write metrics cache" in caplog.text
