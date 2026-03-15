"""Tests for verify_monitor_loop.py — VerifyMonitorLoop class."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.conftest import IssueFactory
from tests.helpers import make_bg_loop_deps


def _make_issue(number: int, *, state: str = "open"):
    """Create a mock GitHubIssue."""
    return IssueFactory.create(
        number=number,
        title=f"Verify issue #{number}",
        body="",
        labels=[],
        state=state,
    )


def _make_loop(tmp_path: Path, *, pending: dict[int, int] | None = None):
    """Build a VerifyMonitorLoop with mock dependencies."""
    from verify_monitor_loop import VerifyMonitorLoop

    deps = make_bg_loop_deps(tmp_path, verify_monitor_interval=60)

    fetcher = MagicMock()
    fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

    state = MagicMock()
    state.get_all_verification_issues = MagicMock(return_value=pending or {})
    state.record_outcome = MagicMock()
    state.clear_verification_issue = MagicMock()

    loop = VerifyMonitorLoop(
        config=deps.config,
        fetcher=fetcher,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, fetcher, state


class TestVerifyMonitorLoopNoPending:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_pending(self, tmp_path: Path) -> None:
        loop, fetcher, state = _make_loop(tmp_path, pending={})
        result = await loop._do_work()
        assert result is None
        fetcher.fetch_issue_by_number.assert_not_called()


class TestVerifyMonitorLoopOpenIssue:
    @pytest.mark.asyncio
    async def test_no_resolve_when_verify_issue_open(self, tmp_path: Path) -> None:
        verify_issue = _make_issue(42, state="open")
        loop, fetcher, state = _make_loop(tmp_path, pending={10: 42})
        fetcher.fetch_issue_by_number = AsyncMock(return_value=verify_issue)

        result = await loop._do_work()

        assert result == {"checked": 1, "resolved": 0, "pending": 1}
        state.record_outcome.assert_not_called()
        state.clear_verification_issue.assert_not_called()


class TestVerifyMonitorLoopClosedIssue:
    @pytest.mark.asyncio
    async def test_resolves_when_verify_issue_closed(self, tmp_path: Path) -> None:
        from models import IssueOutcomeType

        verify_issue = _make_issue(42, state="closed")
        loop, fetcher, state = _make_loop(tmp_path, pending={10: 42})
        fetcher.fetch_issue_by_number = AsyncMock(return_value=verify_issue)

        result = await loop._do_work()

        assert result == {"checked": 1, "resolved": 1, "pending": 1}
        state.record_outcome.assert_called_once_with(
            10,
            IssueOutcomeType.VERIFY_RESOLVED,
            reason="Verification issue #42 closed",
            phase="verify",
            verification_issue_number=42,
        )
        state.clear_verification_issue.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_multiple_pending_resolves_closed_only(self, tmp_path: Path) -> None:
        from models import IssueOutcomeType

        open_issue = _make_issue(100, state="open")
        closed_issue = _make_issue(101, state="closed")

        loop, fetcher, state = _make_loop(tmp_path, pending={20: 100, 21: 101})

        async def _fetch(number: int):
            if number == 100:
                return open_issue
            return closed_issue

        fetcher.fetch_issue_by_number = AsyncMock(side_effect=_fetch)

        result = await loop._do_work()

        assert result["checked"] == 2
        assert result["resolved"] == 1
        assert result["pending"] == 2
        state.record_outcome.assert_called_once_with(
            21,
            IssueOutcomeType.VERIFY_RESOLVED,
            reason="Verification issue #101 closed",
            phase="verify",
            verification_issue_number=101,
        )
        state.clear_verification_issue.assert_called_once_with(21)


class TestVerifyMonitorLoopNotFound:
    @pytest.mark.asyncio
    async def test_skips_when_verify_issue_not_found(self, tmp_path: Path) -> None:
        loop, fetcher, state = _make_loop(tmp_path, pending={10: 99})
        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        result = await loop._do_work()

        assert result == {"checked": 1, "resolved": 0, "pending": 1}
        state.record_outcome.assert_not_called()
        state.clear_verification_issue.assert_not_called()


class TestVerifyMonitorLoopErrorHandling:
    @pytest.mark.asyncio
    async def test_continues_on_fetch_exception(self, tmp_path: Path) -> None:

        closed_issue = _make_issue(200, state="closed")

        loop, fetcher, state = _make_loop(tmp_path, pending={10: 50, 11: 200})

        call_count = 0

        async def _fetch(number: int):
            nonlocal call_count
            call_count += 1
            if number == 50:
                raise RuntimeError("Network error")
            return closed_issue

        fetcher.fetch_issue_by_number = AsyncMock(side_effect=_fetch)

        result = await loop._do_work()

        # Should process both, but only resolve the non-failing one
        assert result is not None
        assert result["resolved"] == 1
        state.record_outcome.assert_called_once()


class TestVerifyMonitorLoopDefaultInterval:
    def test_default_interval_from_config(self, tmp_path: Path) -> None:
        loop, _, _ = _make_loop(tmp_path)
        assert loop._get_default_interval() == loop._config.verify_monitor_interval
