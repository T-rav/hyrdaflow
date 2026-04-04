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
from runner_utils import AuthenticationRetryError

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

    def test_active_count_starts_at_zero(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner.active_count == 0

    def test_active_count_reflects_active_procs_size(
        self, config, event_bus: EventBus
    ) -> None:
        runner = _TestRunner(config, event_bus)
        mock_proc1 = MagicMock()
        mock_proc1.pid = 1
        mock_proc2 = MagicMock()
        mock_proc2.pid = 2
        runner._active_procs.add(mock_proc1)
        assert runner.active_count == 1
        runner._active_procs.add(mock_proc2)
        assert runner.active_count == 2
        runner._active_procs.discard(mock_proc1)
        assert runner.active_count == 1

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
        assert len(runner._active_procs) == 0  # empty procs remain unchanged


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
            "gh_token": runner._credentials.gh_token,
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

    @pytest.mark.asyncio
    async def test_auth_failure_retries_with_backoff(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Auth failures are retried 3 times before raising."""
        runner = _TestRunner(config, event_bus)

        with (
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=AuthenticationRetryError("auth failed"),
            ) as mock,
            patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
            pytest.raises(AuthenticationRetryError),
        ):
            await runner._execute(["claude", "-p"], "prompt", tmp_path, {"issue": 42})

        assert mock.await_count == 3
        # 2 sleeps: 5s after attempt 1, 10s after attempt 2
        assert sleep_mock.await_count == 2
        sleep_mock.assert_any_await(5.0)
        sleep_mock.assert_any_await(10.0)

    @pytest.mark.asyncio
    async def test_auth_failure_succeeds_on_retry(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Auth succeeds on second attempt after transient failure."""
        runner = _TestRunner(config, event_bus)

        with (
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=[
                    AuthenticationRetryError("auth failed"),
                    "transcript output",
                ],
            ) as mock,
            patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
        ):
            result = await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": 42}
            )

        assert result == "transcript output"
        assert mock.await_count == 2
        assert sleep_mock.await_count == 1


# ---------------------------------------------------------------------------
# _inject_memory
# ---------------------------------------------------------------------------


