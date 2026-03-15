"""Tests for verify_monitor_loop.py — VerifyMonitorLoop class."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import make_bg_loop_deps


def _make_issue(number: int, *, state: str = "open"):
    """Create a mock GitHubIssue."""
    from models import GitHubIssue

    return GitHubIssue(
        number=number,
        title=f"Verify issue #{number}",
        body="",
        labels=[],
        state=state,
    )


def _make_loop(
    tmp_path: Path,
    *,
    pending: dict[int, int] | None = None,
    outcomes: dict[str, object] | None = None,
):
    """Build a VerifyMonitorLoop with mock dependencies."""
    from verify_monitor_loop import VerifyMonitorLoop

    deps = make_bg_loop_deps(tmp_path, verify_monitor_interval=60)

    fetcher = MagicMock()
    fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

    state = MagicMock()
    state.get_all_verification_issues = MagicMock(return_value=pending or {})
    state.get_all_outcomes = MagicMock(return_value=outcomes or {})
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
    async def test_resolves_when_verify_issue_not_found(self, tmp_path: Path) -> None:
        """Bug A: not-found verify issues should be treated as resolved."""
        from models import IssueOutcomeType

        loop, fetcher, state = _make_loop(tmp_path, pending={10: 99})
        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        result = await loop._do_work()

        assert result == {"checked": 1, "resolved": 1, "pending": 1}
        state.record_outcome.assert_called_once_with(
            10,
            IssueOutcomeType.VERIFY_RESOLVED,
            reason="Verification issue #99 not found (deleted/inaccessible)",
            phase="verify",
            verification_issue_number=99,
        )
        state.clear_verification_issue.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_not_found_clears_verification_entry(self, tmp_path: Path) -> None:
        """Bug A: not-found should also clear the verification_issues mapping."""
        loop, fetcher, state = _make_loop(tmp_path, pending={10: 99, 20: 88})
        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        result = await loop._do_work()

        assert result is not None
        assert result["resolved"] == 2
        assert state.clear_verification_issue.call_count == 2


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


class TestVerifyMonitorLoopOrphanedReconciliation:
    """Bug B: orphaned VERIFY_PENDING outcomes with no verification_issues entry."""

    @pytest.mark.asyncio
    async def test_reconciles_orphaned_verify_pending(self, tmp_path: Path) -> None:
        """Outcome is VERIFY_PENDING but no verification_issues entry exists."""
        from models import IssueOutcome, IssueOutcomeType

        orphaned_outcome = IssueOutcome(
            outcome=IssueOutcomeType.VERIFY_PENDING,
            reason="Awaiting verification",
            closed_at="2026-01-01T00:00:00Z",
            phase="verify",
            verification_issue_number=555,
        )
        loop, _fetcher, state = _make_loop(
            tmp_path,
            pending={},  # no active verification issues
            outcomes={"30": orphaned_outcome},
        )

        result = await loop._do_work()

        # No pending verification issues to check, but reconciliation finds orphan
        assert result is not None
        assert result["resolved"] == 1
        state.record_outcome.assert_called_once_with(
            30,
            IssueOutcomeType.VERIFY_RESOLVED,
            reason="Orphaned verify_pending — no active verification issue found",
            phase="verify",
            verification_issue_number=555,
        )

    @pytest.mark.asyncio
    async def test_no_reconciliation_when_verification_entry_exists(
        self, tmp_path: Path
    ) -> None:
        """VERIFY_PENDING outcome with active verification_issues entry should NOT be reconciled."""
        from models import IssueOutcome, IssueOutcomeType

        active_outcome = IssueOutcome(
            outcome=IssueOutcomeType.VERIFY_PENDING,
            reason="Awaiting verification",
            closed_at="2026-01-01T00:00:00Z",
            phase="verify",
            verification_issue_number=42,
        )
        open_issue = _make_issue(42, state="open")
        loop, fetcher, state = _make_loop(
            tmp_path,
            pending={10: 42},  # active verification issue
            outcomes={"10": active_outcome},
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=open_issue)

        result = await loop._do_work()

        # Issue is still open and has active mapping — should not reconcile
        assert result is not None
        state.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_non_verify_pending_outcomes(self, tmp_path: Path) -> None:
        """Outcomes with types other than VERIFY_PENDING should not be touched."""
        from models import IssueOutcome, IssueOutcomeType

        merged_outcome = IssueOutcome(
            outcome=IssueOutcomeType.MERGED,
            reason="PR merged",
            closed_at="2026-01-01T00:00:00Z",
            phase="review",
        )
        loop, _fetcher, state = _make_loop(
            tmp_path,
            pending={},
            outcomes={"50": merged_outcome},
        )

        result = await loop._do_work()

        # No pending and no orphans — returns None
        assert result is None
        state.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconciles_multiple_orphans(self, tmp_path: Path) -> None:
        """Multiple orphaned VERIFY_PENDING outcomes should all be reconciled."""
        from models import IssueOutcome, IssueOutcomeType

        orphan1 = IssueOutcome(
            outcome=IssueOutcomeType.VERIFY_PENDING,
            reason="Awaiting",
            closed_at="2026-01-01T00:00:00Z",
            phase="verify",
            verification_issue_number=100,
        )
        orphan2 = IssueOutcome(
            outcome=IssueOutcomeType.VERIFY_PENDING,
            reason="Awaiting",
            closed_at="2026-01-01T00:00:00Z",
            phase="verify",
            verification_issue_number=200,
        )
        loop, _fetcher, state = _make_loop(
            tmp_path,
            pending={},
            outcomes={"60": orphan1, "70": orphan2},
        )

        result = await loop._do_work()

        assert result is not None
        assert result["resolved"] == 2
        assert state.record_outcome.call_count == 2


class TestVerifyMonitorLoopDefaultInterval:
    def test_default_interval_from_config(self, tmp_path: Path) -> None:
        loop, _, _ = _make_loop(tmp_path)
        assert loop._get_default_interval() == loop._config.verify_monitor_interval
