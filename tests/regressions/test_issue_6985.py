"""Regression test for issue #6985.

``PRManager.get_issue_updated_at`` makes a raw ``_run_gh`` call with no
try/except.  When the subprocess raises ``AuthenticationError`` (expired
credentials, rate-limit 401, etc.), the exception propagates into
``StaleIssueGCLoop._do_work`` where a broad ``except Exception`` silently
swallows it, increments the per-issue error counter, and retries on the
next cycle — forever.  Authentication failures should instead propagate
out of the loop so the harness can surface the real problem.

Strategy
--------
Mock ``get_issue_updated_at`` to raise ``AuthenticationError``.  Call
``StaleIssueGCLoop._do_work`` and assert that ``AuthenticationError``
propagates.  Today the broad ``except Exception`` catches it and the
method returns a dict with ``errors >= 1`` — the test therefore fails,
proving the bug.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from stale_issue_gc_loop import StaleIssueGCLoop
from subprocess_util import AuthenticationError
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
) -> tuple[StaleIssueGCLoop, asyncio.Event, MagicMock]:
    """Build a StaleIssueGCLoop with a mock PRManager."""
    deps = make_bg_loop_deps(tmp_path, enabled=True)
    pr_manager = MagicMock()
    pr_manager.list_issues_by_label = AsyncMock(
        return_value=[
            {"number": 42, "title": "Stuck HITL", "updated_at": "2026-03-01T00:00:00Z"},
        ],
    )
    pr_manager.close_issue = AsyncMock()
    pr_manager.post_comment = AsyncMock()
    # Simulate an authentication failure from the gh CLI
    pr_manager.get_issue_updated_at = AsyncMock(
        side_effect=AuthenticationError("gh: authentication required"),
    )

    loop = StaleIssueGCLoop(
        config=deps.config,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, pr_manager


class TestAuthErrorPropagatesFromGCLoop:
    """AuthenticationError must not be silently swallowed by StaleIssueGCLoop."""

    @pytest.mark.asyncio
    async def test_auth_error_propagates_out_of_do_work(self, tmp_path: Path) -> None:
        """When get_issue_updated_at raises AuthenticationError, _do_work
        must let it propagate rather than catching it as a per-issue error.

        BUG: The broad ``except Exception`` at stale_issue_gc_loop.py:106
        catches AuthenticationError, increments ``errors``, and returns
        normally.  This test expects the exception to propagate — it will
        fail (RED) until the handler is fixed to re-raise auth errors.
        """
        loop, _stop, _pr = _make_loop(tmp_path)

        with pytest.raises(AuthenticationError):
            await loop._do_work()