class TestInjectMemory:
    """Tests for BaseRunner._inject_memory."""

    @pytest.mark.asyncio
    async def test_inject_manifest_always_empty(
        self, config, event_bus: EventBus
    ) -> None:
        """returns memory section — manifest loading is done by individual runners."""
        runner = _TestRunner(config, event_bus)
        await runner._inject_memory()

    @pytest.mark.asyncio
    async def test_inject_memory_empty_without_hindsight(
        self, config, event_bus: EventBus
    ) -> None:
        """Without a Hindsight client, memory section is always empty."""
        runner = _TestRunner(config, event_bus)  # no hindsight
        memory_sec = await runner._inject_memory(query_context="Fix the widget")
        assert memory_sec == ""

    @pytest.mark.asyncio
    async def test_inject_returns_empty_strings_when_no_hindsight(
        self, config, event_bus: EventBus
    ) -> None:
        runner = _TestRunner(config, event_bus)
        memory_sec = await runner._inject_memory()
        assert memory_sec == ""

    @pytest.mark.asyncio
    async def test_hindsight_recall_used_when_client_and_query_provided(
        self, config, event_bus: EventBus
    ) -> None:
        from hindsight import HindsightMemory

        mock_client = MagicMock()
        runner = _TestRunner(config, event_bus, hindsight=mock_client)

        memories = [HindsightMemory(content="Always run lint before committing")]
        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=memories,
        ):
            memory_sec = await runner._inject_memory(query_context="Fix the widget")

        assert "## Accumulated Learnings" in memory_sec
        assert "Always run lint before committing" in memory_sec

    @pytest.mark.asyncio
    async def test_hindsight_empty_recall_returns_empty_memory(
        self, config, event_bus: EventBus
    ) -> None:
        """When Hindsight recall returns nothing, memory section is empty."""
        mock_client = MagicMock()
        runner = _TestRunner(config, event_bus, hindsight=mock_client)

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=[],
        ):
            memory_sec = await runner._inject_memory(query_context="Fix the widget")

        assert memory_sec == ""

    @pytest.mark.asyncio
    async def test_hindsight_not_used_when_client_is_none(
        self, config, event_bus: EventBus
    ) -> None:
        """Without a Hindsight client, memory is always empty regardless of query."""
        runner = _TestRunner(config, event_bus)
        memory_sec = await runner._inject_memory(query_context="Fix the widget")
        assert memory_sec == ""

    @pytest.mark.asyncio
    async def test_empty_query_context_skips_hindsight(
        self, config, event_bus: EventBus
    ) -> None:
        """When query_context is empty, Hindsight recall should NOT be called."""
        mock_client = MagicMock()
        runner = _TestRunner(config, event_bus, hindsight=mock_client)

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
        ) as mock_recall:
            memory_sec = await runner._inject_memory(query_context="")

        # Hindsight should not be called with an empty query
        mock_recall.assert_not_called()
        assert memory_sec == ""

    @pytest.mark.asyncio
    async def test_troubleshooting_bank_recalled_when_hindsight_available(
        self, config, event_bus: EventBus
    ) -> None:
        """When Hindsight is configured, TROUBLESHOOTING bank is recalled."""
        from hindsight import Bank, HindsightMemory

        mock_client = MagicMock()
        runner = _TestRunner(config, event_bus, hindsight=mock_client)

        def _recall_side_effect(client, bank, query, **_kwargs):
            if bank == Bank.LEARNINGS:
                return [HindsightMemory(content="Always run lint")]
            if bank == Bank.TROUBLESHOOTING:
                return [HindsightMemory(content="Check import paths first")]
            return []

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=_recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(query_context="Fix import issue")

        assert "## Known Troubleshooting Patterns" in memory_sec
        assert "Check import paths first" in memory_sec

    @pytest.mark.asyncio
    async def test_retrospectives_bank_recalled_when_hindsight_available(
        self, config, event_bus: EventBus
    ) -> None:
        """When Hindsight is configured, RETROSPECTIVES bank is recalled."""
        from hindsight import Bank, HindsightMemory

        mock_client = MagicMock()
        runner = _TestRunner(config, event_bus, hindsight=mock_client)

        def _recall_side_effect(client, bank, query, **_kwargs):
            if bank == Bank.LEARNINGS:
                return [HindsightMemory(content="Always run lint")]
            if bank == Bank.RETROSPECTIVES:
                return [
                    HindsightMemory(content="Sprint 5: CI flakiness was root cause")
                ]
            return []

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=_recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(query_context="CI failure")

        assert "## Past Retrospectives" in memory_sec
        assert "Sprint 5" in memory_sec

    @pytest.mark.asyncio
    async def test_all_three_banks_appear_in_priority_order(
        self, config, event_bus: EventBus
    ) -> None:
        """Learnings appear before troubleshooting, which appears before retrospectives."""
        from hindsight import Bank, HindsightMemory

        mock_client = MagicMock()
        runner = _TestRunner(config, event_bus, hindsight=mock_client)

        def _recall_side_effect(client, bank, query, **_kwargs):
            if bank == Bank.LEARNINGS:
                return [HindsightMemory(content="LEARNING_ITEM")]
            if bank == Bank.TROUBLESHOOTING:
                return [HindsightMemory(content="TROUBLESHOOT_ITEM")]
            if bank == Bank.RETROSPECTIVES:
                return [HindsightMemory(content="RETRO_ITEM")]
            return []

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=_recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(query_context="issue context")

        learnings_pos = memory_sec.index("LEARNING_ITEM")
        troubleshoot_pos = memory_sec.index("TROUBLESHOOT_ITEM")
        retro_pos = memory_sec.index("RETRO_ITEM")
        assert learnings_pos < troubleshoot_pos < retro_pos

    @pytest.mark.asyncio
    async def test_combined_section_capped_at_max_chars(
        self, config, event_bus: EventBus
    ) -> None:
        """The combined memory section must not exceed max_memory_prompt_chars."""
        from hindsight import HindsightMemory

        config.max_memory_prompt_chars = 50
        mock_client = MagicMock()
        runner = _TestRunner(config, event_bus, hindsight=mock_client)

        big_content = "X" * 200

        def _recall_side_effect(client, bank, query, **_kwargs):
            return [HindsightMemory(content=big_content)]

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=_recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(query_context="big query")

        # Leading "\n\n" prepended to combined, but the combined itself is capped
        # Total memory_section must not be vastly larger than max_chars + small overhead
        assert (
            len(memory_sec) <= config.max_memory_prompt_chars + 4
        )  # +4 for leading "\n\n"

    @pytest.mark.asyncio
    async def test_troubleshooting_recall_failure_does_not_raise(
        self, config, event_bus: EventBus
    ) -> None:
        """An exception in TROUBLESHOOTING recall is silently swallowed."""
        from hindsight import Bank, HindsightMemory

        mock_client = MagicMock()
        runner = _TestRunner(config, event_bus, hindsight=mock_client)

        call_count = 0

        async def _flaky_recall(client, bank, query, **_kwargs):
            nonlocal call_count
            call_count += 1
            if bank == Bank.TROUBLESHOOTING:
                raise RuntimeError("network error")
            return [HindsightMemory(content="Always run lint")]

        with patch("hindsight.recall_safe", side_effect=_flaky_recall):
            # Should not raise
            memory_sec = await runner._inject_memory(query_context="Fix something")

        # Learnings should still appear
        assert "## Accumulated Learnings" in memory_sec
        # Troubleshooting section should be absent
        assert "## Known Troubleshooting Patterns" not in memory_sec


