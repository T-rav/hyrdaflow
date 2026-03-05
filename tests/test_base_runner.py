"""Tests for base_runner.py — BaseRunner class."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_runner import BaseRunner
from events import EventBus

# ---------------------------------------------------------------------------
# Concrete subclass for testing (BaseRunner has abstract _log ClassVar)
# ---------------------------------------------------------------------------


class _TestRunner(BaseRunner):
    """Minimal concrete subclass used in tests."""

    _log = logging.getLogger("hydraflow.test_runner")


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestBaseRunnerInit:
    """Tests for BaseRunner.__init__."""

    def test_init_stores_config_reference(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner._config is config

    def test_init_stores_event_bus_reference(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner._bus is event_bus

    def test_active_procs_starts_empty(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner._active_procs == set()

    def test_uses_provided_runner(self, config, event_bus: EventBus) -> None:
        mock_runner = MagicMock()
        runner = _TestRunner(config, event_bus, runner=mock_runner)
        assert runner._runner is mock_runner

    def test_uses_default_runner_when_none(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner._runner is not None


# ---------------------------------------------------------------------------
# terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    """Tests for BaseRunner.terminate."""

    def test_calls_terminate_processes(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        runner._active_procs.add(mock_proc)

        with patch("base_runner.terminate_processes") as mock_tp:
            runner.terminate()
        mock_tp.assert_called_once_with(runner._active_procs)

    def test_terminate_with_empty_procs_does_not_raise(
        self, config, event_bus: EventBus
    ) -> None:
        runner = _TestRunner(config, event_bus)
        runner.terminate()  # Should not raise


# ---------------------------------------------------------------------------
# _save_transcript
# ---------------------------------------------------------------------------


class TestSaveTranscript:
    """Tests for BaseRunner._save_transcript."""

    def test_writes_file_with_prefix_and_identifier(
        self, config, event_bus: EventBus
    ) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = _TestRunner(config, event_bus)
        runner._save_transcript("issue", 42, "transcript content")

        path = config.repo_root / ".hydraflow" / "logs" / "issue-42.txt"
        assert path.exists()
        assert path.read_text() == "transcript content"

    def test_creates_log_directory(self, config, event_bus: EventBus) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert not log_dir.exists()

        runner = _TestRunner(config, event_bus)
        runner._save_transcript("plan-issue", 7, "content")

        assert log_dir.is_dir()

    def test_different_prefixes_produce_different_files(
        self, config, event_bus: EventBus
    ) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = _TestRunner(config, event_bus)

        runner._save_transcript("issue", 1, "agent transcript")
        runner._save_transcript("review-pr", 1, "review transcript")

        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "issue-1.txt").read_text() == "agent transcript"
        assert (log_dir / "review-pr-1.txt").read_text() == "review transcript"

    def test_handles_oserror(
        self, config, event_bus: EventBus, caplog: pytest.LogCaptureFixture
    ) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = _TestRunner(config, event_bus)

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            runner._save_transcript("issue", 42, "content")  # should not raise

        assert "Could not save transcript" in caplog.text


# ---------------------------------------------------------------------------
# _execute
# ---------------------------------------------------------------------------


class TestExecute:
    """Tests for BaseRunner._execute."""

    @pytest.mark.asyncio
    async def test_delegates_to_stream_claude_process(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        runner = _TestRunner(config, event_bus)

        with patch("base_runner.stream_claude_process", new_callable=AsyncMock) as mock:
            mock.return_value = "transcript output"
            result = await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": 42}
            )

        assert result == "transcript output"
        mock.assert_awaited_once()
        call_kwargs = mock.call_args[1]
        expected_kwargs = {
            "cmd": ["claude", "-p"],
            "prompt": "prompt",
            "cwd": tmp_path,
            "event_data": {"issue": 42},
            "on_output": None,
            "gh_token": config.gh_token,
        }
        assert {k: call_kwargs[k] for k in expected_kwargs} == expected_kwargs

    @pytest.mark.asyncio
    async def test_passes_on_output_callback(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        runner = _TestRunner(config, event_bus)

        def callback(text: str) -> bool:
            return "DONE" in text

        with patch("base_runner.stream_claude_process", new_callable=AsyncMock) as mock:
            mock.return_value = "output"
            await runner._execute(
                ["claude", "-p"],
                "prompt",
                tmp_path,
                {"issue": 42},
                on_output=callback,
            )

        call_kwargs = mock.call_args[1]
        assert call_kwargs["on_output"] is callback


# ---------------------------------------------------------------------------
# _inject_manifest_and_memory
# ---------------------------------------------------------------------------


class TestInjectManifestAndMemory:
    """Tests for BaseRunner._inject_manifest_and_memory."""

    def test_inject_returns_manifest_and_memory_when_both_present(
        self, config, event_bus: EventBus
    ) -> None:
        runner = _TestRunner(config, event_bus)

        with (
            patch("base_runner.load_project_manifest", return_value="manifest text"),
            patch("base_runner.load_memory_digest", return_value="digest text"),
        ):
            manifest_sec, memory_sec = runner._inject_manifest_and_memory()

        assert "## Project Context" in manifest_sec
        assert "manifest text" in manifest_sec
        assert "## Accumulated Learnings" in memory_sec
        assert "digest text" in memory_sec

    def test_inject_returns_manifest_section_when_only_manifest_exists(
        self, config, event_bus: EventBus
    ) -> None:
        runner = _TestRunner(config, event_bus)

        with (
            patch("base_runner.load_project_manifest", return_value="manifest text"),
            patch("base_runner.load_memory_digest", return_value=""),
        ):
            manifest_sec, memory_sec = runner._inject_manifest_and_memory()

        assert "## Project Context" in manifest_sec
        assert memory_sec == ""

    def test_inject_returns_memory_section_when_only_digest_exists(
        self, config, event_bus: EventBus
    ) -> None:
        runner = _TestRunner(config, event_bus)

        with (
            patch("base_runner.load_project_manifest", return_value=""),
            patch("base_runner.load_memory_digest", return_value="digest text"),
        ):
            manifest_sec, memory_sec = runner._inject_manifest_and_memory()

        assert manifest_sec == ""
        assert "## Accumulated Learnings" in memory_sec

    def test_inject_returns_empty_strings_when_no_manifest_or_digest(
        self, config, event_bus: EventBus
    ) -> None:
        runner = _TestRunner(config, event_bus)

        with (
            patch("base_runner.load_project_manifest", return_value=""),
            patch("base_runner.load_memory_digest", return_value=""),
        ):
            manifest_sec, memory_sec = runner._inject_manifest_and_memory()

        assert manifest_sec == ""
        assert memory_sec == ""


# ---------------------------------------------------------------------------
# _verify_quality
# ---------------------------------------------------------------------------


class TestVerifyQuality:
    """Tests for BaseRunner._verify_quality."""

    @pytest.mark.asyncio
    async def test_success(self, config, event_bus: EventBus, tmp_path: Path) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(
            return_value=MagicMock(returncode=0, stdout="OK", stderr="")
        )
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        success, msg = await runner._verify_quality(tmp_path)

        assert success is True
        assert msg == "OK"

    @pytest.mark.asyncio
    async def test_failure_nonzero_returncode(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(
            return_value=MagicMock(
                returncode=1, stdout="FAILED test_foo", stderr="error details"
            )
        )
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        success, msg = await runner._verify_quality(tmp_path)

        assert success is False
        assert "`make quality` failed" in msg
        assert "FAILED test_foo" in msg

    @pytest.mark.asyncio
    async def test_file_not_found(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(side_effect=FileNotFoundError)
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        success, msg = await runner._verify_quality(tmp_path)

        assert success is False
        assert "make not found" in msg

    @pytest.mark.asyncio
    async def test_timeout(self, config, event_bus: EventBus, tmp_path: Path) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(side_effect=TimeoutError)
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        success, msg = await runner._verify_quality(tmp_path)

        assert success is False
        assert "timed out" in msg

    @pytest.mark.asyncio
    async def test_verify_quality_truncates_long_failure_output(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        long_output = "x" * 5000
        mock_runner.run_simple = AsyncMock(
            return_value=MagicMock(returncode=1, stdout=long_output, stderr="")
        )
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        success, msg = await runner._verify_quality(tmp_path)

        assert success is False
        # Output should be truncated to last 3000 chars
        assert len(msg) < 5000 + 100  # some overhead for prefix text


# ---------------------------------------------------------------------------
# _build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    """Tests for BaseRunner._build_command (default implementation-tool command)."""

    def test_build_command_starts_with_claude(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert cmd[0] == "claude"

    def test_build_command_uses_implementation_tool_and_model(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == config.model
        assert "--max-budget-usd" not in cmd

    def test_build_command_path_argument_is_unused(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """The worktree_path arg is accepted for API compatibility but not included in cmd."""
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "--cwd" not in cmd

    def test_build_command_accepts_none_worktree_path(
        self, config, event_bus: EventBus
    ) -> None:
        """The worktree_path parameter is optional (None) for runners that don't need worktrees."""
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(None)
        assert cmd[0] == "claude"

    def test_build_command_works_without_arguments(
        self, config, event_bus: EventBus
    ) -> None:
        """The worktree_path parameter defaults to None when omitted."""
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command()
        assert cmd[0] == "claude"
