"""Tests for the ReportIssueLoop background worker."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import PendingReport, TrackedReport
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
    pr_manager.upload_screenshot = AsyncMock(
        return_value="https://gist.example.com/screenshot.png"
    )
    pr_manager.upload_screenshot_gist = AsyncMock(
        return_value="https://gist.example.com/screenshot.png"
    )
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
    return loop, deps.stop_event, state, pr_manager


class TestReportIssueLoopStartup:
    """Tests for ReportIssueLoop startup behaviour."""

    def test_run_on_startup_disabled_in_favour_of_drain(self, tmp_path: Path) -> None:
        """run_on_startup is False because run() drains the queue itself."""
        loop, _stop, _state, _pr = _make_loop(tmp_path)
        assert loop._run_on_startup is False


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
        # Queue should be empty after successful processing
        assert state.peek_report() is None

    @pytest.mark.asyncio
    async def test_screenshot_saved_before_agent(self, tmp_path: Path) -> None:
        """When a screenshot is present, it is saved and referenced for the agent."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(
            description="UI glitch",
            screenshot_base64="iVBORw0KGgo=",
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/101"
            await loop._do_work()

        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert ".png" in prompt
        assert "![Screenshot](" in prompt

    @pytest.mark.asyncio
    async def test_empty_screenshot_skips_upload(self, tmp_path: Path) -> None:
        """When screenshot_base64 is empty, no screenshot is referenced."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(description="No screenshot")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/102"
            await loop._do_work()

        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert "![Screenshot](" not in prompt

    @pytest.mark.asyncio
    async def test_agent_failure_does_not_fall_back_to_direct_issue_create(
        self, tmp_path: Path
    ) -> None:
        """If agent execution fails, no direct fallback issue is created."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(description="Crash test")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.side_effect = RuntimeError("agent died")
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 0
        assert result["error"] is True
        assert result["report_id"] == report.id
        pr_mgr.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_error_when_agent_does_not_create_issue(
        self, tmp_path: Path
    ) -> None:
        """When the agent does not create an issue, report stays in queue."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
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
        pr_mgr.create_issue.assert_not_awaited()
        # Report should still be in the queue with incremented attempts
        pending = state.get_pending_reports()
        assert len(pending) == 1
        assert pending[0].attempts == 1

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        """In dry-run mode, _do_work returns early without processing."""
        loop, _stop, state, _pr = _make_loop(tmp_path, dry_run=True)
        report = PendingReport(description="Dry run test")
        state.enqueue_report(report)

        result = await loop._do_work()
        assert result is None
        # Report should still be in the queue
        assert state.peek_report() is not None

    @pytest.mark.asyncio
    async def test_prompt_includes_description(self, tmp_path: Path) -> None:
        """The agent prompt includes the report description."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(description="Login page 500 error")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/103"
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
            mock_stream.return_value = "https://github.com/acme/repo/issues/104"
            await loop._do_work()

        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert prompt.startswith("/hf.issue Bug in the dashboard")
        assert "IMPORTANT: Use the label" in prompt

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
            mock_stream.return_value = "https://github.com/acme/repo/issues/105"
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
            mock_stream.return_value = "https://github.com/acme/repo/issues/110"
            await loop._do_work()

        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert "screenshot" in prompt.lower()
        assert ".png" in prompt

    @pytest.mark.asyncio
    async def test_data_uri_screenshot_saved_as_temp_file(self, tmp_path: Path) -> None:
        """A data URI screenshot is normalized and saved as a temp PNG."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        raw_png = base64.b64encode(b"\x89PNG\r\n").decode()
        report = PendingReport(
            description="Data URI screenshot",
            screenshot_base64=f"data:image/png;base64,{raw_png}",
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/88"
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 1
        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert ".png" in prompt

    @pytest.mark.asyncio
    async def test_base64_with_whitespace_decoded_successfully(
        self, tmp_path: Path
    ) -> None:
        """Base64 with embedded newlines/spaces is stripped and decoded."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        raw_png = base64.b64encode(b"\x89PNG\r\n").decode()
        # Insert newlines and spaces to simulate transport corruption
        corrupted = "\n".join(raw_png[i : i + 4] for i in range(0, len(raw_png), 4))
        report = PendingReport(
            description="Whitespace in base64",
            screenshot_base64=f"data:image/png;base64,{corrupted}",
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/99"
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 1
        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert ".png" in prompt

    @pytest.mark.asyncio
    async def test_invalid_screenshot_payload_continues_without_attachment(
        self, tmp_path: Path
    ) -> None:
        """Invalid screenshot payloads do not crash processing."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(
            description="Broken screenshot payload",
            screenshot_base64="data:image/png;base64,not-valid-base64",
        )
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/89"
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 1
        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert ".png" not in prompt
        pr_mgr.upload_screenshot_gist.assert_not_awaited()

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
            mock_stream.return_value = "https://github.com/acme/repo/issues/106"
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
            mock_stream.return_value = "https://github.com/acme/repo/issues/107"
            await loop._do_work()

        # Scan is disabled — screenshot should still be referenced in prompt
        prompt = mock_stream.call_args.kwargs.get("prompt", "")
        assert ".png" in prompt


class TestReportRetryAndEscalation:
    """Tests for report retry counting and HITL escalation."""

    @pytest.mark.asyncio
    async def test_failed_report_stays_in_queue(self, tmp_path: Path) -> None:
        """A failed report remains in the queue for retry."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(description="Retry me")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url"
            await loop._do_work()

        pending = state.get_pending_reports()
        assert len(pending) == 1
        assert pending[0].id == report.id
        assert pending[0].attempts == 1

    @pytest.mark.asyncio
    async def test_attempt_counter_increments(self, tmp_path: Path) -> None:
        """Each failure increments the attempt counter."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(description="Keep trying")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url"
            await loop._do_work()
            await loop._do_work()
            await loop._do_work()

        pending = state.get_pending_reports()
        assert len(pending) == 1
        assert pending[0].attempts == 3

    @pytest.mark.asyncio
    async def test_escalates_to_hitl_after_max_attempts(self, tmp_path: Path) -> None:
        """After 5 failures, report is removed and escalated to HITL."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(
            description="Persistent failure",
            environment={"browser": "Chrome"},
        )
        state.enqueue_report(report)
        # Pre-set to 4 attempts so next failure is the 5th
        for _ in range(4):
            state.fail_report(report.id)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url"
            result = await loop._do_work()

        assert result is not None
        assert result["escalated"] is True
        # Report should be removed from queue
        assert state.peek_report() is None
        # HITL issue should have been created with raw content
        hitl_call = pr_mgr.create_issue.call_args_list[-1]
        title = hitl_call[0][0]
        body = hitl_call[0][1]
        assert "[Bug Report]" in title
        assert "Persistent failure" in body
        assert "Chrome" in body

    @pytest.mark.asyncio
    async def test_success_after_retries_removes_from_queue(
        self, tmp_path: Path
    ) -> None:
        """A report that succeeds after previous failures is removed from queue."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(description="Eventually works")
        state.enqueue_report(report)
        # Pre-set 2 failed attempts
        state.fail_report(report.id)
        state.fail_report(report.id)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/99"
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 1
        assert state.peek_report() is None

    @pytest.mark.asyncio
    async def test_escalated_report_includes_screenshot_indicator(
        self, tmp_path: Path
    ) -> None:
        """Escalated HITL issue mentions the screenshot when present."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(
            description="Screenshot bug",
            screenshot_base64="abc123" * 100,
        )
        state.enqueue_report(report)
        for _ in range(4):
            state.fail_report(report.id)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url"
            await loop._do_work()

        hitl_call = pr_mgr.create_issue.call_args_list[-1]
        body = hitl_call[0][1]
        assert "screenshot" in body.lower()
        assert "600 chars" in body


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
            mock_stream.return_value = "https://github.com/acme/repo/issues/108"
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
            mock_stream.return_value = "https://github.com/acme/repo/issues/109"
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
            return "https://github.com/acme/repo/issues/111"

        with patch(
            "report_issue_loop.stream_claude_process",
            side_effect=capture_prompt,
        ):
            await loop._do_work()

        assert saved_path.endswith(".png"), f"Expected .png path, got: {saved_path!r}"
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
            mock_stream.return_value = "https://github.com/acme/repo/issues/112"
            await loop._do_work()

        call_kwargs = mock_build.call_args
        assert (
            call_kwargs.kwargs.get("max_turns", call_kwargs[1].get("max_turns", 0))
            >= 10
        )

    @pytest.mark.asyncio
    async def test_agent_failure_does_not_create_raw_fallback_issue(
        self, tmp_path: Path
    ) -> None:
        """When the agent fails, no raw fallback issue is created."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = PendingReport(description="Login is broken after update")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.side_effect = RuntimeError("agent died")
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 0
        assert result["error"] is True
        pr_mgr.upload_screenshot_gist.assert_not_awaited()
        # Only escalation path should create issue after max retries.
        pr_mgr.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# _save_screenshot resource management tests
# ---------------------------------------------------------------------------


class TestSaveScreenshotResourceManagement:
    """Tests for _save_screenshot FD and temp file handling."""

    def test_writes_directly_via_fdopen(self) -> None:
        """_save_screenshot uses os.fdopen to write directly to the mkstemp FD."""
        raw = b"\x89PNG\r\ntest-data"
        b64 = base64.b64encode(raw).decode()
        result = ReportIssueLoop._save_screenshot(b64)
        try:
            assert result.exists()
            assert result.read_bytes() == raw
            assert result.suffix == ".png"
        finally:
            result.unlink(missing_ok=True)

    def test_data_uri_prefix_stripped(self) -> None:
        """data: URI prefix is stripped before decoding."""
        raw = b"\x89PNG\r\ndata-uri-test"
        b64 = base64.b64encode(raw).decode()
        result = ReportIssueLoop._save_screenshot(f"data:image/png;base64,{b64}")
        try:
            assert result.read_bytes() == raw
        finally:
            result.unlink(missing_ok=True)

    def test_temp_file_cleaned_up_on_write_failure(self) -> None:
        """If writing fails after mkstemp, the temp file is removed."""
        raw = b"\x89PNG\r\n"
        b64 = base64.b64encode(raw).decode()

        captured_path: list[str] = []
        original_mkstemp = tempfile.mkstemp

        def capturing_mkstemp(**kwargs: object) -> tuple[int, str]:
            fd, path = original_mkstemp(**kwargs)
            captured_path.append(path)
            return fd, path

        with (
            patch("report_issue_loop.tempfile.mkstemp", side_effect=capturing_mkstemp),
            patch("report_issue_loop.os.fdopen") as mock_fdopen,
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(side_effect=OSError("disk full"))
            mock_fdopen.return_value = mock_ctx

            with pytest.raises(OSError, match="disk full"):
                ReportIssueLoop._save_screenshot(b64)

        # The temp file must have been unlinked on failure
        assert captured_path, "mkstemp was not called"
        assert not Path(captured_path[0]).exists(), (
            "temp file was not cleaned up on failure"
        )

    def test_no_fd_leak_on_successful_write(self) -> None:
        """After a successful write, no file descriptors are leaked."""
        raw = b"\x89PNG\r\nno-leak-test"
        b64 = base64.b64encode(raw).decode()

        # Track open FD count before and after
        pid = os.getpid()
        try:
            fd_before = len(os.listdir(f"/proc/{pid}/fd"))
        except OSError:
            pytest.skip("/proc not available")

        result = ReportIssueLoop._save_screenshot(b64)
        result.unlink(missing_ok=True)

        fd_after = len(os.listdir(f"/proc/{pid}/fd"))
        assert fd_after <= fd_before, "FD leaked after _save_screenshot"


# ---------------------------------------------------------------------------
# Tracked report status transition tests
# ---------------------------------------------------------------------------


def _enqueue_with_tracking(
    state: StateTracker, description: str = "Test bug"
) -> PendingReport:
    """Enqueue a PendingReport and create a matching TrackedReport."""
    report = PendingReport(description=description)
    state.enqueue_report(report)
    tracked = TrackedReport(
        id=report.id,
        reporter_id="test-user",
        description=description,
        status="queued",
    )
    state.add_tracked_report(tracked)
    return report


class TestTrackedReportStatusTransitions:
    """Tests that _do_work updates TrackedReport status at each lifecycle stage."""

    @pytest.mark.asyncio
    async def test_status_transitions_to_in_progress_on_start(
        self, tmp_path: Path
    ) -> None:
        """When processing begins, tracked report status becomes in-progress."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = _enqueue_with_tracking(state)

        async def check_status_during_processing(**kwargs: Any) -> str:
            # During agent execution the tracked report should be in-progress
            tracked = state.get_tracked_report(report.id)
            assert tracked is not None
            assert tracked.status == "in-progress"
            return "https://github.com/acme/repo/issues/200"

        with patch(
            "report_issue_loop.stream_claude_process",
            side_effect=check_status_during_processing,
        ):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_status_transitions_to_fixed_on_success(self, tmp_path: Path) -> None:
        """On successful issue creation, tracked report status becomes fixed."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = _enqueue_with_tracking(state)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/201"
            await loop._do_work()

        tracked = state.get_tracked_report(report.id)
        assert tracked is not None
        assert tracked.status == "fixed"

    @pytest.mark.asyncio
    async def test_fixed_report_has_linked_issue_url(self, tmp_path: Path) -> None:
        """On success, the tracked report's linked_issue_url is populated."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = _enqueue_with_tracking(state)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/202"
            await loop._do_work()

        tracked = state.get_tracked_report(report.id)
        assert tracked is not None
        assert "issues/202" in tracked.linked_issue_url

    @pytest.mark.asyncio
    async def test_status_transitions_to_closed_on_escalation(
        self, tmp_path: Path
    ) -> None:
        """After max retries, tracked report status becomes closed."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = _enqueue_with_tracking(state)
        # Pre-set to 4 attempts so next failure triggers escalation
        for _ in range(4):
            state.fail_report(report.id)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url"
            await loop._do_work()

        tracked = state.get_tracked_report(report.id)
        assert tracked is not None
        assert tracked.status == "closed"

    @pytest.mark.asyncio
    async def test_status_reverts_to_queued_on_retry_failure(
        self, tmp_path: Path
    ) -> None:
        """On a non-final failure, tracked report status reverts to queued."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = _enqueue_with_tracking(state)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url"
            await loop._do_work()

        tracked = state.get_tracked_report(report.id)
        assert tracked is not None
        assert tracked.status == "queued"

    @pytest.mark.asyncio
    async def test_history_entries_added_for_transitions(self, tmp_path: Path) -> None:
        """Each status transition appends a history entry."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = _enqueue_with_tracking(state)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/203"
            await loop._do_work()

        tracked = state.get_tracked_report(report.id)
        assert tracked is not None
        actions = [h.action for h in tracked.history]
        assert "processing" in actions
        assert "fixed" in actions

    @pytest.mark.asyncio
    async def test_history_entries_added_for_retry(self, tmp_path: Path) -> None:
        """On a non-final failure, history records both in-progress and retry actions."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = _enqueue_with_tracking(state)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url"
            await loop._do_work()

        tracked = state.get_tracked_report(report.id)
        assert tracked is not None
        actions = [h.action for h in tracked.history]
        assert "processing" in actions
        assert "retry" in actions

    @pytest.mark.asyncio
    async def test_history_entries_added_for_escalation(self, tmp_path: Path) -> None:
        """On final failure, history records both in-progress and escalated actions."""
        loop, _stop, state, pr_mgr = _make_loop(tmp_path)
        report = _enqueue_with_tracking(state)
        for _ in range(4):
            state.fail_report(report.id)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url"
            await loop._do_work()

        tracked = state.get_tracked_report(report.id)
        assert tracked is not None
        actions = [h.action for h in tracked.history]
        assert "processing" in actions
        assert "escalated" in actions

    @pytest.mark.asyncio
    async def test_no_tracked_report_does_not_crash(self, tmp_path: Path) -> None:
        """When no TrackedReport exists, status updates are silently skipped."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        # Only enqueue PendingReport, no TrackedReport
        report = PendingReport(description="No tracker")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "https://github.com/acme/repo/issues/204"
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 1

    @pytest.mark.asyncio
    async def test_no_tracked_report_does_not_crash_on_retry(
        self, tmp_path: Path
    ) -> None:
        """When no TrackedReport exists and agent fails, retry path silently skips updates."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        # Only enqueue PendingReport, no TrackedReport
        report = PendingReport(description="No tracker")
        state.enqueue_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "no url"
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 0
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_status_reverts_to_queued_when_agent_raises_exception(
        self, tmp_path: Path
    ) -> None:
        """When stream_claude_process raises, status transitions in-progress -> queued."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = _enqueue_with_tracking(state)

        with patch(
            "report_issue_loop.stream_claude_process",
            side_effect=RuntimeError("agent crashed"),
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 0
        assert result["error"] is True

        tracked = state.get_tracked_report(report.id)
        assert tracked is not None
        assert tracked.status == "queued"
        actions = [h.action for h in tracked.history]
        assert "processing" in actions
        assert "retry" in actions


# ---------------------------------------------------------------------------
# Startup drain tests
# ---------------------------------------------------------------------------


class TestStartupDrain:
    """Tests for the run() override that drains all queued reports on startup."""

    @pytest.mark.asyncio
    async def test_drains_multiple_reports_on_startup(self, tmp_path: Path) -> None:
        """All queued reports are processed before entering the polling loop."""
        loop, stop_event, state, _pr = _make_loop(tmp_path)

        # Enqueue 3 reports
        for i in range(3):
            state.enqueue_report(PendingReport(description=f"Bug {i}"))

        processed: list[str] = []

        async def fake_stream(**kwargs: Any) -> str:
            report = state.peek_report()
            if report:
                processed.append(report.id)
            return f"https://github.com/acme/repo/issues/{100 + len(processed)}"

        with patch(
            "report_issue_loop.stream_claude_process",
            side_effect=fake_stream,
        ):
            # We need super().run() to exit — set stop after drain
            async def patched_super_run(self_inner: Any) -> None:
                stop_event.set()

            with patch.object(loop.__class__.__bases__[0], "run", patched_super_run):
                await loop.run()

        assert len(processed) == 3
        assert state.peek_report() is None

    @pytest.mark.asyncio
    async def test_drain_respects_stop_event(self, tmp_path: Path) -> None:
        """Startup drain stops early when the stop event is set."""
        loop, stop_event, state, _pr = _make_loop(tmp_path)

        for i in range(5):
            state.enqueue_report(PendingReport(description=f"Bug {i}"))

        call_count = 0

        async def fake_stream(**kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                stop_event.set()
            return f"https://github.com/acme/repo/issues/{200 + call_count}"

        with (
            patch(
                "report_issue_loop.stream_claude_process",
                side_effect=fake_stream,
            ),
            patch.object(loop.__class__.__bases__[0], "run", AsyncMock()),
        ):
            await loop.run()

        # Should have stopped after 2 reports due to stop_event
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_drain_empty_queue_goes_straight_to_loop(
        self, tmp_path: Path
    ) -> None:
        """When queue is empty, drain is skipped and super().run() is called."""
        loop, stop_event, state, _pr = _make_loop(tmp_path)

        with patch.object(
            loop.__class__.__bases__[0], "run", AsyncMock()
        ) as mock_super_run:
            await loop.run()

        mock_super_run.assert_awaited_once()


# ---------------------------------------------------------------------------
# Stale report sweep tests
# ---------------------------------------------------------------------------


class TestStaleReportSweep:
    """Tests for _sweep_stale_reports auto-closing old queued reports."""

    def test_stale_report_auto_closed(self, tmp_path: Path) -> None:
        """Reports older than the threshold are removed and marked closed."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        # Create a report with a created_at 7 hours ago (threshold is 6h)
        old_time = (datetime.now(UTC) - timedelta(hours=7)).isoformat()
        report = PendingReport(description="Old bug")
        report.created_at = old_time
        state.enqueue_report(report)

        tracked = TrackedReport(
            id=report.id,
            reporter_id="test-user",
            description="Old bug",
            status="queued",
        )
        state.add_tracked_report(tracked)

        closed = loop._sweep_stale_reports()

        assert closed == 1
        assert state.peek_report() is None
        updated = state.get_tracked_report(report.id)
        assert updated is not None
        assert updated.status == "closed"
        actions = [h.action for h in updated.history]
        assert "stale" in actions

    def test_fresh_report_not_swept(self, tmp_path: Path) -> None:
        """Reports younger than the threshold are kept."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(description="Fresh bug")
        state.enqueue_report(report)

        closed = loop._sweep_stale_reports()

        assert closed == 0
        assert state.peek_report() is not None

    def test_mixed_stale_and_fresh(self, tmp_path: Path) -> None:
        """Only stale reports are swept; fresh ones remain."""
        loop, _stop, state, _pr = _make_loop(tmp_path)

        old_time = (datetime.now(UTC) - timedelta(hours=10)).isoformat()
        stale = PendingReport(description="Stale bug")
        stale.created_at = old_time
        state.enqueue_report(stale)

        fresh = PendingReport(description="Fresh bug")
        state.enqueue_report(fresh)

        closed = loop._sweep_stale_reports()

        assert closed == 1
        remaining = state.get_pending_reports()
        assert len(remaining) == 1
        assert remaining[0].id == fresh.id

    def test_invalid_created_at_skipped(self, tmp_path: Path) -> None:
        """Reports with unparseable created_at are not swept."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        report = PendingReport(description="Bad timestamp")
        report.created_at = "not-a-date"
        state.enqueue_report(report)

        closed = loop._sweep_stale_reports()

        assert closed == 0
        assert state.peek_report() is not None

    @pytest.mark.asyncio
    async def test_sweep_runs_in_do_work(self, tmp_path: Path) -> None:
        """_do_work calls _sweep_stale_reports before processing."""
        loop, _stop, state, _pr = _make_loop(tmp_path)

        old_time = (datetime.now(UTC) - timedelta(hours=10)).isoformat()
        stale = PendingReport(description="Stale")
        stale.created_at = old_time
        state.enqueue_report(stale)

        # No more reports after sweep, so _do_work should return None
        result = await loop._do_work()
        assert result is None
        assert state.peek_report() is None

    def test_sweep_with_zero_reports(self, tmp_path: Path) -> None:
        """Sweep on empty queue returns 0 and doesn't crash."""
        loop, _stop, state, _pr = _make_loop(tmp_path)
        closed = loop._sweep_stale_reports()
        assert closed == 0
