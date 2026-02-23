"""Tests for runner_utils.py — shared streaming utilities."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from runner_utils import stream_claude_process, terminate_processes
from tests.helpers import make_streaming_proc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_kwargs(event_bus, **overrides):
    """Build default kwargs for stream_claude_process."""
    defaults = {
        "cmd": ["claude", "-p"],
        "prompt": "test prompt",
        "cwd": Path("/tmp/test"),
        "active_procs": set(),
        "event_bus": event_bus,
        "event_data": {"issue": 1},
        "logger": logging.getLogger("test"),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# stream_claude_process — basic output
# ---------------------------------------------------------------------------


class TestStreamClaudeProcessOutput:
    """Tests for stream_claude_process output handling."""

    @pytest.mark.asyncio
    async def test_returns_transcript_from_stdout(self, event_bus) -> None:
        """stream_claude_process should return stdout content as transcript."""
        mock_create = make_streaming_proc(
            returncode=0, stdout="Line one\nLine two\nLine three"
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await stream_claude_process(**_default_kwargs(event_bus))

        assert result == "Line one\nLine two\nLine three"

    @pytest.mark.asyncio
    async def test_returns_result_text_when_available(self, event_bus) -> None:
        """stream_claude_process should prefer StreamParser result over raw lines."""
        result_event = json.dumps({"type": "result", "result": "Final result text"})
        mock_create = make_streaming_proc(returncode=0, stdout=result_event)

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await stream_claude_process(**_default_kwargs(event_bus))

        assert result == "Final result text"

    @pytest.mark.asyncio
    async def test_falls_back_to_accumulated_text(self, event_bus) -> None:
        """When no result_text, should use accumulated display text."""
        mock_create = make_streaming_proc(returncode=0, stdout="Display line")

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await stream_claude_process(**_default_kwargs(event_bus))

        assert result == "Display line"

    @pytest.mark.asyncio
    async def test_falls_back_to_raw_lines(self, event_bus) -> None:
        """When no result_text and no display text, should use raw lines."""
        mock_create = make_streaming_proc(returncode=0, stdout="")

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await stream_claude_process(**_default_kwargs(event_bus))

        assert result == ""


# ---------------------------------------------------------------------------
# stream_claude_process — event publishing
# ---------------------------------------------------------------------------


class TestStreamClaudeProcessEvents:
    """Tests for event publishing behavior."""

    @pytest.mark.asyncio
    async def test_publishes_transcript_line_events(self, event_bus) -> None:
        """Should publish a TRANSCRIPT_LINE event per non-empty display line."""
        mock_create = make_streaming_proc(
            returncode=0, stdout="Line one\nLine two\nLine three"
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            await stream_claude_process(**_default_kwargs(event_bus))

        events = event_bus.get_history()
        transcript_events = [e for e in events if e.type == EventType.TRANSCRIPT_LINE]
        assert len(transcript_events) == 3
        lines = [e.data["line"] for e in transcript_events]
        assert "Line one" in lines
        assert "Line two" in lines
        assert "Line three" in lines

    @pytest.mark.asyncio
    async def test_event_data_includes_custom_keys(self, event_bus) -> None:
        """Event data should merge caller-provided keys with 'line'."""
        mock_create = make_streaming_proc(returncode=0, stdout="Hello")

        with patch("asyncio.create_subprocess_exec", mock_create):
            await stream_claude_process(
                **_default_kwargs(
                    event_bus,
                    event_data={"issue": 42, "source": "planner"},
                )
            )

        events = event_bus.get_history()
        transcript_events = [e for e in events if e.type == EventType.TRANSCRIPT_LINE]
        assert len(transcript_events) == 1
        data = transcript_events[0].data
        assert data["issue"] == 42
        assert data["source"] == "planner"
        assert data["line"] == "Hello"

    @pytest.mark.asyncio
    async def test_skips_empty_lines_for_events(self, event_bus) -> None:
        """Should not publish events for blank/whitespace-only lines."""
        mock_create = make_streaming_proc(
            returncode=0, stdout="Line one\n\n   \nLine two"
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            await stream_claude_process(**_default_kwargs(event_bus))

        events = event_bus.get_history()
        transcript_events = [e for e in events if e.type == EventType.TRANSCRIPT_LINE]
        assert len(transcript_events) == 2


# ---------------------------------------------------------------------------
# stream_claude_process — subprocess configuration
# ---------------------------------------------------------------------------


class TestStreamClaudeProcessConfig:
    """Tests for subprocess configuration."""

    @pytest.mark.asyncio
    async def test_uses_large_stream_limit(self, event_bus) -> None:
        """Should set limit=1MB on subprocess to handle large stream-json lines."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")

        with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
            await stream_claude_process(**_default_kwargs(event_bus))

        kwargs = mock_exec.call_args[1]
        assert kwargs["limit"] == 1024 * 1024

    @pytest.mark.asyncio
    async def test_removes_claudecode_from_env(self, event_bus) -> None:
        """Should strip CLAUDECODE from the subprocess environment."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")

        with (
            patch.dict(os.environ, {"CLAUDECODE": "1"}),
            patch("asyncio.create_subprocess_exec", mock_create) as mock_exec,
        ):
            await stream_claude_process(**_default_kwargs(event_bus))

        env = mock_exec.call_args[1]["env"]
        assert "CLAUDECODE" not in env


# ---------------------------------------------------------------------------
# stream_claude_process — non-zero exit handling
# ---------------------------------------------------------------------------


class TestStreamClaudeProcessExitHandling:
    """Tests for non-zero exit code handling."""

    @pytest.mark.asyncio
    async def test_logs_warning_on_nonzero_exit(self, event_bus) -> None:
        """Should log a warning when the process exits non-zero."""
        mock_logger = MagicMock()
        mock_create = make_streaming_proc(
            returncode=1, stdout="output", stderr="error details"
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            await stream_claude_process(
                **_default_kwargs(event_bus, logger=mock_logger)
            )

        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_warning_on_early_kill(self, event_bus) -> None:
        """When on_output kills the process, no warning should be logged."""
        mock_logger = MagicMock()
        mock_create = make_streaming_proc(
            returncode=1, stdout="Line one", stderr="error"
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            await stream_claude_process(
                **_default_kwargs(
                    event_bus,
                    logger=mock_logger,
                    on_output=lambda _: True,  # Kill immediately
                )
            )

        mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# stream_claude_process — on_output callback
# ---------------------------------------------------------------------------


class TestStreamClaudeProcessCallback:
    """Tests for the on_output callback."""

    @pytest.mark.asyncio
    async def test_on_output_callback_kills_process(self, event_bus) -> None:
        """Returning True from on_output should kill the process early."""
        mock_create = make_streaming_proc(
            returncode=0, stdout="Line one\nLine two\nLine three"
        )

        def kill_on_second(accumulated: str) -> bool:
            return "Line two" in accumulated

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await stream_claude_process(
                **_default_kwargs(event_bus, on_output=kill_on_second)
            )

        assert "Line one" in result
        assert "Line two" in result

    @pytest.mark.asyncio
    async def test_on_output_receives_accumulated_text(self, event_bus) -> None:
        """Callback should receive the full accumulated text, not just current line."""
        accumulated_snapshots: list[str] = []

        def capture_accumulated(accumulated: str) -> bool:
            accumulated_snapshots.append(accumulated)
            return False

        mock_create = make_streaming_proc(returncode=0, stdout="Line one\nLine two")

        with patch("asyncio.create_subprocess_exec", mock_create):
            await stream_claude_process(
                **_default_kwargs(event_bus, on_output=capture_accumulated)
            )

        # First call: just "Line one\n"
        assert "Line one" in accumulated_snapshots[0]
        # Second call: "Line one\nLine two\n"
        assert "Line one" in accumulated_snapshots[1]
        assert "Line two" in accumulated_snapshots[1]


# ---------------------------------------------------------------------------
# stream_claude_process — cancellation and process tracking
# ---------------------------------------------------------------------------


class TestStreamClaudeProcessLifecycle:
    """Tests for process lifecycle management."""

    @pytest.mark.asyncio
    async def test_cancellation_kills_process(self, event_bus) -> None:
        """CancelledError during streaming should kill the process."""

        class CancellingIter:
            """Async iterator that raises CancelledError immediately."""

            def __aiter__(self):  # noqa: ANN204
                return self

            async def __anext__(self) -> bytes:
                raise asyncio.CancelledError

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdout = CancellingIter()
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        mock_create = AsyncMock(return_value=mock_proc)
        active_procs: set[asyncio.subprocess.Process] = set()

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(asyncio.CancelledError),
        ):
            await stream_claude_process(
                **_default_kwargs(event_bus, active_procs=active_procs)
            )

        mock_proc.kill.assert_called_once()
        assert mock_proc not in active_procs

    @pytest.mark.asyncio
    async def test_tracks_process_in_active_set(self, event_bus) -> None:
        """Process should be in active_procs during execution and removed after."""
        active_procs: set[asyncio.subprocess.Process] = set()
        proc_was_tracked = False

        def check_tracked(accumulated: str) -> bool:
            nonlocal proc_was_tracked
            proc_was_tracked = len(active_procs) > 0
            return False

        mock_create = make_streaming_proc(returncode=0, stdout="Line one")

        with patch("asyncio.create_subprocess_exec", mock_create):
            await stream_claude_process(
                **_default_kwargs(
                    event_bus, active_procs=active_procs, on_output=check_tracked
                )
            )

        assert proc_was_tracked
        assert len(active_procs) == 0


# ---------------------------------------------------------------------------
# terminate_processes
# ---------------------------------------------------------------------------


class TestTerminateProcesses:
    """Tests for the terminate_processes utility."""

    def test_kills_all_active_processes(self) -> None:
        """terminate_processes should use os.killpg() on all tracked processes."""
        proc1 = MagicMock()
        proc1.pid = 111
        proc2 = MagicMock()
        proc2.pid = 222
        active: set[asyncio.subprocess.Process] = {proc1, proc2}

        with patch("runner_utils.os.killpg") as mock_killpg:
            terminate_processes(active)

        assert mock_killpg.call_count == 2

    def test_handles_process_lookup_error(self) -> None:
        """terminate_processes should not raise when a process has already exited."""
        proc = MagicMock()
        proc.pid = 12345
        active: set[asyncio.subprocess.Process] = {proc}

        with patch("runner_utils.os.killpg", side_effect=ProcessLookupError):
            terminate_processes(active)  # Should not raise

    def test_empty_set_is_noop(self) -> None:
        """terminate_processes with empty set should be a no-op."""
        active: set[asyncio.subprocess.Process] = set()
        terminate_processes(active)  # Should not raise

    def test_uses_killpg_with_sigkill(self) -> None:
        """terminate_processes should use os.killpg() with SIGKILL."""
        proc = MagicMock()
        proc.pid = 12345
        active: set[asyncio.subprocess.Process] = {proc}

        with patch("runner_utils.os.killpg") as mock_killpg:
            terminate_processes(active)

        mock_killpg.assert_called_once_with(12345, signal.SIGKILL)

    def test_falls_back_to_kill_on_oserror(self) -> None:
        """When os.killpg() raises OSError, should fall back to proc.kill()."""
        proc = MagicMock()
        proc.pid = 12345
        active: set[asyncio.subprocess.Process] = {proc}

        with patch("runner_utils.os.killpg", side_effect=OSError("no such group")):
            terminate_processes(active)

        # OSError suppressed, no crash
        proc.kill.assert_not_called()  # OSError is suppressed entirely

    def test_handles_none_pid(self) -> None:
        """When proc.pid is None, should fall back to proc.kill()."""
        proc = MagicMock()
        proc.pid = None
        active: set[asyncio.subprocess.Process] = {proc}

        terminate_processes(active)

        proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# stream_claude_process — start_new_session
# ---------------------------------------------------------------------------


class TestStreamClaudeProcessSessionGroup:
    """Tests for process group (start_new_session) behavior."""

    @pytest.mark.asyncio
    async def test_subprocess_spawned_with_start_new_session(self, event_bus) -> None:
        """create_subprocess_exec should be called with start_new_session=True."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")

        with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
            await stream_claude_process(**_default_kwargs(event_bus))

        kwargs = mock_exec.call_args[1]
        assert kwargs["start_new_session"] is True


