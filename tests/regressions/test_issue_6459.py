"""Regression test for issue #6459.

CIMonitorLoop._do_work uses ``except Exception:`` on both the CI status
fetch (line 67) and the issue-close recovery path (line 88). Because
AuthenticationError and CreditExhaustedError are subclasses of
RuntimeError (which is a subclass of Exception), they get swallowed
inside _do_work and never propagate to BaseBackgroundLoop._execute_cycle,
which is the layer that re-raises them as fatal errors.

The tests below verify that these fatal errors escape _do_work so the
loop supervisor can shut down the loop.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ci_monitor_loop import CIMonitorLoop
from subprocess_util import AuthenticationError, CreditExhaustedError
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
    pr_manager.list_issues_by_label = AsyncMock(return_value=[])

    loop = CIMonitorLoop(
        config=deps.config,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, pr_manager


class TestAuthenticationErrorNotSwallowed:
    """AuthenticationError must escape _do_work so the loop supervisor can
    re-raise it. Currently the broad ``except Exception:`` swallows it."""

    @pytest.mark.asyncio
    async def test_auth_error_on_ci_status_fetch_propagates(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from get_latest_ci_status must not be caught."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.get_latest_ci_status.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_auth_error_on_issue_close_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError from close_issue must not be caught."""
        loop, _stop, pr = _make_loop(tmp_path)

        # First: create an open issue via a red CI status
        pr.get_latest_ci_status.return_value = (
            "failure",
            "https://github.com/runs/123",
        )
        await loop._do_work()
        assert loop._open_issue == 999

        # Now CI recovers, but close_issue raises AuthenticationError
        pr.get_latest_ci_status.return_value = ("success", "")
        pr.post_comment.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()


class TestCreditExhaustedErrorNotSwallowed:
    """CreditExhaustedError must escape _do_work so the loop supervisor can
    re-raise it. Currently the broad ``except Exception:`` swallows it."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_on_ci_status_fetch_propagates(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError from get_latest_ci_status must not be caught."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.get_latest_ci_status.side_effect = CreditExhaustedError("Credits exhausted")

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_credit_exhausted_on_issue_close_propagates(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError from close_issue must not be caught."""
        loop, _stop, pr = _make_loop(tmp_path)

        # First: create an open issue via a red CI status
        pr.get_latest_ci_status.return_value = (
            "failure",
            "https://github.com/runs/123",
        )
        await loop._do_work()
        assert loop._open_issue == 999

        # Now CI recovers, but close_issue raises CreditExhaustedError
        pr.get_latest_ci_status.return_value = ("success", "")
        pr.close_issue.side_effect = CreditExhaustedError("Credits exhausted")

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()


class TestTransientErrorsStillCaught:
    """RuntimeError (transient) should still be caught and logged — this is
    existing correct behavior that must be preserved after the fix."""

    @pytest.mark.asyncio
    async def test_runtime_error_on_ci_status_is_caught(self, tmp_path: Path) -> None:
        """Transient RuntimeError on fetch should be caught, not propagated."""
        loop, _stop, pr = _make_loop(tmp_path)
        pr.get_latest_ci_status.side_effect = RuntimeError("API timeout")

        # Should NOT raise — transient errors are handled gracefully
        result = await loop._do_work()
        assert result is not None
        assert result.get("error") is True

    @pytest.mark.asyncio
    async def test_runtime_error_on_issue_close_is_caught(self, tmp_path: Path) -> None:
        """Transient RuntimeError on close should be caught, not propagated."""
        loop, _stop, pr = _make_loop(tmp_path)

        # Create an open issue
        pr.get_latest_ci_status.return_value = (
            "failure",
            "https://github.com/runs/123",
        )
        await loop._do_work()
        assert loop._open_issue == 999

        # CI recovers but close fails with transient error
        pr.get_latest_ci_status.return_value = ("success", "")
        pr.close_issue.side_effect = RuntimeError("API timeout")

        # Should NOT raise — transient errors are handled gracefully
        result = await loop._do_work()
        assert result is not None
        assert result["status"] == "green"
        # Open issue retained for retry
        assert loop._open_issue == 999
