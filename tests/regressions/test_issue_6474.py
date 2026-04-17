"""Regression test for issue #6474.

Bug: ``diagnostic_loop._do_work()`` and ``report_issue_loop._do_work()``
catch ``Exception`` broadly on GitHub API calls.  Because
``AuthenticationError`` is a subclass of ``RuntimeError`` (which is a
subclass of ``Exception``), it is silently swallowed and the loop
returns a no-op result instead of propagating the error to
``BaseBackgroundLoop._execute_cycle()``, which is designed to re-raise
``AuthenticationError`` so the orchestrator can set ``_auth_failed=True``
and halt the pipeline.

Expected behaviour after fix:
  - ``AuthenticationError`` raised inside ``_do_work()`` propagates out
    of ``_do_work()`` (not caught by the broad ``except Exception``).
  - ``_execute_cycle()`` then re-raises it (line 141 of
    ``base_background_loop.py``), which the orchestrator handles.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from diagnostic_loop import DiagnosticLoop
from models import TrackedReport
from report_issue_loop import ReportIssueLoop
from state import StateTracker
from subprocess_util import AuthenticationError
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers — DiagnosticLoop
# ---------------------------------------------------------------------------


def _make_diagnostic_loop(
    tmp_path: Path,
) -> tuple[DiagnosticLoop, MagicMock]:
    """Build a DiagnosticLoop with its PRPort mock."""
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    runner = MagicMock()
    runner.diagnose = AsyncMock()

    prs = MagicMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    prs.post_comment = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=None)
    state.get_diagnostic_attempts = MagicMock(return_value=[])

    loop = DiagnosticLoop(
        config=deps.config,
        runner=runner,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, prs


# ---------------------------------------------------------------------------
# Helpers — ReportIssueLoop
# ---------------------------------------------------------------------------


def _make_report_loop(
    tmp_path: Path,
) -> tuple[ReportIssueLoop, MagicMock]:
    """Build a ReportIssueLoop with its PRManager mock."""
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    state = StateTracker(tmp_path / "state.json")
    pr_manager = MagicMock()
    pr_manager.get_issue_state = AsyncMock(return_value="OPEN")
    pr_manager.create_issue = AsyncMock(return_value=123)
    pr_manager._repo = "owner/repo"

    runner = MagicMock()

    loop = ReportIssueLoop(
        config=deps.config,
        state=state,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
        runner=runner,
    )
    return loop, pr_manager


# ---------------------------------------------------------------------------
# Tests — DiagnosticLoop
# ---------------------------------------------------------------------------


class TestDiagnosticLoopAuthenticationError:
    """AuthenticationError must propagate out of diagnostic_loop._do_work()."""

    @pytest.mark.asyncio
    async def test_auth_error_on_list_issues_propagates(self, tmp_path: Path) -> None:
        """When list_issues_by_label raises AuthenticationError, _do_work
        must NOT catch it — the error should bubble up so _execute_cycle
        can re-raise it to the orchestrator.

        BUG (current): the broad ``except Exception`` at line 95 catches it
        and returns ``{"processed": 0, ...}`` silently.
        """
        loop, prs = _make_diagnostic_loop(tmp_path)
        prs.list_issues_by_label.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await loop._do_work()


# ---------------------------------------------------------------------------
# Tests — ReportIssueLoop
# ---------------------------------------------------------------------------


class TestReportIssueLoopAuthenticationError:
    """AuthenticationError must propagate out of report_issue_loop methods."""

    @pytest.mark.asyncio
    async def test_auth_error_on_get_issue_state_propagates(
        self, tmp_path: Path
    ) -> None:
        """When get_issue_state raises AuthenticationError during
        _sync_filed_reports, it must NOT be caught — the error should
        bubble up so _execute_cycle can re-raise it.

        BUG (current): the broad ``except Exception`` at line 160 catches
        it and silently continues to the next report.
        """
        loop, pr_manager = _make_report_loop(tmp_path)

        # Seed a filed report so _sync_filed_reports actually calls
        # get_issue_state.
        loop._state.add_tracked_report(
            TrackedReport(
                id="rpt-1",
                reporter_id="test",
                description="Test report",
                status="filed",
                linked_issue_url="https://github.com/owner/repo/issues/99",
            )
        )

        pr_manager.get_issue_state.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await loop._sync_filed_reports()
