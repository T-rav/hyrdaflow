"""Tests for the StaleIssueLoop background worker."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import StaleIssueSettings
from stale_issue_loop import StaleIssueLoop
from tests.helpers import make_bg_loop_deps


def _gh_issue_json(
    number: int,
    title: str = "Some issue",
    updated_at: str | None = None,
    labels: list[str] | None = None,
) -> dict:
    """Build a dict matching `gh issue list --json` output."""
    if updated_at is None:
        updated_at = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    label_objs = [{"name": lbl} for lbl in (labels or [])]
    return {
        "number": number,
        "title": title,
        "updatedAt": updated_at,
        "labels": label_objs,
    }


def _make_state(
    *,
    staleness_days: int = 30,
    excluded_labels: list[str] | None = None,
    dry_run: bool = False,
    already_closed: set[int] | None = None,
) -> MagicMock:
    """Build a mock StateTracker with stale issue methods."""
    state = MagicMock()
    settings = StaleIssueSettings(
        staleness_days=staleness_days,
        excluded_labels=excluded_labels or [],
        dry_run=dry_run,
    )
    state.get_stale_issue_settings.return_value = settings
    state.get_stale_issue_closed.return_value = already_closed or set()
    return state


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 86400,
    gh_issues: list[dict] | None = None,
    staleness_days: int = 30,
    excluded_labels: list[str] | None = None,
    dry_run: bool = False,
    already_closed: set[int] | None = None,
) -> tuple[StaleIssueLoop, MagicMock, MagicMock]:
    """Build a StaleIssueLoop with test-friendly defaults.

    Returns (loop, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, stale_issue_interval=interval)

    prs = MagicMock()
    prs._repo = "owner/repo"
    prs._run_gh = AsyncMock(return_value=json.dumps(gh_issues) if gh_issues else "[]")
    prs.post_comment = AsyncMock()

    state = _make_state(
        staleness_days=staleness_days,
        excluded_labels=excluded_labels,
        dry_run=dry_run,
        already_closed=already_closed,
    )

    loop = StaleIssueLoop(
        config=deps.config,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, prs, state


class TestStaleIssueLoopInterval:
    def test_default_interval_uses_config(self, tmp_path: Path) -> None:
        loop, *_ = _make_loop(tmp_path, interval=86400)
        assert loop._get_default_interval() == 86400


class TestStaleIssueLoopDoWork:
    @pytest.mark.asyncio
    async def test_no_issues_returns_zeroes(self, tmp_path: Path) -> None:
        """When there are no open issues, all counters are zero."""
        loop, *_ = _make_loop(tmp_path, gh_issues=[])
        result = await loop._do_work()
        assert result == {"scanned": 0, "closed": 0, "skipped": 0}

    @pytest.mark.asyncio
    async def test_stale_issue_gets_closed(self, tmp_path: Path) -> None:
        """An issue with old updatedAt is commented and closed."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(42, updated_at=old_date)]
        loop, prs, state = _make_loop(tmp_path, gh_issues=issues)

        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 1
        assert result["scanned"] == 1
        prs.post_comment.assert_awaited_once()
        # Verify close was called via _run_gh
        close_calls = [c for c in prs._run_gh.await_args_list if "close" in c.args]
        assert len(close_calls) == 1
        state.add_stale_issue_closed.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_non_stale_issue_skipped(self, tmp_path: Path) -> None:
        """An issue updated recently is not closed."""
        recent_date = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        issues = [_gh_issue_json(10, updated_at=recent_date)]
        loop, prs, state = _make_loop(tmp_path, gh_issues=issues)

        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 0
        assert result["scanned"] == 1
        prs.post_comment.assert_not_awaited()
        state.add_stale_issue_closed.assert_not_called()

    @pytest.mark.asyncio
    async def test_excluded_label_skips_issue(self, tmp_path: Path) -> None:
        """Issues with excluded labels are skipped entirely."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(7, updated_at=old_date, labels=["keep-open"])]
        loop, prs, state = _make_loop(
            tmp_path,
            gh_issues=issues,
            excluded_labels=["keep-open"],
        )

        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] == 1
        assert result["scanned"] == 0
        assert result["closed"] == 0
        prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_closed_issue_skipped(self, tmp_path: Path) -> None:
        """Issues already in the closed set are skipped."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(99, updated_at=old_date)]
        loop, prs, state = _make_loop(
            tmp_path,
            gh_issues=issues,
            already_closed={99},
        )

        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] == 1
        assert result["scanned"] == 0
        assert result["closed"] == 0
        prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dry_run_logs_but_does_not_close(self, tmp_path: Path) -> None:
        """In dry_run mode, stale issues are counted but not actually closed."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(15, updated_at=old_date)]
        loop, prs, state = _make_loop(tmp_path, gh_issues=issues, dry_run=True)

        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 1
        assert result["scanned"] == 1
        # Should NOT have called post_comment or close
        prs.post_comment.assert_not_awaited()
        close_calls = [c for c in prs._run_gh.await_args_list if "close" in c.args]
        assert len(close_calls) == 0
        state.add_stale_issue_closed.assert_not_called()

    @pytest.mark.asyncio
    async def test_sentry_breadcrumb_emitted(self, tmp_path: Path) -> None:
        """When sentry_sdk is available, a breadcrumb is added."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(5, updated_at=old_date)]
        loop, prs, state = _make_loop(tmp_path, gh_issues=issues)

        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            await loop._do_work()

        mock_sentry.add_breadcrumb.assert_called_once()
        call_kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert call_kwargs["category"] == "stale_issue.cycle"
        assert "1" in call_kwargs["message"]  # scanned count

    @pytest.mark.asyncio
    async def test_gh_fetch_failure_returns_stats(self, tmp_path: Path) -> None:
        """If fetching issues fails, stats are returned with zeroes."""
        loop, prs, state = _make_loop(tmp_path)
        prs._run_gh = AsyncMock(side_effect=RuntimeError("network error"))

        result = await loop._do_work()

        assert result == {"scanned": 0, "closed": 0, "skipped": 0}

    @pytest.mark.asyncio
    async def test_lifecycle_labels_excluded_by_default(
        self,
        tmp_path: Path,
    ) -> None:
        """Issues with HydraFlow lifecycle labels are skipped."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [
            _gh_issue_json(1, updated_at=old_date, labels=["hydraflow-plan"]),
        ]
        loop, prs, _ = _make_loop(tmp_path, gh_issues=issues)

        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] == 1
        assert result["closed"] == 0