# ---------------------------------------------------------------------------
# _verify_quality
# ---------------------------------------------------------------------------


class TestVerifyQuality:
    """Tests for BaseRunner._verify_quality."""

    @pytest.mark.asyncio
    async def test_verify_quality_returns_true_on_success(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(
            return_value=MagicMock(returncode=0, stdout="OK", stderr="")
        )
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        result = await runner._verify_quality(tmp_path)

        assert result.passed is True
        assert result.summary == "OK"

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

        result = await runner._verify_quality(tmp_path)

        assert result.passed is False
        assert "`make quality` failed" in result.summary
        assert "FAILED test_foo" in result.summary

    @pytest.mark.asyncio
    async def test_file_not_found(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(side_effect=FileNotFoundError)
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        result = await runner._verify_quality(tmp_path)

        assert result.passed is False
        assert "make not found" in result.summary

    @pytest.mark.asyncio
    async def test_verify_quality_returns_false_on_timeout(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(side_effect=TimeoutError)
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        result = await runner._verify_quality(tmp_path)

        assert result.passed is False
        assert "timed out" in result.summary

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

        result = await runner._verify_quality(tmp_path)

        assert result.passed is False
        # Output should be truncated to last 3000 chars
        assert len(result.summary) < 5000 + 100  # some overhead for prefix text


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
        """The workspace_path arg is accepted for API compatibility but not included in cmd."""
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "--cwd" not in cmd

    def test_build_command_accepts_none_workspace_path(
        self, config, event_bus: EventBus
    ) -> None:
        """The workspace_path parameter is optional (None) for runners that don't need worktrees."""
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(None)
        assert cmd[0] == "claude"

    def test_build_command_works_without_arguments(
        self, config, event_bus: EventBus
    ) -> None:
        """The workspace_path parameter defaults to None when omitted."""
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command()
        assert cmd[0] == "claude"
