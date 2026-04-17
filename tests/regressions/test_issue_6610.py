"""Regression test for issue #6610.

Bug: ``StaleIssueLoop._do_work`` (line 68) and ``StaleIssueGCLoop._do_work``
(line 63) use ``except Exception`` on GitHub API calls without first
checking for ``AuthenticationError``.  An expired or revoked token is
treated as a transient per-item error — the loop logs the exception and
retries next cycle forever, with no escalation.

Expected behaviour after fix:
  - ``AuthenticationError`` propagates out of ``_do_work`` so the loop
    supervisor can handle it (alert, back off, etc.).
  - Other transient ``Exception`` subclasses are still caught gracefully.

These tests are RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from models import StaleIssueSettings  # noqa: E402
from stale_issue_gc_loop import StaleIssueGCLoop  # noqa: E402
from stale_issue_loop import StaleIssueLoop  # noqa: E402
from subprocess_util import AuthenticationError  # noqa: E402
from tests.helpers import make_bg_loop_deps  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stale_issue_loop(
    tmp_path: Path,
) -> tuple[StaleIssueLoop, MagicMock, MagicMock]:
    """Build a StaleIssueLoop with test-friendly mocks.

    Returns (loop, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    prs = MagicMock()
    prs._repo = "owner/repo"
    prs._run_gh = AsyncMock(return_value="[]")
    prs.post_comment = AsyncMock()

    state = MagicMock()
    state.get_stale_issue_settings = MagicMock(return_value=StaleIssueSettings())
    state.get_stale_issue_closed = MagicMock(return_value=set())
    state.add_stale_issue_closed = MagicMock()

    loop = StaleIssueLoop(
        config=deps.config,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, prs, state


def _make_stale_issue_gc_loop(
    tmp_path: Path,
) -> tuple[StaleIssueGCLoop, MagicMock]:
    """Build a StaleIssueGCLoop with test-friendly mocks.

    Returns (loop, prs_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    prs = MagicMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    prs.get_issue_updated_at = AsyncMock(return_value=None)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()

    loop = StaleIssueGCLoop(
        config=deps.config,
        pr_manager=prs,
        deps=deps.loop_deps,
    )
    return loop, prs


# ---------------------------------------------------------------------------
# StaleIssueLoop — AuthenticationError on issue list fetch (line 68)
# ---------------------------------------------------------------------------


class TestStaleIssueLoopAuthErrorOnFetch:
    """Issue #6610 finding 1 — ``except Exception`` at line 68 of
    ``stale_issue_loop.py`` swallows ``AuthenticationError`` from the
    ``_run_gh`` call that fetches the issue list.
    """

    @pytest.mark.asyncio
    async def test_authentication_error_propagates_from_fetch(
        self, tmp_path: Path
    ) -> None:
        """When ``_run_gh`` raises ``AuthenticationError``, ``_do_work``
        must let it propagate rather than returning stats dict.

        Currently FAILS (RED) because the broad ``except Exception`` at
        line 68 catches ``AuthenticationError`` and silently returns
        ``{"scanned": 0, "closed": 0, "skipped": 0}``.
        """
        loop, prs, _ = _make_stale_issue_loop(tmp_path)
        prs._run_gh.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_transient_error_still_caught_on_fetch(self, tmp_path: Path) -> None:
        """A non-auth ``Exception`` (e.g. network timeout) should still be
        caught and the method should return zero-count stats.

        This is GREEN on the current code and should remain GREEN after fix.
        """
        loop, prs, _ = _make_stale_issue_loop(tmp_path)
        prs._run_gh.side_effect = RuntimeError("network timeout")

        result = await loop._do_work()

        assert result == {"scanned": 0, "closed": 0, "skipped": 0}


# ---------------------------------------------------------------------------
# StaleIssueLoop — AuthenticationError on per-issue close (line 132)
# ---------------------------------------------------------------------------


class TestStaleIssueLoopAuthErrorOnClose:
    """Issue #6610 finding 3 — ``except Exception`` at line 132 of
    ``stale_issue_loop.py`` swallows ``AuthenticationError`` when closing
    a single stale issue mid-batch.
    """

    @pytest.mark.asyncio
    async def test_authentication_error_propagates_from_close(
        self, tmp_path: Path
    ) -> None:
        """When ``post_comment`` raises ``AuthenticationError`` during
        the per-issue close action, ``_do_work`` must let it propagate.

        Currently FAILS (RED) because the broad ``except Exception`` at
        line 132 catches it and continues to the next issue.
        """
        loop, prs, state = _make_stale_issue_loop(tmp_path)

        # Return one stale issue (updated long ago)
        import json

        stale_issue = json.dumps(
            [
                {
                    "number": 42,
                    "title": "old issue",
                    "updatedAt": "2020-01-01T00:00:00Z",
                    "labels": [],
                }
            ]
        )
        prs._run_gh.side_effect = AsyncMock(return_value=stale_issue)
        # The close path calls post_comment first — make it raise
        prs.post_comment.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()


# ---------------------------------------------------------------------------
# StaleIssueGCLoop — AuthenticationError on label fetch (line 63)
# ---------------------------------------------------------------------------


class TestStaleIssueGCLoopAuthErrorOnFetch:
    """Issue #6610 finding 2 — ``except Exception`` at line 63 of
    ``stale_issue_gc_loop.py`` swallows ``AuthenticationError`` from
    ``list_issues_by_label``.
    """

    @pytest.mark.asyncio
    async def test_authentication_error_propagates_from_list_issues(
        self, tmp_path: Path
    ) -> None:
        """When ``list_issues_by_label`` raises ``AuthenticationError``,
        ``_do_work`` must let it propagate rather than incrementing the
        errors counter and continuing.

        Currently FAILS (RED) because the broad ``except Exception`` at
        line 63 catches ``AuthenticationError`` and continues looping.
        """
        loop, prs = _make_stale_issue_gc_loop(tmp_path)
        prs.list_issues_by_label.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_transient_error_still_caught_on_list_issues(
        self, tmp_path: Path
    ) -> None:
        """A non-auth ``Exception`` (e.g. network timeout) should still be
        caught and produce an errors-count in the result.

        This is GREEN on the current code and should remain GREEN after fix.
        """
        loop, prs = _make_stale_issue_gc_loop(tmp_path)
        prs.list_issues_by_label.side_effect = RuntimeError("network timeout")

        result = await loop._do_work()

        assert result is not None
        assert result["errors"] >= 1
