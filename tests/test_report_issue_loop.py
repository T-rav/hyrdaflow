"""Tests for the ReportIssueLoop background worker."""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import PendingReport
from report_issue_loop import ReportIssueLoop
from state import StateTracker
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    dry_run: bool = False,
) -> tuple[ReportIssueLoop, asyncio.Event, StateTracker, MagicMock]:
    """Build a ReportIssueLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=enabled)

    if dry_run:
        object.__setattr__(deps.config, "dry_run", True)

    state = StateTracker(tmp_path / "state.json")
    pr_manager = MagicMock()
    pr_manager.upload_screenshot_gist = AsyncMock(
        return_value="https://gist.example.com/screenshot.png"
    )
    pr_manager.create_issue = AsyncMock(return_value=123)
    runner = MagicMock()

    loop = ReportIssueLoop(
        config=deps.config,
        state=state,
        pr_manager=pr_manager,
        event_bus=deps.bus,
        stop_event=deps.stop_event,
        status_cb=deps.status_cb,
        enabled_cb=deps.enabled_cb,
        sleep_fn=deps.sleep_fn,
        runner=runner,
    )
    return loop, deps.stop_event, state, pr_manager


class TestReportIssueLoopDoWork:
    """Tests for ReportIssueLoop._do_work."""

    @pytest.mark.asyncio
    async def test_no_pending_reports_returns_none(self, tmp_path: Path) -> None:
        """When no reports are queued, _do_work returns None (no-op)."""
        loop, _stop, _state, _pr = _make_loop(tmp_path)
        result = await loop._do_work()
        assert result is None

    @pytest.mark.asyncio
    async def test_pending_report_dequeues_and_invokes_agent(
        self, tmp_path: Path
    ) -> None:
        """A queued report is dequeued and the agent CLI is invoked."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(description="Button is broken")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/77"
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 1
        assert result["report_id"] == report.id
        assert result["issue_number"] == 77
        mock_stream.assert_awaited_once()
        _pr.create_issue.assert_not_awaited()
        assert mock_stream.call_args[1]["gh_token"] == loop._config.gh_token
        # Queue should be empty after processing
        assert state.dequeue_report() is None

    @pytest.mark.asyncio
    async def test_screenshot_uploaded_before_agent(self, tmp_path: Path) -> None:
        """When a screenshot is present, it is uploaded before invoking the agent."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(
            description="UI glitch",
            screenshot_base64="iVBORw0KGgo=",
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            await loop._do_work()

        pr_mgr.upload_screenshot_gist.assert_awaited_once_with("iVBORw0KGgo=")

    @pytest.mark.asyncio
    async def test_empty_screenshot_skips_gist_upload(self, tmp_path: Path) -> None:
        """When screenshot_base64 is empty, gist upload is skipped."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(description="No screenshot")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            await loop._do_work()

        pr_mgr.upload_screenshot_gist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_agent_failure_falls_back_to_direct_issue_create(
        self, tmp_path: Path
    ) -> None:
        """If agent execution fails, fallback direct issue creation is attempted."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(description="Crash test")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.side_effect = RuntimeError("agent died")
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 1
        assert result["report_id"] == report.id
        assert result["issue_number"] == 123
        pr_mgr.create_issue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_error_when_agent_and_fallback_both_fail(
        self, tmp_path: Path
    ) -> None:
        """When neither agent nor fallback creates an issue, report stays failed."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        pr_mgr.create_issue.return_value = 0
        report = PendingReport(description="Still broken")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url in output"
            result = await loop._do_work()

        assert result is not None
        assert result["error"] is True
        assert result["processed"] == 0
        assert result["report_id"] == report.id
        pr_mgr.create_issue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        """In dry-run mode, _do_work returns early without processing."""
        loop, _stop, state, _pr = _make_loop(tmp_path, dry_run=True)
        report = PendingReport(description="Dry run test")
        state.enqueue_report(report)

        result = await loop._do_work()
        assert result is None
        # Report should still be in the queue
        assert state.dequeue_report() is not None

    @pytest.mark.asyncio
    async def test_prompt_includes_description(self, tmp_path: Path) -> None:
        """The agent prompt includes the report description."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(description="Login page 500 error")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            await loop._do_work()

        call_kwargs = mock_stream.call_args
        prompt = call_kwargs.kwargs.get("prompt", "")
        assert "Login page 500 error" in prompt
        assert prompt.startswith("/hf.issue ")

    @pytest.mark.asyncio
    async def test_prompt_uses_hf_issue_skill(self, tmp_path: Path) -> None:
        """The prompt invokes /hf.issue so the agent uses the full skill."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(description="Bug in the dashboard")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            await loop._do_work()

        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert prompt == "/hf.issue Bug in the dashboard"

    @pytest.mark.asyncio
    async def test_screenshot_with_secrets_is_stripped(self, tmp_path: Path) -> None:
        """When the screenshot contains a secret pattern, it is not uploaded."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        # Include a GitHub PAT pattern in the screenshot payload
        report = PendingReport(
            description="UI glitch",
            screenshot_base64="ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl",
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            await loop._do_work()

        # Screenshot should NOT have been uploaded
        pr_mgr.upload_screenshot_gist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_screenshot_saved_as_temp_file(self, tmp_path: Path) -> None:
        """A clean screenshot is saved as a temp PNG and referenced in the prompt."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        # Valid base64 for a tiny payload
        b64 = base64.b64encode(b"\x89PNG\r\n").decode()
        report = PendingReport(
            description="Normal bug",
            screenshot_base64=b64,
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            await loop._do_work()

        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert "screenshot" in prompt.lower()
        assert ".png" in prompt

    @pytest.mark.asyncio
    async def test_screenshot_with_secrets_still_creates_issue(
        self, tmp_path: Path
    ) -> None:
        """Even when the screenshot is stripped, the issue is still created."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(
            description="Secrets in screenshot",
            screenshot_base64="ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl",
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 1
        # The prompt should not reference a screenshot file
        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert ".png" not in prompt

    @pytest.mark.asyncio
    async def test_scanner_disabled_saves_screenshot_with_secrets(
        self, tmp_path: Path
    ) -> None:
        """When screenshot_redaction_enabled=False, scan is skipped and screenshot is saved."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        object.__setattr__(loop._config, "screenshot_redaction_enabled", False)
        # Use valid base64 so _save_screenshot can decode it
        b64 = base64.b64encode(b"fake-png-data").decode()
        report = PendingReport(
            description="UI glitch",
            screenshot_base64=b64,
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            await loop._do_work()

        # Scan is disabled — screenshot should still be referenced in prompt
        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert ".png" in prompt


class TestReportIssueLoopInterval:
    """Tests for interval configuration."""

    def test_default_interval_from_config(self, tmp_path: Path) -> None:
        """The default interval comes from config.report_issue_interval."""
        loop, _stop, _state, _pr = _make_loop(tmp_path)
        assert loop._get_default_interval() == 30


# ---------------------------------------------------------------------------
# Enrichment prompt structure tests
# ---------------------------------------------------------------------------


class TestHfIssueSkillPrompt:
    """Tests verifying the prompt uses /hf.issue so the agent gets the full
    skill instructions for codebase research and structured issue creation."""

    @pytest.mark.asyncio
    async def test_prompt_invokes_hf_issue_skill(self, tmp_path: Path) -> None:
        """The prompt starts with /hf.issue to trigger the skill."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(description="rename the processes subtab toggles please")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            await loop._do_work()

        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert prompt.startswith("/hf.issue ")
        assert "rename the processes subtab toggles please" in prompt

    @pytest.mark.asyncio
    async def test_screenshot_path_in_prompt(self, tmp_path: Path) -> None:
        """When a screenshot is available, the prompt tells the agent where to find it."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        b64 = base64.b64encode(b"\x89PNG\r\n").decode()
        report = PendingReport(
            description="UI looks wrong",
            screenshot_base64=b64,
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "done"
            await loop._do_work()

        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert ".png" in prompt
        assert "Read tool" in prompt

    @pytest.mark.asyncio
    async def test_screenshot_temp_file_cleaned_up(self, tmp_path: Path) -> None:
        """The temp screenshot file is cleaned up after the agent finishes."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        b64 = base64.b64encode(b"\x89PNG\r\n").decode()
        report = PendingReport(description="bug", screenshot_base64=b64)
        state.enqueue_report(report)

        saved_path: str = ""

        async def capture_prompt(**kwargs: Any) -> str:
            nonlocal saved_path
            prompt = kwargs.get("prompt", "")
            # Extract the .png path from the prompt
            for word in prompt.split():
                if word.endswith(".png"):
                    saved_path = word
            return "done"

        with patch(
            "report_issue_loop.stream_claude_process",
            side_effect=capture_prompt,
        ):
            await loop._do_work()

        assert saved_path
        assert not Path(saved_path).exists(), "Temp screenshot should be deleted"

    @pytest.mark.asyncio
    async def test_max_turns_increased_for_research(self, tmp_path: Path) -> None:
        """max_turns is >= 10 to allow the agent to research the codebase."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(description="something broken")
        state.enqueue_report(report)

        with (
            patch(
                "report_issue_loop.stream_claude_process", new_callable=AsyncMock
            ) as mock_stream,
            patch(
                "report_issue_loop.build_agent_command",
                wraps=__import__("agent_cli").build_agent_command,
            ) as mock_build,
        ):
            mock_stream.return_value = "done"
            await loop._do_work()

        call_kwargs = mock_build.call_args
        assert (
            call_kwargs.kwargs.get("max_turns", call_kwargs[1].get("max_turns", 0))
            >= 10
        )

    @pytest.mark.asyncio
    async def test_fallback_uses_basic_description(self, tmp_path: Path) -> None:
        """When the agent fails, the fallback issue body is based on the raw description."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(description="Login is broken after update")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.side_effect = RuntimeError("agent died")
            await loop._do_work()

        call_args = pr_mgr.create_issue.call_args
        fallback_title = call_args[0][0]
        fallback_body = call_args[0][1]
        assert "[Bug Report]" in fallback_title
        assert "Login is broken after update" in fallback_body

    @pytest.mark.asyncio
    async def test_fallback_uploads_screenshot_gist(self, tmp_path: Path) -> None:
        """When the agent fails and a screenshot exists, fallback uploads a gist."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        b64 = base64.b64encode(b"\x89PNG\r\n").decode()
        report = PendingReport(description="UI bug", screenshot_base64=b64)
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.side_effect = RuntimeError("agent died")
            await loop._do_work()

        # Fallback should upload the screenshot as a gist
        pr_mgr.upload_screenshot_gist.assert_awaited_once_with(b64)
        call_args = pr_mgr.create_issue.call_args
        fallback_body = call_args[0][1]
        assert "Screenshot" in fallback_body or "screenshot" in fallback_body.lower()
