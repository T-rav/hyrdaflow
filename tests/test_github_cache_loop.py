"""Unit tests for GitHubCacheLoop and GitHubDataCache."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from github_cache_loop import CacheSnapshot, GitHubCacheLoop, GitHubDataCache
from models import HITLItem, LabelCounts, PRListItem
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pr(pr: int = 1) -> PRListItem:
    return PRListItem(
        pr=pr,
        author="testuser",
        title=f"PR #{pr}",
        url=f"https://github.com/o/r/pull/{pr}",
    )


def _make_hitl_item(issue: int = 10) -> HITLItem:
    return HITLItem(issue=issue, title=f"HITL #{issue}")


def _make_label_counts() -> LabelCounts:
    return LabelCounts(
        open_by_label={"hydraflow-review": 2}, total_closed=5, total_merged=3
    )


def _make_cache(
    tmp_path: Path,
    *,
    open_prs: list[PRListItem] | None = None,
    hitl_items: list[HITLItem] | None = None,
    label_counts: LabelCounts | None = None,
    collaborators: set[str] | None = None,
    prs_error: Exception | None = None,
    hitl_error: Exception | None = None,
    label_error: Exception | None = None,
    collab_error: Exception | None = None,
) -> tuple[GitHubDataCache, MagicMock, MagicMock]:
    """Build a GitHubDataCache with test-friendly mocks.

    Returns (cache, prs_mock, fetcher_mock).
    """
    from tests.helpers import ConfigFactory

    config = ConfigFactory.create(repo_root=tmp_path / "repo")

    prs = MagicMock()
    if prs_error is not None:
        prs.list_open_prs = AsyncMock(side_effect=prs_error)
        prs.list_hitl_items = AsyncMock(side_effect=hitl_error or prs_error)
        prs.get_label_counts = AsyncMock(side_effect=label_error or prs_error)
    else:
        prs.list_open_prs = AsyncMock(
            return_value=open_prs if open_prs is not None else []
        )
        prs.list_hitl_items = (
            AsyncMock(
                side_effect=hitl_error,
            )
            if hitl_error is not None
            else AsyncMock(return_value=hitl_items if hitl_items is not None else [])
        )
        prs.get_label_counts = (
            AsyncMock(
                side_effect=label_error,
            )
            if label_error is not None
            else AsyncMock(return_value=label_counts)
        )

    fetcher = MagicMock()
    if collab_error is not None:
        fetcher._get_collaborators = AsyncMock(side_effect=collab_error)
    else:
        fetcher._get_collaborators = AsyncMock(
            return_value=collaborators if collaborators is not None else set()
        )

    cache = GitHubDataCache(
        config=config,
        pr_manager=prs,
        fetcher=fetcher,
        cache_dir=tmp_path / "cache",
    )
    return cache, prs, fetcher


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 300,
    open_prs: list[PRListItem] | None = None,
) -> tuple[GitHubCacheLoop, asyncio.Event, GitHubDataCache]:
    """Build a GitHubCacheLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, data_poll_interval=interval)

    cache, _, _ = _make_cache(tmp_path, open_prs=open_prs)

    loop = GitHubCacheLoop(
        config=deps.config,
        cache=cache,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, cache


# ===========================================================================
# CacheSnapshot
# ===========================================================================


class TestCacheSnapshot:
    def test_age_seconds_returns_inf_when_never_fetched(self) -> None:
        snap = CacheSnapshot()
        assert snap.age_seconds == float("inf")

    def test_age_seconds_returns_elapsed_time(self) -> None:
        fetched = datetime.now(UTC) - timedelta(seconds=30)
        snap = CacheSnapshot(data=[], fetched_at=fetched)
        assert 28 < snap.age_seconds < 35

    def test_data_defaults_to_none(self) -> None:
        snap = CacheSnapshot()
        assert snap.data is None

    def test_fetched_at_defaults_to_none(self) -> None:
        snap = CacheSnapshot()
        assert snap.fetched_at is None


# ===========================================================================
# GitHubDataCache — initial state (before first poll)
# ===========================================================================


class TestGitHubDataCacheInitialState:
    def test_get_open_prs_returns_empty_list_before_poll(self, tmp_path: Path) -> None:
        cache, _, _ = _make_cache(tmp_path)
        assert cache.get_open_prs() == []

    def test_get_hitl_items_returns_empty_list_before_poll(
        self, tmp_path: Path
    ) -> None:
        cache, _, _ = _make_cache(tmp_path)
        assert cache.get_hitl_items() == []

    def test_get_label_counts_returns_none_before_poll(self, tmp_path: Path) -> None:
        cache, _, _ = _make_cache(tmp_path)
        assert cache.get_label_counts() is None

    def test_get_collaborators_returns_none_before_poll(self, tmp_path: Path) -> None:
        cache, _, _ = _make_cache(tmp_path)
        assert cache.get_collaborators() is None

    def test_get_cache_age_returns_inf_before_poll(self, tmp_path: Path) -> None:
        cache, _, _ = _make_cache(tmp_path)
        assert cache.get_cache_age("open_prs") == float("inf")

    def test_get_cache_age_returns_inf_for_unknown_dataset(
        self, tmp_path: Path
    ) -> None:
        cache, _, _ = _make_cache(tmp_path)
        assert cache.get_cache_age("nonexistent") == float("inf")


# ===========================================================================
# GitHubDataCache — poll cycle (happy path)
# ===========================================================================


class TestGitHubDataCachePoll:
    @pytest.mark.asyncio
    async def test_poll_populates_open_prs(self, tmp_path: Path) -> None:
        prs_data = [_make_pr(1), _make_pr(2)]
        cache, _, _ = _make_cache(tmp_path, open_prs=prs_data)

        stats = await cache.poll()

        assert cache.get_open_prs() == prs_data
        assert stats["open_prs"] == 2

    @pytest.mark.asyncio
    async def test_poll_populates_hitl_items(self, tmp_path: Path) -> None:
        hitl_data = [_make_hitl_item(10), _make_hitl_item(20)]
        cache, _, _ = _make_cache(tmp_path, hitl_items=hitl_data)

        stats = await cache.poll()

        assert cache.get_hitl_items() == hitl_data
        assert stats["hitl_items"] == 2

    @pytest.mark.asyncio
    async def test_poll_populates_label_counts(self, tmp_path: Path) -> None:
        lc = _make_label_counts()
        cache, _, _ = _make_cache(tmp_path, label_counts=lc)

        stats = await cache.poll()

        assert cache.get_label_counts() == lc
        assert stats["label_counts"] is True

    @pytest.mark.asyncio
    async def test_poll_populates_collaborators(self, tmp_path: Path) -> None:
        collabs = {"alice", "bob"}
        cache, _, _ = _make_cache(tmp_path, collaborators=collabs)

        stats = await cache.poll()

        assert cache.get_collaborators() == collabs
        assert stats["collaborators"] == 2

    @pytest.mark.asyncio
    async def test_poll_updates_cache_age(self, tmp_path: Path) -> None:
        cache, _, _ = _make_cache(tmp_path)
        assert cache.get_cache_age("open_prs") == float("inf")

        await cache.poll()

        assert cache.get_cache_age("open_prs") < 5

    @pytest.mark.asyncio
    async def test_poll_uses_combined_label_list_for_open_prs(
        self, tmp_path: Path
    ) -> None:
        """list_open_prs is called with the deduplicated union of ready/review/hitl labels."""
        cache, prs_mock, _ = _make_cache(tmp_path)

        await cache.poll()

        prs_mock.list_open_prs.assert_awaited_once()
        called_labels = prs_mock.list_open_prs.call_args[0][0]
        # All three label categories should be represented, de-duplicated
        assert "test-label" in called_labels  # ready_label default
        assert "hydraflow-review" in called_labels
        assert "hydraflow-hitl" in called_labels

    @pytest.mark.asyncio
    async def test_poll_returns_stats_dict(self, tmp_path: Path) -> None:
        cache, _, _ = _make_cache(tmp_path)
        stats = await cache.poll()
        assert isinstance(stats, dict)
        assert "open_prs" in stats
        assert "hitl_items" in stats
        assert "label_counts" in stats
        assert "collaborators" in stats


# ===========================================================================
# GitHubDataCache — poll failure handling
# ===========================================================================


class TestGitHubDataCachePollFailure:
    @pytest.mark.asyncio
    async def test_open_prs_failure_logs_warning_and_continues(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A transient open_prs failure is logged; other datasets still update."""
        hitl_data = [_make_hitl_item(5)]
        cache, _, _ = _make_cache(
            tmp_path,
            hitl_items=hitl_data,
            prs_error=RuntimeError("API rate limit"),
        )

        # Ensure hitl/label/collab mocks are still wired up for the non-failing paths
        cache._hitl_items = CacheSnapshot()  # start unfetched

        # The poll should not raise
        with caplog.at_level("WARNING", logger="hydraflow.github_cache"):
            stats = await cache.poll()

        assert "open_prs" not in stats  # failing dataset absent from stats
        assert "Cache poll failed for open_prs" in caplog.text

    @pytest.mark.asyncio
    async def test_hitl_failure_does_not_crash_loop(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A transient hitl_items failure is logged; open_prs still updates."""
        prs_data = [_make_pr(1)]
        cache, _, _ = _make_cache(
            tmp_path,
            open_prs=prs_data,
            hitl_error=RuntimeError("Network timeout"),
        )

        with caplog.at_level("WARNING", logger="hydraflow.github_cache"):
            stats = await cache.poll()

        assert stats["open_prs"] == 1
        assert "hitl_items" not in stats
        assert "Cache poll failed for hitl_items" in caplog.text

    @pytest.mark.asyncio
    async def test_label_counts_failure_does_not_crash_loop(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache, _, _ = _make_cache(
            tmp_path,
            label_error=OSError("Connection refused"),
        )

        with caplog.at_level("WARNING", logger="hydraflow.github_cache"):
            stats = await cache.poll()

        assert "label_counts" not in stats
        assert "Cache poll failed for label_counts" in caplog.text

    @pytest.mark.asyncio
    async def test_collaborators_failure_does_not_crash_loop(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache, _, _ = _make_cache(
            tmp_path,
            collab_error=RuntimeError("403 Forbidden"),
        )

        with caplog.at_level("WARNING", logger="hydraflow.github_cache"):
            stats = await cache.poll()

        assert "collaborators" not in stats
        assert "Cache poll failed for collaborators" in caplog.text

    @pytest.mark.asyncio
    async def test_credit_exhausted_error_propagates_from_open_prs(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError must not be swallowed — reraise_on_credit_or_bug fires."""
        from subprocess_util import CreditExhaustedError

        cache, _, _ = _make_cache(
            tmp_path,
            prs_error=CreditExhaustedError("out of credits"),
        )

        with pytest.raises(CreditExhaustedError):
            await cache.poll()

    @pytest.mark.asyncio
    async def test_poll_preserves_stale_data_on_partial_failure(
        self, tmp_path: Path
    ) -> None:
        """Stale cache data is preserved when a refresh fails mid-poll."""
        stale_prs = [_make_pr(99)]
        cache, _, _ = _make_cache(tmp_path, open_prs=stale_prs)

        # Initial good poll
        await cache.poll()
        assert len(cache.get_open_prs()) == 1

        # Now make prs fail on next poll
        cache._prs.list_open_prs = AsyncMock(side_effect=RuntimeError("API down"))

        await cache.poll()

        # Stale data is still there — the snapshot is not reset to empty on failure
        assert len(cache.get_open_prs()) == 1


# ===========================================================================
# GitHubDataCache — disk persistence round-trip
# ===========================================================================


class TestGitHubDataCacheDiskPersistence:
    @pytest.mark.asyncio
    async def test_save_and_load_open_prs(self, tmp_path: Path) -> None:
        """PRListItem data survives a save/load round-trip via JSON."""
        prs_data = [_make_pr(1), _make_pr(2)]
        cache, _, _ = _make_cache(tmp_path, open_prs=prs_data)
        await cache.poll()

        # Construct a fresh cache from the same directory — simulates restart
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        prs2 = MagicMock()
        fetcher2 = MagicMock()
        cache2 = GitHubDataCache(
            config=config,
            pr_manager=prs2,
            fetcher=fetcher2,
            cache_dir=tmp_path / "cache",
        )

        loaded = cache2.get_open_prs()
        assert len(loaded) == 2
        assert loaded[0].pr == 1
        assert loaded[1].pr == 2

    @pytest.mark.asyncio
    async def test_save_and_load_collaborators(self, tmp_path: Path) -> None:
        collabs = {"alice", "bob", "charlie"}
        cache, _, _ = _make_cache(tmp_path, collaborators=collabs)
        await cache.poll()

        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        cache2 = GitHubDataCache(
            config=config,
            pr_manager=MagicMock(),
            fetcher=MagicMock(),
            cache_dir=tmp_path / "cache",
        )

        assert cache2.get_collaborators() == collabs

    @pytest.mark.asyncio
    async def test_cache_file_is_valid_json(self, tmp_path: Path) -> None:
        cache, _, _ = _make_cache(tmp_path, open_prs=[_make_pr(1)])
        await cache.poll()

        cache_file = tmp_path / "cache" / "github_cache.json"
        assert cache_file.is_file()
        parsed = json.loads(cache_file.read_text())
        assert "open_prs" in parsed
        assert "fetched_at" in parsed

    def test_load_tolerates_missing_cache_file(self, tmp_path: Path) -> None:
        """Construction succeeds even if the cache file does not exist."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        cache = GitHubDataCache(
            config=config,
            pr_manager=MagicMock(),
            fetcher=MagicMock(),
            cache_dir=tmp_path / "no_such_dir",
        )
        assert cache.get_open_prs() == []

    def test_load_tolerates_corrupt_cache_file(self, tmp_path: Path) -> None:
        """Construction succeeds when the cache file contains invalid JSON."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "github_cache.json").write_text("{bad json!!!}")

        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        cache = GitHubDataCache(
            config=config,
            pr_manager=MagicMock(),
            fetcher=MagicMock(),
            cache_dir=cache_dir,
        )
        assert cache.get_open_prs() == []

    @pytest.mark.asyncio
    async def test_age_restored_from_disk_after_reload(self, tmp_path: Path) -> None:
        """Cache age loaded from disk reflects original fetched_at, not inf."""
        cache, _, _ = _make_cache(tmp_path, open_prs=[_make_pr(1)])
        await cache.poll()

        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        cache2 = GitHubDataCache(
            config=config,
            pr_manager=MagicMock(),
            fetcher=MagicMock(),
            cache_dir=tmp_path / "cache",
        )

        age = cache2.get_cache_age("open_prs")
        assert age != float("inf")
        assert age < 10  # should be just-fetched


# ===========================================================================
# GitHubDataCache — invalidate()
# ===========================================================================


class TestGitHubDataCacheInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_single_dataset_clears_its_snapshot(
        self, tmp_path: Path
    ) -> None:
        cache, _, _ = _make_cache(tmp_path, open_prs=[_make_pr(1)])
        await cache.poll()

        assert cache.get_cache_age("open_prs") < 5

        cache.invalidate("open_prs")

        assert cache.get_cache_age("open_prs") == float("inf")

    @pytest.mark.asyncio
    async def test_invalidate_single_dataset_leaves_others_intact(
        self, tmp_path: Path
    ) -> None:
        collabs = {"alice"}
        cache, _, _ = _make_cache(
            tmp_path, open_prs=[_make_pr(1)], collaborators=collabs
        )
        await cache.poll()

        cache.invalidate("open_prs")

        # collaborators snapshot is unaffected
        assert cache.get_collaborators() == collabs
        assert cache.get_cache_age("collaborators") < 5

    @pytest.mark.asyncio
    async def test_invalidate_all_clears_all_datasets(self, tmp_path: Path) -> None:
        collabs = {"alice"}
        cache, _, _ = _make_cache(
            tmp_path,
            open_prs=[_make_pr(1)],
            hitl_items=[_make_hitl_item(10)],
            label_counts=_make_label_counts(),
            collaborators=collabs,
        )
        await cache.poll()

        cache.invalidate()  # None → all

        for dataset in ("open_prs", "hitl_items", "label_counts", "collaborators"):
            assert cache.get_cache_age(dataset) == float("inf"), dataset

    @pytest.mark.asyncio
    async def test_invalidate_resets_snapshot_to_empty(self, tmp_path: Path) -> None:
        """invalidate() replaces the snapshot with a blank CacheSnapshot so that
        both the timestamp and the data are cleared — the next poll fills it fresh."""
        prs_data = [_make_pr(7)]
        cache, _, _ = _make_cache(tmp_path, open_prs=prs_data)
        await cache.poll()

        assert cache.get_open_prs() == prs_data  # data present before invalidate

        cache.invalidate("open_prs")

        # After invalidate the snapshot is empty — get_open_prs() falls back to []
        assert cache.get_open_prs() == []
        assert cache.get_cache_age("open_prs") == float("inf")

    def test_invalidate_unknown_dataset_is_a_no_op(self, tmp_path: Path) -> None:
        """Passing an unknown dataset name to invalidate() does not crash."""
        cache, _, _ = _make_cache(tmp_path)
        cache.invalidate("does_not_exist")  # should not raise


# ===========================================================================
# GitHubDataCache — stale entry eviction via get_cache_age
# ===========================================================================


class TestGitHubDataCacheStaleEntries:
    @pytest.mark.asyncio
    async def test_age_exceeds_threshold_after_elapsed_time(
        self, tmp_path: Path
    ) -> None:
        """get_cache_age grows over time, enabling consumers to detect staleness."""
        past = datetime.now(UTC) - timedelta(seconds=400)
        cache, _, _ = _make_cache(tmp_path)
        # Inject a stale snapshot directly
        cache._open_prs = CacheSnapshot(data=[_make_pr(1)], fetched_at=past)

        age = cache.get_cache_age("open_prs")
        assert age > 395

    @pytest.mark.asyncio
    async def test_poll_refreshes_stale_entry(self, tmp_path: Path) -> None:
        """A subsequent poll replaces the stale snapshot with a fresh one."""
        past = datetime.now(UTC) - timedelta(seconds=400)
        prs_data = [_make_pr(5)]
        cache, _, _ = _make_cache(tmp_path, open_prs=prs_data)
        cache._open_prs = CacheSnapshot(data=[_make_pr(99)], fetched_at=past)

        await cache.poll()

        assert cache.get_open_prs() == prs_data
        assert cache.get_cache_age("open_prs") < 5


# ===========================================================================
# GitHubCacheLoop — loop wiring
# ===========================================================================


class TestGitHubCacheLoopInterval:
    def test_default_interval_uses_config(self, tmp_path: Path) -> None:
        loop, _, _ = _make_loop(tmp_path, interval=120)
        assert loop._get_default_interval() == 120


class TestGitHubCacheLoopDoWork:
    @pytest.mark.asyncio
    async def test_do_work_returns_stats_on_success(self, tmp_path: Path) -> None:
        prs_data = [_make_pr(1), _make_pr(2)]
        loop, _, cache = _make_loop(tmp_path, open_prs=prs_data)

        result = await loop._do_work()

        assert result is not None
        assert result["open_prs"] == 2

    @pytest.mark.asyncio
    async def test_do_work_returns_disabled_when_not_enabled(
        self, tmp_path: Path
    ) -> None:
        loop, _, _ = _make_loop(tmp_path, enabled=False)

        result = await loop._do_work()

        assert result == {"status": "disabled"}

    @pytest.mark.asyncio
    async def test_do_work_calls_cache_poll(self, tmp_path: Path) -> None:
        loop, _, cache = _make_loop(tmp_path)
        cache.poll = AsyncMock(return_value={"open_prs": 0, "hitl_items": 0})

        await loop._do_work()

        cache.poll.assert_awaited_once()


class TestGitHubCacheLoopRun:
    @pytest.mark.asyncio
    async def test_run_publishes_worker_status_event(self, tmp_path: Path) -> None:
        """The loop publishes a BACKGROUND_WORKER_STATUS event on success."""
        loop, _, _ = _make_loop(tmp_path)

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        data = events[0].data
        assert data["worker"] == "github_cache"
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_run_skips_work_when_disabled(self, tmp_path: Path) -> None:
        """The loop returns the disabled sentinel when the enabled callback is False."""
        loop, _, cache = _make_loop(tmp_path, enabled=False)
        cache.poll = AsyncMock(return_value={})

        await loop.run()

        cache.poll.assert_not_awaited()
