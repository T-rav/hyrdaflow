"""Tests for the StaleIssueGCLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from stale_issue_gc_loop import StaleIssueGCLoop
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
) -> tuple[StaleIssueGCLoop, asyncio.Event, MagicMock]:
    """Build a StaleIssueGCLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=enabled)
    pr_manager = MagicMock()
    pr_manager.list_issues_by_label = AsyncMock(return_value=[])
    pr_manager.close_issue = AsyncMock()
    pr_manager.post_comment = AsyncMock()
    pr_manager.get_issue_updated_at = AsyncMock(return_value="2026-03-01T00:00:00Z")

    loop = StaleIssueGCLoop(
        config=deps.config,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, pr_manager


class TestStaleIssueGCLoop:
    """Tests for StaleIssueGCLoop._do_work."""

    @pytest.mark.asyncio
    async def test_no_issues_returns_zero(self, tmp_path: Path) -> None:
        """When no HITL issues exist, _do_work returns zero closed."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label.return_value = []
        result = await loop._do_work()
        assert result is not None
        assert result["closed"] == 0

    @pytest.mark.asyncio
    async def test_stale_issue_is_closed(self, tmp_path: Path) -> None:
        """An issue with no activity beyond the threshold is closed."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label.return_value = [
            {"number": 100, "title": "Stale bug", "updated_at": "2026-03-01T00:00:00Z"},
        ]
        pr.get_issue_updated_at.return_value = "2026-03-01T00:00:00Z"

        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 1
        pr.post_comment.assert_awaited_once()
        pr.close_issue.assert_awaited_once_with(100)

    @pytest.mark.asyncio
    async def test_fresh_issue_is_not_closed(self, tmp_path: Path) -> None:
        """An issue with recent activity is kept open."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label.return_value = [
            {"number": 200, "title": "Fresh bug", "updated_at": "2099-01-01T00:00:00Z"},
        ]
        pr.get_issue_updated_at.return_value = "2099-01-01T00:00:00Z"

        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 0
        pr.close_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_comment_explains_auto_close(self, tmp_path: Path) -> None:
        """The auto-close comment includes the reason."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label.return_value = [
            {"number": 300, "title": "Old bug", "updated_at": "2026-03-01T00:00:00Z"},
        ]
        pr.get_issue_updated_at.return_value = "2026-03-01T00:00:00Z"

        await loop._do_work()

        comment = pr.post_comment.call_args[0][1]
        assert "auto-clos" in comment.lower()
        assert "no activity" in comment.lower() or "stale" in comment.lower()

    @pytest.mark.asyncio
    async def test_mixed_stale_and_fresh(self, tmp_path: Path) -> None:
        """Only stale issues are closed; fresh ones are kept."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label.return_value = [
            {"number": 400, "title": "Stale", "updated_at": "2026-03-01T00:00:00Z"},
            {"number": 401, "title": "Fresh", "updated_at": "2099-01-01T00:00:00Z"},
        ]

        async def get_updated(issue_number: int) -> str:
            return (
                "2026-03-01T00:00:00Z"
                if issue_number == 400
                else "2099-01-01T00:00:00Z"
            )

        pr.get_issue_updated_at.side_effect = get_updated

        result = await loop._do_work()

        assert result["closed"] == 1
        pr.close_issue.assert_awaited_once_with(400)

    @pytest.mark.asyncio
    async def test_api_error_skips_issue(self, tmp_path: Path) -> None:
        """API errors for individual issues are caught and skipped."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label.return_value = [
            {"number": 500, "title": "Error bug", "updated_at": "2026-03-01T00:00:00Z"},
        ]
        pr.get_issue_updated_at.side_effect = RuntimeError("API failed")

        result = await loop._do_work()

        assert result["closed"] == 0
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        """In dry-run mode, _do_work returns None without closing anything."""
        deps = make_bg_loop_deps(tmp_path, dry_run=True)
        pr = MagicMock()
        loop = StaleIssueGCLoop(config=deps.config, pr_manager=pr, deps=deps.loop_deps)
        result = await loop._do_work()
        assert result is None
        pr.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_updated_at_skips_issue(self, tmp_path: Path) -> None:
        """An issue with empty updated_at is skipped, not crashed."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.list_issues_by_label.return_value = [
            {"number": 600, "title": "No timestamp", "updated_at": ""},
        ]
        pr.get_issue_updated_at.return_value = ""
        result = await loop._do_work()
        assert result["closed"] == 0
        assert result["skipped"] == 1
        pr.close_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_default_interval_from_config(self, tmp_path: Path) -> None:
        """_get_default_interval reads from config."""
        loop, _stop, _pr = _make_loop(tmp_path)
        assert loop._get_default_interval() == 3600
