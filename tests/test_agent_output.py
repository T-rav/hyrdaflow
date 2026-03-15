"""Tests for agent — output."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, patch

import pytest

from agent import AgentRunner
from events import EventBus, EventType
from models import LoopResult, Task, WorkerStatus
from tests.conftest import WorkerResultFactory
from tests.helpers import ConfigFactory, make_proc


@pytest.fixture
def agent_task() -> Task:
    return Task(
        id=42,
        title="Fix the frobnicator",
        body="The frobnicator is broken. Please fix it.",
        tags=["ready"],
        comments=[],
        source_url="https://github.com/test-org/test-repo/issues/42",
    )


# ---------------------------------------------------------------------------
# AgentRunner._verify_result
# ---------------------------------------------------------------------------


class TestVerifyResult:
    """Tests for AgentRunner._verify_result."""

    @pytest.mark.asyncio
    async def test_verify_returns_false_when_no_commits(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_verify_result should return (False, ...) when commit count is 0."""
        runner = AgentRunner(config, event_bus)

        with patch.object(
            runner, "_count_commits", new_callable=AsyncMock, return_value=0
        ):
            result = await runner._verify_result(tmp_path, "agent/issue-42")

        assert result.passed is False
        assert "commit" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_verify_runs_make_quality(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_verify_result should run make quality and return OK on success."""
        runner = AgentRunner(config, event_bus)

        quality_proc = make_proc(returncode=0, stdout=b"All checks passed")

        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch(
                "asyncio.create_subprocess_exec",
                return_value=quality_proc,
            ) as mock_exec,
        ):
            result = await runner._verify_result(tmp_path, "agent/issue-42")

        assert result.passed is True
        assert result.summary == "OK"
        # Should call make quality exactly once
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert "make" in call_args
        assert "quality" in call_args

    @pytest.mark.asyncio
    async def test_verify_returns_false_when_quality_fails(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_verify_result should return (False, ...) when make quality exits non-zero."""
        runner = AgentRunner(config, event_bus)

        fail_proc = make_proc(
            returncode=1, stdout=b"FAILED test_foo.py::test_bar", stderr=b""
        )

        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch("asyncio.create_subprocess_exec", return_value=fail_proc),
        ):
            result = await runner._verify_result(tmp_path, "agent/issue-42")

        assert result.passed is False
        assert "make quality" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_verify_includes_output_on_failure(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_verify_result should include the last 3000 chars of output on failure."""
        runner = AgentRunner(config, event_bus)

        fail_proc = make_proc(
            returncode=1,
            stdout=b"error: type mismatch on line 42",
            stderr=b"pyright found 1 error",
        )

        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch("asyncio.create_subprocess_exec", return_value=fail_proc),
        ):
            result = await runner._verify_result(tmp_path, "agent/issue-42")

        assert result.passed is False
        assert "type mismatch" in result.summary
        assert "pyright" in result.summary

    @pytest.mark.asyncio
    async def test_verify_returns_false_when_make_not_found(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_verify_result should handle FileNotFoundError from missing 'make'."""
        runner = AgentRunner(config, event_bus)

        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError),
        ):
            result = await runner._verify_result(tmp_path, "agent/issue-42")

        assert result.passed is False
        assert "make" in result.summary.lower()


# ---------------------------------------------------------------------------
# AgentRunner._count_commits
# ---------------------------------------------------------------------------


