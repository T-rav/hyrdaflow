"""Tests for verify_monitor_loop.py — VerifyMonitorLoop class."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import make_bg_loop_deps


def _make_issue(number: int, *, state: str = "open"):
    """Create a mock GitHubIssue."""
    from models import GitHubIssue, GitHubIssueState

    return GitHubIssue(
        number=number,
        title=f"Verify issue #{number}",
        body="",
        labels=[],
        state=GitHubIssueState(state),
    )


def _make_outcome(outcome_type, *, phase: str = "verify"):
    """Create a mock IssueOutcome."""
    from models import IssueOutcome

    return IssueOutcome(
        outcome=outcome_type,
        reason="test",
        closed_at="2026-01-01T00:00:00+00:00",
        phase=phase,
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
    state.record_outcome = MagicMock()
    state.clear_verification_issue = MagicMock()
    state.get_all_outcomes = MagicMock(return_value=outcomes or {})

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
        loop, fetcher, _ = _make_loop(tmp_path, pending={})
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

        assert result == {"checked": 1, "resolved": 0, "reconciled": 0, "pending": 1}
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

        assert result == {
            "checked": 1,
            "resolved": 1,
            "reconciled": 0,
            "pending": 0,
        }
        state.record_outcome.assert_called_once_with(
            10,
            IssueOutcomeType.MERGED,
            reason="Verification issue #42 closed — promoted to merged",
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

        assert result is not None
        assert result["checked"] == 2
        assert result["resolved"] == 1
        assert result["reconciled"] == 0
        assert result["pending"] == 1
        state.record_outcome.assert_called_once_with(
            21,
            IssueOutcomeType.MERGED,
            reason="Verification issue #101 closed — promoted to merged",
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

        assert result == {
            "checked": 1,
            "resolved": 1,
            "reconciled": 0,
            "pending": 0,
        }
        state.record_outcome.assert_called_once_with(
            10,
            IssueOutcomeType.MERGED,
            reason="Verification issue #99 not found — auto-resolved to merged",
            phase="verify",
            verification_issue_number=99,
        )
        state.clear_verification_issue.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_not_found_clears_verification_entry(self, tmp_path: Path) -> None:
        """Bug A: not-found verify issues must clear their verification_issues entry."""
        loop, fetcher, state = _make_loop(tmp_path, pending={5: 77, 6: 78})
        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        result = await loop._do_work()

        assert result is not None
        assert result["resolved"] == 2
        assert state.clear_verification_issue.call_count == 2


class TestVerifyMonitorLoopOrphanedOutcomes:
    @pytest.mark.asyncio
    async def test_reconciles_orphaned_verify_pending_no_other_pending(
        self, tmp_path: Path
    ) -> None:
        """Bug B: orphan reconciliation runs even when pending dict is empty."""
        from models import IssueOutcomeType

        orphan_outcome = _make_outcome(IssueOutcomeType.VERIFY_PENDING)
        loop, _, state = _make_loop(
            tmp_path,
            pending={},
            outcomes={"30": orphan_outcome},
        )

        result = await loop._do_work()

        assert result is not None
        assert result["reconciled"] == 1
        assert result["checked"] == 0
        assert result["resolved"] == 0
        state.record_outcome.assert_called_once_with(
            30,
            IssueOutcomeType.MERGED,
            reason="Orphaned verify_pending — verification issue missing, promoted to merged",
            phase="verify",
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_no_pending_and_no_orphans(
        self, tmp_path: Path
    ) -> None:
        """Returns None when there is genuinely nothing to do."""
        loop, _, state = _make_loop(tmp_path, pending={}, outcomes={})

        result = await loop._do_work()

        assert result is None
        state.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconciles_orphaned_verify_pending_alongside_pending(
        self, tmp_path: Path
    ) -> None:
        """Bug B: orphan reconciliation also runs when some pending entries exist."""
        from models import IssueOutcomeType

        orphan_outcome = _make_outcome(IssueOutcomeType.VERIFY_PENDING)
        loop, fetcher, state = _make_loop(
            tmp_path,
            pending={10: 42},
            outcomes={"30": orphan_outcome},
        )
        fetcher.fetch_issue_by_number = AsyncMock(
            return_value=_make_issue(42, state="closed")
        )

        result = await loop._do_work()

        assert result is not None
        assert result["reconciled"] == 1
        # record_outcome called twice: once for the closed verify, once for reconciliation
        assert state.record_outcome.call_count == 2
        state.record_outcome.assert_any_call(
            30,
            IssueOutcomeType.MERGED,
            reason="Orphaned verify_pending — verification issue missing, promoted to merged",
            phase="verify",
        )

    @pytest.mark.asyncio
    async def test_does_not_reconcile_pending_with_verification_entry(
        self, tmp_path: Path
    ) -> None:
        """VERIFY_PENDING outcomes WITH a verification_issues entry are not orphaned."""
        from models import IssueOutcomeType

        # Issue 10 has VERIFY_PENDING outcome AND is in pending dict → not orphaned
        non_orphan = _make_outcome(IssueOutcomeType.VERIFY_PENDING)
        loop, fetcher, state = _make_loop(
            tmp_path,
            pending={10: 42},
            outcomes={"10": non_orphan},
        )
        fetcher.fetch_issue_by_number = AsyncMock(
            return_value=_make_issue(42, state="open")
        )

        result = await loop._do_work()

        assert result is not None
        assert result["reconciled"] == 0
        state.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_reconcile_non_verify_outcomes(self, tmp_path: Path) -> None:
        """Only VERIFY_PENDING/VERIFY_RESOLVED outcomes should be reconciled, not MERGED etc."""
        from models import IssueOutcomeType

        merged_outcome = _make_outcome(IssueOutcomeType.MERGED, phase="review")
        loop, fetcher, state = _make_loop(
            tmp_path,
            pending={10: 42},
            outcomes={"30": merged_outcome},
        )
        fetcher.fetch_issue_by_number = AsyncMock(
            return_value=_make_issue(42, state="open")
        )

        result = await loop._do_work()

        assert result is not None
        assert result["reconciled"] == 0
        state.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconciles_stale_verify_resolved_to_merged(
        self, tmp_path: Path
    ) -> None:
        """VERIFY_RESOLVED outcomes are promoted to MERGED during reconciliation."""
        from models import IssueOutcomeType

        stale_resolved = _make_outcome(IssueOutcomeType.VERIFY_RESOLVED)
        loop, _, state = _make_loop(
            tmp_path,
            pending={},
            outcomes={"40": stale_resolved},
        )

        result = await loop._do_work()

        assert result is not None
        assert result["reconciled"] == 1
        state.record_outcome.assert_called_once_with(
            40,
            IssueOutcomeType.MERGED,
            reason="Stale verify_resolved — promoted to merged",
            phase="verify",
        )

    @pytest.mark.asyncio
    async def test_reconciles_multiple_orphans(self, tmp_path: Path) -> None:
        """Multiple orphaned VERIFY_PENDING outcomes all get resolved."""
        from models import IssueOutcomeType

        orphan1 = _make_outcome(IssueOutcomeType.VERIFY_PENDING)
        orphan2 = _make_outcome(IssueOutcomeType.VERIFY_PENDING)
        merged = _make_outcome(IssueOutcomeType.MERGED, phase="review")
        loop, fetcher, state = _make_loop(
            tmp_path,
            pending={10: 42},
            outcomes={"30": orphan1, "31": orphan2, "32": merged},
        )
        fetcher.fetch_issue_by_number = AsyncMock(
            return_value=_make_issue(42, state="open")
        )

        result = await loop._do_work()

        assert result is not None
        assert result["reconciled"] == 2
        reconcile_calls = [
            c
            for c in state.record_outcome.call_args_list
            if c
            == call(
                30,
                IssueOutcomeType.MERGED,
                reason="Orphaned verify_pending — verification issue missing, promoted to merged",
                phase="verify",
            )
            or c
            == call(
                31,
                IssueOutcomeType.MERGED,
                reason="Orphaned verify_pending — verification issue missing, promoted to merged",
                phase="verify",
            )
        ]
        assert len(reconcile_calls) == 2

    @pytest.mark.asyncio
    async def test_continues_on_record_outcome_exception(self, tmp_path: Path) -> None:
        """Per-item exception handling: one failing record_outcome doesn't abort others."""
        from models import IssueOutcomeType

        orphan1 = _make_outcome(IssueOutcomeType.VERIFY_PENDING)
        orphan2 = _make_outcome(IssueOutcomeType.VERIFY_PENDING)
        loop, _, state = _make_loop(
            tmp_path,
            pending={},
            outcomes={"30": orphan1, "31": orphan2},
        )

        call_count = 0

        def _record(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("State write failure")

        state.record_outcome = _record

        result = await loop._do_work()

        # One failed, one succeeded — reconciled count = 1
        assert result is not None
        assert result["reconciled"] == 1


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
        # record_outcome called once for the closed issue (not for the errored one)
        assert any(
            c[0][1].value == "merged" for c in state.record_outcome.call_args_list
        )


class TestVerifyMonitorLoopDefaultInterval:
    def test_default_interval_from_config(self, tmp_path: Path) -> None:
        loop, _, _ = _make_loop(tmp_path)
        assert loop._get_default_interval() == loop._config.verify_monitor_interval
