"""Integration test: report pipeline event flow through a real EventBus."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from models import PendingReport, TrackedReport
from report_issue_loop import ReportIssueLoop
from state import StateTracker
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
) -> tuple[ReportIssueLoop, StateTracker, MagicMock]:
    """Build a ReportIssueLoop wired to a real EventBus (from make_bg_loop_deps).

    Returns (loop, state, pr_manager).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=enabled)

    state = StateTracker(tmp_path / "state.json")
    pr_manager = MagicMock()
    pr_manager.upload_screenshot = AsyncMock(return_value="")
    pr_manager.upload_screenshot_gist = AsyncMock(return_value="")
    pr_manager.create_issue = AsyncMock(return_value=123)
    pr_manager.add_labels = AsyncMock()
    pr_manager._run_gh = AsyncMock(return_value='{"labels":[],"body":""}')
    pr_manager._repo = "owner/repo"
    runner = MagicMock()

    loop = ReportIssueLoop(
        config=deps.config,
        state=state,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
        runner=runner,
    )
    return loop, state, pr_manager


class TestReportEventFlow:
    """End-to-end event flow: enqueue report -> _do_work -> verify bus history."""

    @pytest.mark.asyncio
    async def test_successful_report_emits_in_progress_then_filed(
        self, tmp_path: Path
    ) -> None:
        """A successfully processed report emits REPORT_UPDATE events:
        first with status=in-progress, then status=filed with issue_number.
        """
        loop, state, _pr = _make_loop(tmp_path)

        # Enqueue a pending report *and* a tracked report so state updates work.
        report = PendingReport(description="Login button does not respond")
        state.enqueue_report(report)
        tracked = TrackedReport(
            id=report.id,
            reporter_id="user-1",
            description=report.description,
        )
        state.add_tracked_report(tracked)

        fake_issue_url = "https://github.com/owner/repo/issues/42"

        with patch(
            "report_issue_loop.stream_claude_process",
            new_callable=AsyncMock,
        ) as mock_stream:
            mock_stream.return_value = (
                f"I created the issue here: {fake_issue_url}\nDone."
            )
            result = await loop._do_work()

        # Basic result checks
        assert result is not None
        assert result["processed"] == 1
        assert result["issue_number"] == 42

        # Inspect the real EventBus history
        history = loop._bus.get_history()
        report_events = [e for e in history if e.type == EventType.REPORT_UPDATE]

        # We expect at least 2 REPORT_UPDATE events: in-progress and filed
        assert len(report_events) >= 2, (
            f"Expected at least 2 REPORT_UPDATE events, got {len(report_events)}: "
            f"{[e.data for e in report_events]}"
        )

        # First event: in-progress
        first = report_events[0]
        assert first.data["report_id"] == report.id
        assert first.data["status"] == "in-progress"

        # Second event: filed with issue_number
        second = report_events[1]
        assert second.data["report_id"] == report.id
        assert second.data["status"] == "filed"
        assert second.data["issue_number"] == 42

    @pytest.mark.asyncio
    async def test_no_reports_emits_no_events(self, tmp_path: Path) -> None:
        """When the queue is empty, _do_work returns None and no events are emitted."""
        loop, _state, _pr = _make_loop(tmp_path)

        result = await loop._do_work()
        assert result is None

        history = loop._bus.get_history()
        report_events = [e for e in history if e.type == EventType.REPORT_UPDATE]
        assert len(report_events) == 0

    @pytest.mark.asyncio
    async def test_failed_report_emits_in_progress_only(self, tmp_path: Path) -> None:
        """When the agent fails to extract an issue number, we still get the
        in-progress event but no filed event.
        """
        loop, state, _pr = _make_loop(tmp_path)

        report = PendingReport(description="Crash on page load")
        state.enqueue_report(report)
        tracked = TrackedReport(
            id=report.id,
            reporter_id="user-2",
            description=report.description,
        )
        state.add_tracked_report(tracked)

        with patch(
            "report_issue_loop.stream_claude_process",
            new_callable=AsyncMock,
        ) as mock_stream:
            # Return transcript with no issue URL
            mock_stream.return_value = "I was unable to create the issue."
            result = await loop._do_work()

        # Result indicates failure (processed=0)
        assert result is not None
        assert result["processed"] == 0

        history = loop._bus.get_history()
        report_events = [e for e in history if e.type == EventType.REPORT_UPDATE]

        # Should have the in-progress event
        in_progress_events = [
            e for e in report_events if e.data.get("status") == "in-progress"
        ]
        assert len(in_progress_events) == 1
        assert in_progress_events[0].data["report_id"] == report.id

        # Should NOT have a filed event
        filed_events = [e for e in report_events if e.data.get("status") == "filed"]
        assert len(filed_events) == 0