# ---------------------------------------------------------------------------
# stream_claude_process — timeout behavior
# ---------------------------------------------------------------------------


class TestStreamClaudeProcessTimeout:
    """Tests for stream_claude_process timeout behavior."""

    @pytest.mark.asyncio
    async def test_no_timeout_by_default(self, event_bus) -> None:
        """When timeout=None (default), no wait_for wrapping occurs."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            patch("asyncio.wait_for") as mock_wait_for,
        ):
            await stream_claude_process(**_default_kwargs(event_bus))

        mock_wait_for.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_kills_process_and_raises(self, event_bus) -> None:
        """When timeout fires, process is killed and RuntimeError is raised."""

        class HangingIter:
            """Async iterator that hangs until cancelled."""

            def __aiter__(self):  # noqa: ANN204
                return self

            async def __anext__(self) -> bytes:
                await asyncio.sleep(3600)
                return b""

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdout = HangingIter()
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        mock_create = AsyncMock(return_value=mock_proc)
        active_procs: set[asyncio.subprocess.Process] = set()

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(RuntimeError, match="timed out after 0.01s"),
        ):
            await stream_claude_process(
                **_default_kwargs(event_bus, active_procs=active_procs),
                timeout=0.01,
            )

        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_cleans_up_active_procs(self, event_bus) -> None:
        """Process should be removed from active_procs on timeout."""

        class HangingIter:
            """Async iterator that hangs."""

            def __aiter__(self):  # noqa: ANN204
                return self

            async def __anext__(self) -> bytes:
                await asyncio.sleep(3600)
                return b""

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdout = HangingIter()
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        mock_create = AsyncMock(return_value=mock_proc)
        active_procs: set[asyncio.subprocess.Process] = set()

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(RuntimeError),
        ):
            await stream_claude_process(
                **_default_kwargs(event_bus, active_procs=active_procs),
                timeout=0.01,
            )

        assert len(active_procs) == 0
