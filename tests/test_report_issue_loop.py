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
