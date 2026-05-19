"""Tests for the CIMonitorLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ci_monitor_loop import CIMonitorLoop
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
) -> tuple[CIMonitorLoop, asyncio.Event, MagicMock]:
    """Build a CIMonitorLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=enabled)
    pr_manager = MagicMock()
    pr_manager.get_latest_ci_status = AsyncMock(return_value=("success", ""))
    pr_manager.create_issue = AsyncMock(return_value=999)
    pr_manager.add_labels = AsyncMock()
    pr_manager.close_issue = AsyncMock()
    pr_manager.post_comment = AsyncMock()

    loop = CIMonitorLoop(
        config=deps.config,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, pr_manager


class TestCIMonitorLoop:
    @pytest.mark.asyncio
    async def test_green_ci_returns_no_action(self, tmp_path: Path) -> None:
        """When CI is green, no issue is created."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.get_latest_ci_status.return_value = ("success", "")
        result = await loop._do_work()
        assert result is not None
        assert result["status"] == "green"
        assert result.get("issue_created") is None
        pr.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_red_ci_creates_issue(self, tmp_path: Path) -> None:
        """When CI is red, an issue is filed."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.get_latest_ci_status.return_value = (
            "failure",
            "https://github.com/runs/123",
        )
        result = await loop._do_work()
        assert result is not None
        assert result["status"] == "red"
        assert result["issue_created"] == 999
        pr.create_issue.assert_awaited_once()
        title = pr.create_issue.call_args[0][0]
        assert "CI" in title

    @pytest.mark.asyncio
    async def test_red_ci_does_not_duplicate_issue(self, tmp_path: Path) -> None:
        """A second red CI poll does not create a duplicate issue."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.get_latest_ci_status.return_value = (
            "failure",
            "https://github.com/runs/123",
        )

        # First poll — creates issue
        await loop._do_work()
        assert pr.create_issue.await_count == 1

        # Second poll — same failure, should NOT create another
        result = await loop._do_work()
        assert pr.create_issue.await_count == 1
        assert result["status"] == "red"

    @pytest.mark.asyncio
    async def test_ci_recovery_closes_issue(self, tmp_path: Path) -> None:
        """When CI goes from red to green, the open issue is auto-closed."""
        loop, _stop, pr = _make_loop(tmp_path)

        # First: CI is red
        pr.get_latest_ci_status.return_value = (
            "failure",
            "https://github.com/runs/123",
        )
        await loop._do_work()
        assert pr.create_issue.await_count == 1

        # Then: CI recovers
        pr.get_latest_ci_status.return_value = ("success", "")
        result = await loop._do_work()
        assert result["status"] == "green"
        pr.close_issue.assert_awaited_once_with(999)
        pr.post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_api_error_does_not_crash(self, tmp_path: Path) -> None:
        """API errors are caught gracefully."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.get_latest_ci_status.side_effect = RuntimeError("API failed")
        result = await loop._do_work()
        assert result is not None
        assert result.get("error") is True

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        """In dry-run mode, _do_work returns None without API calls."""
        deps = make_bg_loop_deps(tmp_path, dry_run=True)
        pr = MagicMock()
        loop = CIMonitorLoop(config=deps.config, pr_manager=pr, deps=deps.loop_deps)
        result = await loop._do_work()
        assert result is None

    @pytest.mark.asyncio
    async def test_close_failure_retains_open_issue_for_retry(
        self, tmp_path: Path
    ) -> None:
        """If close_issue fails, _open_issue is retained so next cycle retries."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.get_latest_ci_status.return_value = ("failure", "https://github.com/runs/1")
        await loop._do_work()
        assert loop._open_issue == 999

        # CI recovers but close fails
        pr.get_latest_ci_status.return_value = ("success", "")
        pr.close_issue.side_effect = RuntimeError("close failed")
        await loop._do_work()

        # _open_issue should still be set for retry
        assert loop._open_issue == 999

    @pytest.mark.asyncio
    async def test_default_interval_from_config(self, tmp_path: Path) -> None:
        """_get_default_interval reads from config."""
        loop, _stop, _pr = _make_loop(tmp_path)
        assert loop._get_default_interval() == loop._config.ci_monitor_interval

    @pytest.mark.asyncio
    async def test_failed_issue_creation_does_not_track_phantom_zero(
        self, tmp_path: Path
    ) -> None:
        """When create_issue returns 0 (failure sentinel — e.g. missing label),
        the loop must not store 0 as ``_open_issue``.  Otherwise every later cycle
        emits ``gh issue comment 0`` / ``gh issue close 0`` calls that GitHub
        rejects with "Could not resolve to an issue or pull request with the
        number of 0"."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.get_latest_ci_status.return_value = ("failure", "https://github.com/runs/1")
        pr.create_issue = AsyncMock(return_value=0)

        result = await loop._do_work()

        assert result is not None
        assert result["status"] == "red"
        assert result.get("error") is True
        assert "issue_created" not in result
        assert loop._open_issue is None