class TestCountCommits:
    """Tests for AgentRunner._count_commits."""

    @pytest.mark.asyncio
    async def test_count_commits_returns_parsed_count(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_count_commits should return the integer from git rev-list output."""
        runner = AgentRunner(config, event_bus)
        mock_proc = make_proc(returncode=0, stdout=b"3\n")

        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)
        ) as mock_exec:
            result = await runner._count_commits(tmp_path, "agent/issue-42")

        assert result == 3
        mock_exec.assert_awaited_once_with(
            "git",
            "rev-list",
            "--count",
            "origin/main..agent/issue-42",
            cwd=str(tmp_path),
            stdin=None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=None,
        )

    @pytest.mark.asyncio
    async def test_count_commits_parses_multi_digit(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_count_commits should correctly parse multi-digit counts."""
        runner = AgentRunner(config, event_bus)
        mock_proc = make_proc(returncode=0, stdout=b"15\n")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await runner._count_commits(tmp_path, "agent/issue-42")

        assert result == 15

    @pytest.mark.asyncio
    async def test_count_commits_returns_zero_on_empty_stdout(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_count_commits should return 0 when stdout is empty (ValueError)."""
        runner = AgentRunner(config, event_bus)
        mock_proc = make_proc(returncode=0, stdout=b"")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await runner._count_commits(tmp_path, "agent/issue-42")

        assert result == 0

    @pytest.mark.asyncio
    async def test_count_commits_returns_zero_on_nonzero_exit(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_count_commits should return 0 when git exits with non-zero code."""
        runner = AgentRunner(config, event_bus)
        mock_proc = make_proc(returncode=1, stdout=b"")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await runner._count_commits(tmp_path, "agent/issue-42")

        assert result == 0

    @pytest.mark.asyncio
    async def test_count_commits_returns_zero_on_file_not_found(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_count_commits should return 0 when git binary is not found."""
        runner = AgentRunner(config, event_bus)

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await runner._count_commits(tmp_path, "agent/issue-42")

        assert result == 0


# ---------------------------------------------------------------------------
# AgentRunner._build_quality_fix_prompt
# ---------------------------------------------------------------------------


class TestBuildQualityFixPrompt:
    """Tests for AgentRunner._build_quality_fix_prompt."""

    def test_prompt_includes_error_output(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Fix prompt should include the quality error output."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_quality_fix_prompt(agent_task, "ruff: error E501", 1)
        assert "ruff: error E501" in prompt

    def test_prompt_includes_attempt_number(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Fix prompt should include the attempt number."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_quality_fix_prompt(agent_task, "error", 3)
        assert "3" in prompt

    def test_prompt_includes_issue_number(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Fix prompt should reference the issue number."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_quality_fix_prompt(agent_task, "error", 1)
        assert str(agent_task.id) in prompt

    def test_prompt_instructs_make_quality(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Fix prompt should instruct running make quality."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_quality_fix_prompt(agent_task, "error", 1)
        assert "make quality" in prompt

    def test_prompt_truncates_long_error_output(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Fix prompt should truncate error output to last 3000 chars."""
        runner = AgentRunner(config, event_bus)
        long_error = "x" * 5000
        prompt = runner._build_quality_fix_prompt(agent_task, long_error, 1)
        # The prompt should contain at most 3000 chars of the error
        assert "x" * 3000 in prompt
        assert "x" * 5000 not in prompt


# ---------------------------------------------------------------------------
# AgentRunner._run_quality_fix_loop
# ---------------------------------------------------------------------------


class TestQualityFixLoop:
    """Tests for AgentRunner._run_quality_fix_loop."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """Fix loop should succeed on first attempt when quality passes."""
        runner = AgentRunner(config, event_bus)

        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="fix output"
            ),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=True, summary="OK"),
            ),
        ):
            result = await runner._run_quality_fix_loop(
                agent_task, tmp_path, "agent/issue-42", "initial error", worker_id=0
            )

        assert result.passed is True
        assert result.summary == "OK"
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """Fix loop should succeed when second attempt passes quality."""
        runner = AgentRunner(config, event_bus)

        verify_results = iter(
            [
                LoopResult(passed=False, summary="still failing"),
                LoopResult(passed=True, summary="OK"),
            ]
        )

        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="fix output"
            ),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                side_effect=lambda *a: next(verify_results),
            ),
        ):
            result = await runner._run_quality_fix_loop(
                agent_task, tmp_path, "agent/issue-42", "initial error", worker_id=0
            )

        assert result.passed is True
        assert result.summary == "OK"
        assert result.attempts == 2

    @pytest.mark.asyncio
    async def test_fails_after_max_attempts(
        self, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """Fix loop should fail after exhausting max_quality_fix_attempts."""
        cfg = ConfigFactory.create(
            max_quality_fix_attempts=3,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        runner = AgentRunner(cfg, event_bus)

        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="fix output"
            ),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=False, summary="still broken"),
            ),
        ):
            result = await runner._run_quality_fix_loop(
                agent_task, tmp_path, "agent/issue-42", "initial error", worker_id=0
            )

        assert result.passed is False
        assert "still broken" in result.summary
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_emits_quality_fix_status_events(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """Fix loop should emit QUALITY_FIX status events."""
        runner = AgentRunner(config, event_bus)
        queue = event_bus.subscribe()

        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="fix output"
            ),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=True, summary="OK"),
            ),
        ):
            await runner._run_quality_fix_loop(
                agent_task, tmp_path, "agent/issue-42", "error", worker_id=0
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        worker_updates = [e for e in events if e.type == EventType.WORKER_UPDATE]
        statuses = [e.data.get("status") for e in worker_updates]
        assert WorkerStatus.QUALITY_FIX.value in statuses

    @pytest.mark.asyncio
    async def test_zero_max_attempts_returns_immediately(
        self, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """Fix loop with 0 max attempts should return failure without executing."""
        cfg = ConfigFactory.create(
            max_quality_fix_attempts=0,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        runner = AgentRunner(cfg, event_bus)

        with (
            patch.object(runner, "_execute", new_callable=AsyncMock) as exec_mock,
        ):
            result = await runner._run_quality_fix_loop(
                agent_task, tmp_path, "agent/issue-42", "error", worker_id=0
            )

        assert result.passed is False
        assert result.attempts == 0
        exec_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# AgentRunner._save_transcript
# ---------------------------------------------------------------------------


class TestSaveTranscript:
    """Tests for AgentRunner._save_transcript."""

    def test_save_transcript_writes_to_hydraflow_logs(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_save_transcript should write to <repo_root>/.hydraflow-logs/issue-N.txt."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = AgentRunner(config, event_bus)

        result = WorkerResultFactory.create(
            issue_number=42,
            branch="agent/issue-42",
            transcript="This is the agent transcript",
        )
        runner._save_transcript("issue", result.issue_number, result.transcript)

        expected_path = config.repo_root / ".hydraflow" / "logs" / "issue-42.txt"
        assert expected_path.exists()
        assert expected_path.read_text() == "This is the agent transcript"

    def test_save_transcript_creates_log_directory(
        self, config, event_bus: EventBus
    ) -> None:
        """_save_transcript should create .hydraflow/logs/ if it does not exist."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert not log_dir.exists()

        runner = AgentRunner(config, event_bus)
        result = WorkerResultFactory.create(
            issue_number=7,
            branch="agent/issue-7",
            transcript="output",
        )
        runner._save_transcript("issue", result.issue_number, result.transcript)

        assert log_dir.is_dir()

    def test_save_transcript_uses_issue_number_in_filename(
        self, config, event_bus: EventBus
    ) -> None:
        """_save_transcript filename should be issue-<number>.txt."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = AgentRunner(config, event_bus)

        result = WorkerResultFactory.create(
            issue_number=123,
            branch="agent/issue-123",
            transcript="content",
        )
        runner._save_transcript("issue", result.issue_number, result.transcript)

        log_file = config.repo_root / ".hydraflow" / "logs" / "issue-123.txt"
        assert log_file.exists()

    def test_save_transcript_handles_oserror(
        self, config, event_bus: EventBus, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_save_transcript should swallow OSError and log a warning."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = AgentRunner(config, event_bus)
        result = WorkerResultFactory.create(
            issue_number=42,
            branch="agent/issue-42",
            transcript="content",
        )

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            runner._save_transcript(
                "issue", result.issue_number, result.transcript
            )  # should not raise

        assert "Could not save transcript" in caplog.text


# ---------------------------------------------------------------------------
# AgentRunner.run — _save_transcript OSError defense-in-depth
# ---------------------------------------------------------------------------


class TestRunSaveTranscriptOSError:
    """Tests verifying that an OSError from _save_transcript does not crash run()."""

    @pytest.mark.asyncio
    async def test_run_returns_result_when_save_transcript_raises_os_error(
        self,
        config,
        event_bus: EventBus,
        agent_task,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """run() should return a valid WorkerResult even if _save_transcript raises OSError."""
        runner = AgentRunner(config, event_bus)

        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="transcript"
            ),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=True, summary="OK"),
            ),
            patch.object(
                runner,
                "_count_commits",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch.object(
                runner,
                "_save_transcript",
                side_effect=OSError("disk full"),
            ),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is True
        assert result.issue_number == agent_task.id
        assert result.branch == "agent/issue-42"
        assert result.commits == 2
        assert "Failed to save transcript" in caplog.text

    @pytest.mark.asyncio
    async def test_run_returns_failure_result_when_save_transcript_raises_after_exception(
        self,
        config,
        event_bus: EventBus,
        agent_task,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """run() should return failure result even if _save_transcript raises after an agent error."""
        runner = AgentRunner(config, event_bus)

        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=RuntimeError("agent crashed"),
            ),
            patch.object(
                runner,
                "_save_transcript",
                side_effect=OSError("disk full"),
            ),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is False
        assert "agent crashed" in (result.error or "")
        assert "Failed to save transcript" in caplog.text


# ---------------------------------------------------------------------------
# AgentRunner — event publishing
# ---------------------------------------------------------------------------


class TestEventPublishing:
    """Tests verifying that the correct events are published during a run."""

    @pytest.mark.asyncio
    async def test_run_emits_running_status_at_start(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should publish WORKER_UPDATE with status=running before executing."""
        runner = AgentRunner(config, event_bus)
        received_events = []

        # Subscribe BEFORE the run
        queue = event_bus.subscribe()

        with (
            patch.object(runner, "_execute", new_callable=AsyncMock, return_value=""),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=True, summary="OK"),
            ),
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(runner, "_save_transcript"),
        ):
            await runner.run(agent_task, tmp_path, "agent/issue-42")

        while not queue.empty():
            received_events.append(queue.get_nowait())

        worker_updates = [
            e for e in received_events if e.type == EventType.WORKER_UPDATE
        ]
        statuses = [e.data.get("status") for e in worker_updates]
        assert WorkerStatus.RUNNING.value in statuses

    @pytest.mark.asyncio
    async def test_run_emits_done_status_on_success(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should publish WORKER_UPDATE with status=done on a successful run."""
        runner = AgentRunner(config, event_bus)
        queue = event_bus.subscribe()

        with (
            patch.object(runner, "_execute", new_callable=AsyncMock, return_value=""),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=True, summary="OK"),
            ),
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(runner, "_save_transcript"),
        ):
            await runner.run(agent_task, tmp_path, "agent/issue-42")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        worker_updates = [e for e in events if e.type == EventType.WORKER_UPDATE]
        statuses = [e.data.get("status") for e in worker_updates]
        assert WorkerStatus.DONE.value in statuses

    @pytest.mark.asyncio
    async def test_run_emits_failed_status_on_exception(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should publish WORKER_UPDATE with status=failed when an exception occurs."""
        runner = AgentRunner(config, event_bus)
        queue = event_bus.subscribe()

        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch.object(runner, "_save_transcript"),
        ):
            await runner.run(agent_task, tmp_path, "agent/issue-42")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        worker_updates = [e for e in events if e.type == EventType.WORKER_UPDATE]
        statuses = [e.data.get("status") for e in worker_updates]
        assert WorkerStatus.FAILED.value in statuses

    @pytest.mark.asyncio
    async def test_run_emits_testing_status_during_verification(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should publish WORKER_UPDATE with status=testing before verifying."""
        runner = AgentRunner(config, event_bus)
        queue = event_bus.subscribe()

        with (
            patch.object(runner, "_execute", new_callable=AsyncMock, return_value=""),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=True, summary="OK"),
            ),
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(runner, "_save_transcript"),
        ):
            await runner.run(agent_task, tmp_path, "agent/issue-42")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        worker_updates = [e for e in events if e.type == EventType.WORKER_UPDATE]
        statuses = [e.data.get("status") for e in worker_updates]
        assert WorkerStatus.TESTING.value in statuses

    @pytest.mark.asyncio
    async def test_run_events_include_correct_issue_number(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """WORKER_UPDATE events should carry the correct issue number."""
        runner = AgentRunner(config, event_bus)
        queue = event_bus.subscribe()

        with (
            patch.object(runner, "_execute", new_callable=AsyncMock, return_value=""),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=True, summary="OK"),
            ),
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(runner, "_save_transcript"),
        ):
            await runner.run(agent_task, tmp_path, "agent/issue-42", worker_id=3)

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        worker_updates = [e for e in events if e.type == EventType.WORKER_UPDATE]
        for event in worker_updates:
            assert event.data.get("issue") == agent_task.id
            assert event.data.get("worker") == 3

    @pytest.mark.asyncio
    async def test_worker_update_events_include_implementer_role(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """WORKER_UPDATE events should carry role='implementer'."""
        runner = AgentRunner(config, event_bus)
        queue = event_bus.subscribe()

        with (
            patch.object(runner, "_execute", new_callable=AsyncMock, return_value=""),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=True, summary="OK"),
            ),
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(runner, "_save_transcript"),
        ):
            await runner.run(agent_task, tmp_path, "agent/issue-42")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        worker_updates = [e for e in events if e.type == EventType.WORKER_UPDATE]
        assert len(worker_updates) > 0
        for event in worker_updates:
            assert event.data.get("role") == "implementer"

    @pytest.mark.asyncio
    async def test_dry_run_emits_running_and_done_events(
        self, dry_config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """In dry-run mode, run should still emit RUNNING and DONE status events."""
        runner = AgentRunner(dry_config, event_bus)
        queue = event_bus.subscribe()

        await runner.run(agent_task, tmp_path, "agent/issue-42")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        worker_updates = [e for e in events if e.type == EventType.WORKER_UPDATE]
        statuses = [e.data.get("status") for e in worker_updates]
        assert WorkerStatus.RUNNING.value in statuses
        assert WorkerStatus.DONE.value in statuses

    @pytest.mark.asyncio
    async def test_dry_run_events_include_implementer_role(
        self, dry_config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """In dry-run mode, WORKER_UPDATE events should still carry role='implementer'."""
        runner = AgentRunner(dry_config, event_bus)
        queue = event_bus.subscribe()

        await runner.run(agent_task, tmp_path, "agent/issue-42")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        worker_updates = [e for e in events if e.type == EventType.WORKER_UPDATE]
        assert len(worker_updates) > 0
        for event in worker_updates:
            assert event.data.get("role") == "implementer"


# ---------------------------------------------------------------------------
# _build_plan_section — extracted from _build_prompt_with_stats
# ---------------------------------------------------------------------------

from prompt_builder import PromptBuilder


class TestBuildPlanSection:
    """Tests for the _build_plan_section helper extracted from _build_prompt_with_stats."""

    def test_returns_empty_when_no_plan(self, config, event_bus) -> None:
        runner = AgentRunner(config, event_bus)
        builder = PromptBuilder()
        task = Task(id=99, title="Test", body="body", comments=[], tags=[])
        section = runner._build_plan_section(task, builder)
        assert section == ""

    def test_returns_plan_from_comment(self, config, event_bus) -> None:
        runner = AgentRunner(config, event_bus)
        builder = PromptBuilder()
        plan_text = "## Implementation Plan\n\nDo the thing."
        task = Task(
            id=99,
            title="Test",
            body="body",
            comments=[plan_text],
            tags=[],
        )
        section = runner._build_plan_section(task, builder)
        assert "## Implementation Plan" in section
        assert "Do the thing" in section


# ---------------------------------------------------------------------------
# _build_history_sections — extracted from _build_prompt_with_stats
# ---------------------------------------------------------------------------


class TestBuildHistorySections:
    """Tests for the _build_history_sections helper."""

    def test_returns_empty_sections_with_no_data(self, config, event_bus) -> None:
        runner = AgentRunner(config, event_bus)
        builder = PromptBuilder()
        task = Task(id=99, title="Test", body="body", comments=[], tags=[])
        review, failure, comments = runner._build_history_sections(task, builder)
        assert review == ""
        assert failure == ""
        assert comments == ""

    def test_includes_review_feedback(self, config, event_bus) -> None:
        runner = AgentRunner(config, event_bus)
        builder = PromptBuilder()
        task = Task(id=99, title="Test", body="body", comments=[], tags=[])
        review, _, _ = runner._build_history_sections(
            task, builder, review_feedback="Fix the bug"
        )
        assert "Review Feedback" in review
        assert "Fix the bug" in review

    def test_includes_prior_failure(self, config, event_bus) -> None:
        runner = AgentRunner(config, event_bus)
        builder = PromptBuilder()
        task = Task(id=99, title="Test", body="body", comments=[], tags=[])
        _, failure, _ = runner._build_history_sections(
            task, builder, prior_failure="TypeError: bad"
        )
        assert "Prior Attempt Failure" in failure
        assert "TypeError: bad" in failure

    def test_includes_discussion_comments(self, config, event_bus) -> None:
        runner = AgentRunner(config, event_bus)
        builder = PromptBuilder()
        task = Task(
            id=99,
            title="Test",
            body="body",
            comments=["user comment one"],
            tags=[],
        )
        _, _, comments = runner._build_history_sections(task, builder)
        assert "Discussion" in comments
        assert "user comment one" in comments


# ---------------------------------------------------------------------------
# _build_insight_sections — extracted from _build_prompt_with_stats
# ---------------------------------------------------------------------------


class TestBuildInsightSections:
    """Tests for the _build_insight_sections helper."""

    def test_returns_empty_sections_when_no_insights(self, config, event_bus) -> None:
        runner = AgentRunner(config, event_bus)
        builder = PromptBuilder()
        feedback, escalation, escalations = runner._build_insight_sections(builder)
        assert feedback == ""
        assert escalation == ""
        assert escalations == []
