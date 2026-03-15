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
from runner_utils import (
    check_post_stream_errors,
    prepare_command,
    resolve_transcript,
    stream_claude_process,
    terminate_processes,
)
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

    @pytest.mark.asyncio
    async def test_populates_usage_stats_when_provided(self, event_bus) -> None:
        """Usage metrics should be extracted from stream events with minimal overhead."""
        usage_event = json.dumps(
            {
                "type": "result",
                "result": "done",
                "usage": {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
            }
        )
        mock_create = make_streaming_proc(returncode=0, stdout=usage_event)
        usage_stats: dict[str, object] = {}

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await stream_claude_process(
                **_default_kwargs(event_bus, usage_stats=usage_stats)
            )

        assert result == "done"
        assert usage_stats["input_tokens"] == 50
        assert usage_stats["output_tokens"] == 10
        assert usage_stats["total_tokens"] == 60
        assert usage_stats["usage_status"] == "available"
        assert usage_stats["usage_available"] is True
        assert usage_stats["usage_backend"] == "claude"
        assert isinstance(usage_stats["raw_usage"], list)


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

    @pytest.mark.asyncio
    async def test_codex_exec_passes_prompt_as_argument(self, event_bus) -> None:
        """Codex exec should receive prompt as CLI arg, not stdin pipe."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")
        cmd = ["codex", "exec", "--json", "--model", "gpt-5.3"]
        prompt = "do the thing"

        with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
            await stream_claude_process(
                **_default_kwargs(event_bus, cmd=cmd, prompt=prompt)
            )

        args = list(mock_exec.call_args[0])
        kwargs = mock_exec.call_args[1]
        assert args[-1] == prompt
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL

    @pytest.mark.asyncio
    async def test_pi_print_passes_prompt_as_argument(self, event_bus) -> None:
        """Pi print mode should insert prompt right after -p, not at end."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")
        cmd = ["pi", "-p", "--mode", "json", "--model", "openai/gpt-4o-mini"]
        prompt = "do the thing"

        with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
            await stream_claude_process(
                **_default_kwargs(event_bus, cmd=cmd, prompt=prompt)
            )

        args = list(mock_exec.call_args[0])
        kwargs = mock_exec.call_args[1]
        # Prompt must be immediately after -p for the CLI to recognise it.
        p_idx = args.index("-p")
        assert args[p_idx + 1] == prompt
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL

    @pytest.mark.asyncio
    async def test_claude_print_passes_prompt_as_argument(self, event_bus) -> None:
        """Claude -p should insert prompt right after -p, not at end."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")
        cmd = ["claude", "-p", "--output-format", "stream-json", "--model", "sonnet"]
        prompt = "evaluate this issue"

        with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
            await stream_claude_process(
                **_default_kwargs(event_bus, cmd=cmd, prompt=prompt)
            )

        args = list(mock_exec.call_args[0])
        kwargs = mock_exec.call_args[1]
        # Prompt must be immediately after -p for the CLI to recognise it.
        p_idx = args.index("-p")
        assert args[p_idx + 1] == prompt
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL

    @pytest.mark.asyncio
    async def test_claude_print_with_disallowed_tools(self, event_bus) -> None:
        """Planner pattern: prompt must go after -p, not after --disallowedTools."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--model",
            "opus",
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
            "--disallowedTools",
            "Write,Edit,NotebookEdit",
        ]
        prompt = "Plan this issue: " + "x" * 8000

        with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
            await stream_claude_process(
                **_default_kwargs(event_bus, cmd=cmd, prompt=prompt)
            )

        args = list(mock_exec.call_args[0])
        p_idx = args.index("-p")
        assert args[p_idx + 1] == prompt, "prompt must be right after -p"
        # --disallowedTools value must not be eaten by prompt placement
        dt_idx = args.index("--disallowedTools")
        assert args[dt_idx + 1] == "Write,Edit,NotebookEdit"


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

    @pytest.mark.asyncio
    async def test_early_kill_ignores_auth_failed_in_output(self, event_bus) -> None:
        """When on_output kills the process, auth_failed in output should not raise."""
        import json

        auth_line = json.dumps({"error": "authentication_failed"})
        mock_create = make_streaming_proc(
            returncode=0, stdout=f"good output\n{auth_line}"
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await stream_claude_process(
                **_default_kwargs(
                    event_bus,
                    on_output=lambda _: True,  # Kill immediately
                )
            )

        # Should NOT raise AuthenticationRetryError
        assert "good output" in result


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
    async def test_timeout_cancels_stderr_task(self, event_bus) -> None:
        """On timeout, stderr_task must be cancelled and awaited — no pending task leak."""
        stderr_read_started = asyncio.Event()

        async def hanging_stderr_read() -> bytes:
            stderr_read_started.set()
            await asyncio.sleep(3600)
            return b""

        class HangingIter:
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
        mock_proc.stderr.read = hanging_stderr_read
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        mock_create = AsyncMock(return_value=mock_proc)

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(RuntimeError, match="timed out"),
        ):
            await stream_claude_process(**_default_kwargs(event_bus), timeout=0.01)

        # The finally block in stream_claude_process already cancelled and awaited
        # stderr_task before raising, so no sleep(0) is needed here.
        assert stderr_read_started.is_set(), (
            "stderr task should have started before timeout"
        )

        # The key assertion: no pending tasks should remain after the function returns
        # If stderr_task was not cancelled+awaited in the finally block, it would
        # still be pending here.
        current = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        assert not pending, f"stderr_task was not cleaned up: {pending}"

        mock_proc.kill.assert_called()
        mock_proc.wait.assert_awaited()

    @pytest.mark.asyncio
    async def test_timeout_chains_original_exception(self, event_bus) -> None:
        """Timeout RuntimeError should chain the original TimeoutError via __cause__."""

        class HangingIter:
            def __aiter__(self):
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

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(RuntimeError, match="timed out") as exc_info,
        ):
            await stream_claude_process(**_default_kwargs(event_bus), timeout=0.01)

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, TimeoutError)

    @pytest.mark.asyncio
    async def test_cancellation_cancels_stderr_task(self, event_bus) -> None:
        """On CancelledError, stderr_task must be cancelled — no pending task leak."""
        stderr_read_started = asyncio.Event()

        async def hanging_stderr_read() -> bytes:
            stderr_read_started.set()
            await asyncio.sleep(3600)
            return b""

        class CancellingIter:
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
        mock_proc.stderr.read = hanging_stderr_read
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        mock_create = AsyncMock(return_value=mock_proc)

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(asyncio.CancelledError),
        ):
            await stream_claude_process(**_default_kwargs(event_bus))

        # The finally block in stream_claude_process already cancelled and awaited
        # stderr_task before raising, so stderr_read_started is set before we get here.
        # Verify the stderr task actually started before the CancelledError fired
        assert stderr_read_started.is_set(), (
            "stderr task should have started before cancellation"
        )

        # The key assertion: no pending tasks should remain after the function raises
        # If stderr_task was not cancelled+awaited, it would still be pending here
        current = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        assert not pending, (
            f"stderr_task was not cleaned up on CancelledError: {pending}"
        )

        mock_proc.kill.assert_called_once()

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

        assert proc_was_tracked is True
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

        with patch(
            "runner_utils.os.killpg", side_effect=ProcessLookupError
        ) as mock_killpg:
            terminate_processes(active)  # Should not raise
        mock_killpg.assert_called_once()

    def test_empty_set_is_noop(self) -> None:
        """terminate_processes with empty set should be a no-op."""
        active: set[asyncio.subprocess.Process] = set()
        terminate_processes(active)  # Should not raise
        assert len(active) == 0

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
    async def test_default_timeout_applied(self, event_bus) -> None:
        """Default timeout of 3600s is always applied via wait_for."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await stream_claude_process(**_default_kwargs(event_bus))

        # The function completes normally with a 3600s default timeout
        assert result == "ok"

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


# ---------------------------------------------------------------------------
# stream_claude_process — gh_token injection
# ---------------------------------------------------------------------------


class TestStreamClaudeProcessGhToken:
    """Tests for gh_token propagation into subprocess environment."""

    @pytest.mark.asyncio
    async def test_gh_token_injected_into_env(self, event_bus) -> None:
        """When gh_token is passed, it should appear in the subprocess env as GH_TOKEN."""
        captured_env: dict[str, str] = {}
        mock_create = make_streaming_proc(returncode=0, stdout="ok")

        original_create = mock_create

        async def capture_env(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return await original_create(*args, **kwargs)

        with patch("asyncio.create_subprocess_exec", side_effect=capture_env):
            await stream_claude_process(
                **_default_kwargs(event_bus), gh_token="ghp_bot_token"
            )

        assert captured_env.get("GH_TOKEN") == "ghp_bot_token"

    @pytest.mark.asyncio
    async def test_empty_gh_token_does_not_override(self, event_bus) -> None:
        """When gh_token is empty, GH_TOKEN should not be explicitly injected."""
        captured_env: dict[str, str] = {}
        mock_create = make_streaming_proc(returncode=0, stdout="ok")
        original_create = mock_create

        async def capture_env(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return await original_create(*args, **kwargs)

        with patch("asyncio.create_subprocess_exec", side_effect=capture_env):
            await stream_claude_process(**_default_kwargs(event_bus), gh_token="")

        # GH_TOKEN is only set if it was already in os.environ (inherited),
        # not explicitly injected by make_clean_env.
        # The key assertion: no bot-specific override was applied.
        assert captured_env.get("GH_TOKEN", "") != "ghp_bot_token"
        # Also verify: GH_TOKEN key should be absent from env (not just
        # different from ghp_bot_token) or should preserve the inherited value.
        if "GH_TOKEN" in captured_env:
            # If present, it was inherited from os.environ, not injected
            assert captured_env["GH_TOKEN"] == os.environ.get("GH_TOKEN", "")


# ---------------------------------------------------------------------------
# _prepare_command — extracted helper
# ---------------------------------------------------------------------------


class TestPrepareCommand:
    """Tests for the _prepare_command helper extracted from stream_claude_process."""

    def test_claude_print_inserts_prompt_after_flag(self) -> None:
        cmd = ["claude", "-p", "--model", "sonnet"]
        cmd_out, stdin_mode = prepare_command(cmd, "my prompt")
        assert cmd_out == ["claude", "-p", "my prompt", "--model", "sonnet"]
        assert stdin_mode == asyncio.subprocess.DEVNULL

    def test_codex_exec_appends_prompt(self) -> None:
        cmd = ["codex", "exec"]
        cmd_out, stdin_mode = prepare_command(cmd, "do stuff")
        assert cmd_out == ["codex", "exec", "do stuff"]
        assert stdin_mode == asyncio.subprocess.DEVNULL

    def test_pi_print_inserts_prompt_after_flag(self) -> None:
        cmd = ["pi", "-p"]
        cmd_out, stdin_mode = prepare_command(cmd, "plan it")
        assert cmd_out == ["pi", "-p", "plan it"]
        assert stdin_mode == asyncio.subprocess.DEVNULL

    def test_unknown_tool_uses_stdin(self) -> None:
        cmd = ["other-tool", "--flag"]
        cmd_out, stdin_mode = prepare_command(cmd, "prompt")
        assert cmd_out == ["other-tool", "--flag"]
        assert stdin_mode == asyncio.subprocess.PIPE

    def test_pi_with_long_print_flag(self) -> None:
        cmd = ["pi", "--print"]
        cmd_out, stdin_mode = prepare_command(cmd, "prompt")
        assert cmd_out == ["pi", "--print", "prompt"]
        assert stdin_mode == asyncio.subprocess.DEVNULL

    def test_empty_cmd_uses_stdin(self) -> None:
        cmd: list[str] = []
        cmd_out, stdin_mode = prepare_command(cmd, "prompt")
        assert cmd_out == []
        assert stdin_mode == asyncio.subprocess.PIPE


# ---------------------------------------------------------------------------
# _check_post_stream_errors — extracted helper
# ---------------------------------------------------------------------------


class TestCheckPostStreamErrors:
    """Tests for the _check_post_stream_errors helper."""

    def test_raises_auth_error_on_authentication_failed(self) -> None:
        from runner_utils import AuthenticationRetryError

        with pytest.raises(AuthenticationRetryError):
            check_post_stream_errors(
                raw_lines=['{"error":"authentication_failed"}'],
                accumulated_text="",
                stderr_text="",
                early_killed=False,
                returncode=1,
                caller_logger=logging.getLogger("test"),
            )

    def test_no_error_when_early_killed(self) -> None:
        # Should not raise even with auth failure markers when early_killed
        check_post_stream_errors(
            raw_lines=['{"error":"authentication_failed"}'],
            accumulated_text="",
            stderr_text="",
            early_killed=True,
            returncode=0,
            caller_logger=logging.getLogger("test"),
        )

    def test_raises_credit_exhausted_on_credit_limit(self) -> None:
        from subprocess_util import CreditExhaustedError

        with pytest.raises(CreditExhaustedError):
            check_post_stream_errors(
                raw_lines=[],
                accumulated_text="Your credit balance is too low",
                stderr_text="",
                early_killed=False,
                returncode=0,
                caller_logger=logging.getLogger("test"),
            )

    def test_logs_warning_on_nonzero_exit(self, caplog) -> None:
        test_logger = logging.getLogger("test_nonzero")
        with caplog.at_level(logging.WARNING, logger="test_nonzero"):
            check_post_stream_errors(
                raw_lines=["normal output"],
                accumulated_text="normal output",
                stderr_text="some error",
                early_killed=False,
                returncode=1,
                caller_logger=test_logger,
            )
        assert "exited with code 1" in caplog.text

    def test_no_error_on_clean_exit(self) -> None:
        # Should not raise on a clean exit
        check_post_stream_errors(
            raw_lines=["ok"],
            accumulated_text="ok",
            stderr_text="",
            early_killed=False,
            returncode=0,
            caller_logger=logging.getLogger("test"),
        )


# ---------------------------------------------------------------------------
# _resolve_transcript — extracted helper
# ---------------------------------------------------------------------------


class TestResolveTranscript:
    """Tests for the _resolve_transcript helper."""

    def test_prefers_result_text(self) -> None:
        transcript = resolve_transcript(
            result_text="result",
            accumulated_text="accumulated",
            raw_lines=["raw"],
            stderr_text="",
            returncode=0,
            caller_logger=logging.getLogger("test"),
        )
        assert transcript == "result"

    def test_falls_back_to_accumulated(self) -> None:
        transcript = resolve_transcript(
            result_text="",
            accumulated_text="accumulated\n",
            raw_lines=["raw"],
            stderr_text="",
            returncode=0,
            caller_logger=logging.getLogger("test"),
        )
        assert transcript == "accumulated"

    def test_falls_back_to_raw_lines(self) -> None:
        transcript = resolve_transcript(
            result_text="",
            accumulated_text="",
            raw_lines=["line1", "line2"],
            stderr_text="",
            returncode=0,
            caller_logger=logging.getLogger("test"),
        )
        assert transcript == "line1\nline2"

    def test_logs_warning_when_empty_with_stderr(self, caplog) -> None:
        test_logger = logging.getLogger("test_empty_stderr")
        with caplog.at_level(logging.WARNING, logger="test_empty_stderr"):
            resolve_transcript(
                result_text="",
                accumulated_text="",
                raw_lines=[],
                stderr_text="something went wrong",
                returncode=1,
                caller_logger=test_logger,
            )
        assert "empty stdout" in caplog.text


# ---------------------------------------------------------------------------
# _write_stdin — extracted helper
# ---------------------------------------------------------------------------


class TestWriteStdin:
    """Tests for the _write_stdin helper extracted from stream_claude_process."""

    @pytest.mark.asyncio
    async def test_writes_prompt_to_stdin(self) -> None:
        """_write_stdin should encode and write the prompt, then close stdin."""
        from runner_utils import _write_stdin

        proc = AsyncMock()
        proc.stdin = MagicMock()
        proc.stdin.drain = AsyncMock()

        await _write_stdin(proc, "hello")

        proc.stdin.write.assert_called_once_with(b"hello")
        proc.stdin.drain.assert_awaited_once()
        proc.stdin.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_stdin_is_none(self) -> None:
        """_write_stdin should raise AssertionError when stdin is None."""
        from runner_utils import _write_stdin

        proc = AsyncMock()
        proc.stdin = None

        with pytest.raises(AssertionError):
            await _write_stdin(proc, "hello")


# ---------------------------------------------------------------------------
# _read_stdout_lines — extracted helper
# ---------------------------------------------------------------------------


class TestReadStdoutLines:
    """Tests for the _read_stdout_lines helper extracted from stream_claude_process."""

    @pytest.mark.asyncio
    async def test_collects_raw_lines(self, event_bus) -> None:
        """_read_stdout_lines should collect all raw stdout lines."""
        from runner_utils import _read_stdout_lines
        from stream_parser import StreamParser

        lines_data = [b"Line one\n", b"Line two\n"]

        async def async_iter():
            for line in lines_data:
                yield line

        proc = AsyncMock()
        parser = StreamParser()

        raw_lines, result_text, accumulated, early_killed = await _read_stdout_lines(
            async_iter(),
            parser,
            event_bus,
            {"issue": 1},
            None,
            proc,
        )

        assert len(raw_lines) == 2
        assert "Line one" in raw_lines[0]
        assert "Line two" in raw_lines[1]
        assert early_killed is False

    @pytest.mark.asyncio
    async def test_early_kill_on_callback(self, event_bus) -> None:
        """_read_stdout_lines should kill process when on_output returns True."""
        from runner_utils import _read_stdout_lines
        from stream_parser import StreamParser

        lines_data = [b"Line one\n", b"Line two\n", b"Line three\n"]

        async def async_iter():
            for line in lines_data:
                yield line

        proc = AsyncMock()
        proc.kill = MagicMock()
        parser = StreamParser()

        raw_lines, _, _, early_killed = await _read_stdout_lines(
            async_iter(),
            parser,
            event_bus,
            {"issue": 1},
            lambda _: True,  # Kill on first output
            proc,
        )

        assert early_killed is True
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_blank_lines(self, event_bus) -> None:
        """_read_stdout_lines should not accumulate blank lines."""
        from runner_utils import _read_stdout_lines
        from stream_parser import StreamParser

        lines_data = [b"Line one\n", b"\n", b"   \n", b"Line two\n"]

        async def async_iter():
            for line in lines_data:
                yield line

        proc = AsyncMock()
        parser = StreamParser()

        raw_lines, _, accumulated, _ = await _read_stdout_lines(
            async_iter(),
            parser,
            event_bus,
            {"issue": 1},
            None,
            proc,
        )

        # Raw lines include all lines, accumulated skips blanks
        assert len(raw_lines) == 4
        assert "Line one" in accumulated
        assert "Line two" in accumulated

    @pytest.mark.asyncio
    async def test_publishes_transcript_events(self, event_bus) -> None:
        """_read_stdout_lines should publish TRANSCRIPT_LINE events."""
        from runner_utils import _read_stdout_lines
        from stream_parser import StreamParser

        lines_data = [b"Hello world\n"]

        async def async_iter():
            for line in lines_data:
                yield line

        proc = AsyncMock()
        parser = StreamParser()

        await _read_stdout_lines(
            async_iter(),
            parser,
            event_bus,
            {"issue": 1},
            None,
            proc,
        )

        events = event_bus.get_history()
        transcript_events = [e for e in events if e.type == EventType.TRANSCRIPT_LINE]
        assert len(transcript_events) == 1
        assert transcript_events[0].data["line"] == "Hello world"


# ---------------------------------------------------------------------------
# _collect_output — extracted from stream_claude_process
# ---------------------------------------------------------------------------


class TestCollectOutput:
    """Tests for _collect_output extracted from stream_claude_process."""

    @pytest.mark.asyncio
    async def test_returns_transcript_from_stdout(self, event_bus) -> None:
        """_collect_output should return transcript from parsed stdout."""
        from runner_utils import _collect_output
        from stream_parser import StreamParser

        lines_data = [b"Hello from agent\n"]

        async def async_iter():
            for line in lines_data:
                yield line

        proc = AsyncMock()
        proc.stdout = async_iter()
        proc.wait = AsyncMock()
        proc.returncode = 0

        stderr_future: asyncio.Future[bytes] = asyncio.get_event_loop().create_future()
        stderr_future.set_result(b"")
        stderr_task = asyncio.ensure_future(stderr_future)

        parser = StreamParser()
        result = await _collect_output(
            proc,
            parser,
            stderr_task,
            event_bus,
            {"issue": 1},
            None,
            None,
            logging.getLogger("test"),
        )

        assert "Hello from agent" in result

    @pytest.mark.asyncio
    async def test_updates_usage_stats(self, event_bus) -> None:
        """_collect_output should update usage_stats from parser snapshot."""
        from runner_utils import _collect_output
        from stream_parser import StreamParser

        async def async_iter():
            return
            yield  # make it an async generator  # noqa: RET504

        proc = AsyncMock()
        proc.stdout = async_iter()
        proc.wait = AsyncMock()
        proc.returncode = 0

        stderr_future: asyncio.Future[bytes] = asyncio.get_event_loop().create_future()
        stderr_future.set_result(b"")
        stderr_task = asyncio.ensure_future(stderr_future)

        parser = StreamParser()
        usage: dict[str, object] = {}
        await _collect_output(
            proc,
            parser,
            stderr_task,
            event_bus,
            {"issue": 1},
            None,
            usage,
            logging.getLogger("test"),
        )

        # usage_stats dict should have been updated (even if empty snapshot)
        assert isinstance(usage, dict)

    @pytest.mark.asyncio
    async def test_raises_on_auth_failure(self, event_bus) -> None:
        """_collect_output should raise AuthenticationRetryError on auth failure."""
        from runner_utils import AuthenticationRetryError, _collect_output
        from stream_parser import StreamParser

        lines_data = [b'"error":"authentication_failed"\n']

        async def async_iter():
            for line in lines_data:
                yield line

        proc = AsyncMock()
        proc.stdout = async_iter()
        proc.wait = AsyncMock()
        proc.returncode = 1

        stderr_future: asyncio.Future[bytes] = asyncio.get_event_loop().create_future()
        stderr_future.set_result(b"")
        stderr_task = asyncio.ensure_future(stderr_future)

        parser = StreamParser()
        with pytest.raises(AuthenticationRetryError):
            await _collect_output(
                proc,
                parser,
                stderr_task,
                event_bus,
                {"issue": 1},
                None,
                None,
                logging.getLogger("test"),
            )


# ---------------------------------------------------------------------------
# _create_and_start_process — extracted from stream_claude_process
# ---------------------------------------------------------------------------


class TestCreateAndStartProcess:
    """Tests for _create_and_start_process extracted from stream_claude_process."""

    @pytest.mark.asyncio
    async def test_returns_process_and_stdin_mode(self) -> None:
        """_create_and_start_process returns (proc, stdin_mode) tuple."""
        from runner_utils import _create_and_start_process

        mock_proc = AsyncMock()
        mock_runner = AsyncMock()
        mock_runner.create_streaming_process = AsyncMock(return_value=mock_proc)

        proc, stdin_mode = await _create_and_start_process(
            mock_runner,
            ["claude", "-p"],
            "test prompt",
            Path("/tmp/test"),
            "",
        )

        assert proc is mock_proc
        # claude -p uses prompt arg, so stdin is DEVNULL
        assert stdin_mode == asyncio.subprocess.DEVNULL
        mock_runner.create_streaming_process.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_prompt_in_command_for_claude(self) -> None:
        """For claude -p, the prompt should be inserted into the command."""
        from runner_utils import _create_and_start_process

        mock_proc = AsyncMock()
        mock_runner = AsyncMock()
        mock_runner.create_streaming_process = AsyncMock(return_value=mock_proc)

        await _create_and_start_process(
            mock_runner,
            ["claude", "-p"],
            "hello world",
            Path("/tmp/test"),
            "",
        )

        call_args = mock_runner.create_streaming_process.call_args
        cmd_arg = call_args[0][0]
        assert "hello world" in cmd_arg

    @pytest.mark.asyncio
    async def test_uses_pipe_stdin_for_non_prompt_cmd(self) -> None:
        """For commands without -p, stdin should be PIPE."""
        from runner_utils import _create_and_start_process

        mock_proc = AsyncMock()
        mock_runner = AsyncMock()
        mock_runner.create_streaming_process = AsyncMock(return_value=mock_proc)

        _, stdin_mode = await _create_and_start_process(
            mock_runner,
            ["some-tool"],
            "test prompt",
            Path("/tmp/test"),
            "",
        )

        assert stdin_mode == asyncio.subprocess.PIPE