class TestRehydrateOpenIssue:
    @pytest.mark.asyncio
    async def test_rehydrate_open_issue_when_existing_issue_found(
        self, tmp_path: Path
    ) -> None:
        """When an open CI-failure issue already exists, loop rehydrates state from it."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label = AsyncMock(return_value=[{"number": 42}])

        await loop._rehydrate_open_issue()

        assert loop._open_issue == 42
        pr.list_issues_by_label.assert_awaited_once_with("hydraflow-ci-failure")

    @pytest.mark.asyncio
    async def test_rehydrate_open_issue_when_no_existing_issue(
        self, tmp_path: Path
    ) -> None:
        """When no open CI-failure issue exists, _open_issue stays None (fresh start)."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label = AsyncMock(return_value=[])

        await loop._rehydrate_open_issue()

        assert loop._open_issue is None
        pr.list_issues_by_label.assert_awaited_once_with("hydraflow-ci-failure")

    @pytest.mark.asyncio
    async def test_rehydrate_open_issue_api_failure_is_handled_gracefully(
        self, tmp_path: Path
    ) -> None:
        """When the API call to list issues fails, the loop logs and skips — no crash."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label = AsyncMock(side_effect=RuntimeError("API down"))

        # Must not raise; _open_issue must remain None (safe default)
        await loop._rehydrate_open_issue()

        assert loop._open_issue is None
        assert loop._startup_check_done is True

    @pytest.mark.asyncio
    async def test_rehydrate_open_issue_is_idempotent(self, tmp_path: Path) -> None:
        """Calling _rehydrate_open_issue twice in succession produces the same state.

        The guard flag (_startup_check_done) must prevent a second API call so that
        a concurrent or repeated invocation cannot overwrite rehydrated state.
        """
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label = AsyncMock(return_value=[{"number": 77}])

        await loop._rehydrate_open_issue()
        assert loop._open_issue == 77

        # Mutate the mock to return a different result for a second API call
        pr.list_issues_by_label.return_value = [{"number": 99}]

        await loop._rehydrate_open_issue()

        # State must be unchanged; the second call must have been a no-op
        assert loop._open_issue == 77
        pr.list_issues_by_label.assert_awaited_once()  # called exactly once total

    @pytest.mark.asyncio
    async def test_rehydrate_does_not_duplicate_issue_on_restart(
        self, tmp_path: Path
    ) -> None:
        """After restart rehydration, a red CI poll must NOT create a second issue.

        This is the primary regression ADR-0029 guards against: without rehydration
        every process restart would call create_issue even though one already exists.
        """
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label = AsyncMock(return_value=[{"number": 55}])
        pr.get_latest_ci_status.return_value = (
            "failure",
            "https://github.com/runs/456",
        )

        # Simulate the first _do_work call after a process restart
        result = await loop._do_work()

        # Rehydration should have set _open_issue; create_issue must NOT be called
        assert loop._open_issue == 55
        pr.create_issue.assert_not_awaited()
        assert result is not None
        assert result["status"] == "red"
