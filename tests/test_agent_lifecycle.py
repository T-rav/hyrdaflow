"""Tests for agent — lifecycle."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent import AgentRunner
from events import EventBus
from models import LoopResult, Task
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


@pytest.fixture
def agent_task() -> Task:
    return TaskFactory.create()


# ---------------------------------------------------------------------------
# AgentRunner.run — success path
# ---------------------------------------------------------------------------


class TestRunSuccess:
    @pytest.mark.asyncio
    async def test_run_success_returns_worker_result_with_success_true(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should return a WorkerResult with success=True on the happy path."""
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
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is True
        assert result.issue_number == agent_task.id
        assert result.branch == "agent/issue-42"
        assert result.commits == 2
        assert result.transcript == "transcript"

    @pytest.mark.asyncio
    async def test_run_success_sets_duration(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should record a positive duration_seconds."""
        runner = AgentRunner(config, event_bus)

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
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.duration_seconds >= 0


# ---------------------------------------------------------------------------
# AgentRunner._force_commit_uncommitted
# ---------------------------------------------------------------------------


class TestForceCommitUncommitted:
    @pytest.mark.asyncio
    async def test_force_commit_creates_commit_when_dirty(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Uncommitted changes should be staged and committed via host git."""
        runner = AgentRunner(config, event_bus)
        task = TaskFactory.create(id=99, title="Fix the widget")

        call_count = 0

        async def fake_run_simple(cmd, *, cwd=None, timeout=120.0, **kw):
            nonlocal call_count
            call_count += 1
            from execution import SimpleResult

            if "status" in cmd:
                return SimpleResult(stdout=" M src/foo.py", stderr="", returncode=0)
            return SimpleResult(stdout="", stderr="", returncode=0)

        mock_host = MagicMock()
        mock_host.run_simple = AsyncMock(side_effect=fake_run_simple)

        with patch("execution.get_default_runner", return_value=mock_host):
            result = await runner._force_commit_uncommitted(task, tmp_path)

        assert result is True
        assert call_count == 3  # status, add, commit

    @pytest.mark.asyncio
    async def test_force_commit_noop_when_clean(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """No commit should be created when working tree is clean."""
        runner = AgentRunner(config, event_bus)
        task = TaskFactory.create(id=99, title="Fix the widget")

        async def fake_run_simple(cmd, *, cwd=None, timeout=120.0, **kw):
            from execution import SimpleResult

            return SimpleResult(stdout="", stderr="", returncode=0)

        mock_host = MagicMock()
        mock_host.run_simple = AsyncMock(side_effect=fake_run_simple)

        with patch("execution.get_default_runner", return_value=mock_host):
            result = await runner._force_commit_uncommitted(task, tmp_path)

        assert result is False
        assert mock_host.run_simple.await_count == 1  # status

    @pytest.mark.asyncio
    async def test_force_commit_returns_false_when_git_add_fails(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Non-zero returncode from git add should return False."""
        runner = AgentRunner(config, event_bus)
        task = TaskFactory.create(id=99, title="Fix the widget")

        async def fake_run_simple(cmd, *, cwd=None, timeout=120.0, **kw):
            from execution import SimpleResult

            if "status" in cmd:
                return SimpleResult(stdout=" M src/foo.py", stderr="", returncode=0)
            if "add" in cmd:
                return SimpleResult(stdout="", stderr="fatal: error", returncode=128)
            return SimpleResult(stdout="", stderr="", returncode=0)

        mock_host = MagicMock()
        mock_host.run_simple = AsyncMock(side_effect=fake_run_simple)

        with patch("execution.get_default_runner", return_value=mock_host):
            result = await runner._force_commit_uncommitted(task, tmp_path)

        assert result is False

    @pytest.mark.asyncio
    async def test_force_commit_returns_false_when_git_commit_fails(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Non-zero returncode from git commit should return False."""
        runner = AgentRunner(config, event_bus)
        task = TaskFactory.create(id=99, title="Fix the widget")

        async def fake_run_simple(cmd, *, cwd=None, timeout=120.0, **kw):
            from execution import SimpleResult

            if "status" in cmd:
                return SimpleResult(stdout=" M src/foo.py", stderr="", returncode=0)
            if "commit" in cmd:
                return SimpleResult(stdout="", stderr="nothing to commit", returncode=1)
            return SimpleResult(stdout="", stderr="", returncode=0)

        mock_host = MagicMock()
        mock_host.run_simple = AsyncMock(side_effect=fake_run_simple)

        with patch("execution.get_default_runner", return_value=mock_host):
            result = await runner._force_commit_uncommitted(task, tmp_path)

        assert result is False

    @pytest.mark.asyncio
    async def test_force_commit_handles_error_gracefully(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Errors in git commands should not crash, just return False."""
        runner = AgentRunner(config, event_bus)
        task = TaskFactory.create(id=99, title="Fix the widget")

        mock_host = MagicMock()
        mock_host.run_simple = AsyncMock(side_effect=OSError("git broke"))

        with patch("execution.get_default_runner", return_value=mock_host):
            result = await runner._force_commit_uncommitted(task, tmp_path)

        assert result is False


class TestForceCommitE2E:
    """End-to-end tests using real git repos to verify the salvage-commit flow."""

    @pytest.mark.asyncio
    async def test_force_commit_clean_repo_no_corruption(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """No corruption + no dirty files = no commit, returns False."""
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", repo], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        (repo / "README.md").write_text("# Hello")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "Initial commit"],
            check=True,
            capture_output=True,
        )

        runner = AgentRunner(config, event_bus)
        task = TaskFactory.create(id=42, title="Fix the bug")

        committed = await runner._force_commit_uncommitted(task, repo)

        assert committed is False

    @pytest.mark.asyncio
    async def test_force_commit_dirty_without_corruption(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Dirty files without Docker corruption should still be committed."""
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", repo], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        (repo / "README.md").write_text("# Hello")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "Initial commit"],
            check=True,
            capture_output=True,
        )

        # Add a dirty file (no Docker corruption)
        (repo / "new_file.py").write_text("print('hello')\n")

        runner = AgentRunner(config, event_bus)
        task = TaskFactory.create(id=42, title="Add greeting")

        committed = await runner._force_commit_uncommitted(task, repo)

        assert committed is True

        log = subprocess.run(
            ["git", "-C", str(repo), "log", "--oneline"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Add greeting" in log.stdout


# ---------------------------------------------------------------------------
# AgentRunner.run — failure paths
# ---------------------------------------------------------------------------


class TestRunFailure:
    @pytest.mark.asyncio
    async def test_run_failure_when_verify_returns_false_and_fix_loop_fails(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should return success=False when quality fix loop also fails."""
        runner = AgentRunner(config, event_bus)

        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="output"
            ),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=False, summary="Quality failed"),
            ),
            patch.object(
                runner,
                "_run_quality_fix_loop",
                new_callable=AsyncMock,
                return_value=LoopResult(
                    passed=False, summary="Still failing", attempts=2
                ),
            ),
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is False
        assert result.error == "Still failing"
        assert result.quality_fix_attempts == 2

    @pytest.mark.asyncio
    async def test_run_skips_fix_loop_when_no_commits(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should not invoke the fix loop when there are no commits."""
        runner = AgentRunner(config, event_bus)

        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="output"
            ),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(
                    passed=False, summary="No commits found on branch"
                ),
            ),
            patch.object(
                runner,
                "_run_quality_fix_loop",
                new_callable=AsyncMock,
            ) as fix_mock,
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=0
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is False
        fix_mock.assert_not_awaited()


class TestPreQualityReviewLoop:
    @pytest.mark.asyncio
    async def test_skips_when_no_commits(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner, "_count_commits", new_callable=AsyncMock, return_value=0
        ):
            result = await runner._run_pre_quality_review_loop(
                agent_task, tmp_path, "agent/issue-42", worker_id=1
            )
        assert result.passed is True
        assert result.attempts == 0
        assert "Skipped" in result.summary

    @pytest.mark.asyncio
    async def test_retries_bounded_by_config(
        self, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        cfg = ConfigFactory.create(
            max_pre_quality_review_attempts=2,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        runner = AgentRunner(cfg, event_bus)
        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                return_value="PRE_QUALITY_REVIEW_RESULT: RETRY\nRUN_TOOL_RESULT: RETRY",
            ) as execute_mock,
        ):
            result = await runner._run_pre_quality_review_loop(
                agent_task, tmp_path, "agent/issue-42", worker_id=1
            )
        assert result.passed is False
        assert result.attempts == 2
        assert execute_mock.await_count == 4

    @pytest.mark.asyncio
    async def test_run_success_when_fix_loop_succeeds(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should return success=True when the fix loop recovers."""
        runner = AgentRunner(config, event_bus)

        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="output"
            ),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=False, summary="Quality failed"),
            ),
            patch.object(
                runner,
                "_run_quality_fix_loop",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=True, summary="OK", attempts=1),
            ),
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=2
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is True
        assert result.quality_fix_attempts == 1

    @pytest.mark.asyncio
    async def test_run_handles_exception_and_returns_failure(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should catch unexpected exceptions and return success=False."""
        runner = AgentRunner(config, event_bus)

        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=RuntimeError("subprocess exploded"),
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is False
        assert "subprocess exploded" in (result.error or "")

    @pytest.mark.asyncio
    async def test_run_records_error_message_on_exception(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should store the exception message in result.error."""
        runner = AgentRunner(config, event_bus)

        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=RuntimeError("unexpected value"),
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.error is not None
        assert "unexpected value" in result.error

    @pytest.mark.asyncio
    async def test_run_skips_fix_loop_when_max_attempts_zero(
        self, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """run should skip the fix loop when max_quality_fix_attempts is 0."""
        cfg = ConfigFactory.create(
            max_quality_fix_attempts=0,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        runner = AgentRunner(cfg, event_bus)

        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="output"
            ),
            patch.object(
                runner,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=LoopResult(passed=False, summary="Quality failed"),
            ),
            patch.object(
                runner,
                "_run_quality_fix_loop",
                new_callable=AsyncMock,
            ) as fix_mock,
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is False
        fix_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# AgentRunner.run — dry-run mode
# ---------------------------------------------------------------------------


class TestRunDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_success_without_executing(
        self, dry_config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """In dry-run mode, run should succeed without calling _execute."""
        runner = AgentRunner(dry_config, event_bus)

        execute_mock = AsyncMock()
        with patch.object(runner, "_execute", execute_mock):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        execute_mock.assert_not_awaited()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_verify_result(
        self, dry_config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """In dry-run mode, _verify_result should not be called."""
        runner = AgentRunner(dry_config, event_bus)

        verify_mock = AsyncMock()
        with patch.object(runner, "_verify_result", verify_mock):
            await runner.run(agent_task, tmp_path, "agent/issue-42")

        verify_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# CLAUDE.md integrity guard
# ---------------------------------------------------------------------------


class TestClaudeMdIntegrityGuard:
    def test_snapshot_returns_content_when_file_exists(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Project\nSome rules\n")
        assert AgentRunner._snapshot_claude_md(tmp_path) == "# Project\nSome rules\n"

    def test_snapshot_returns_none_when_file_absent(self, tmp_path: Path) -> None:
        assert AgentRunner._snapshot_claude_md(tmp_path) is None

    def test_guard_restores_deleted_file(self, tmp_path: Path) -> None:
        original = "# Project\nLine 1\nLine 2\n"
        # File was deleted by agent
        assert not (tmp_path / "CLAUDE.md").exists()
        AgentRunner._guard_claude_md(tmp_path, original, issue_id=1)
        assert (tmp_path / "CLAUDE.md").read_text() == original

    def test_guard_restores_truncated_file(self, tmp_path: Path) -> None:
        original = "# Project\nLine 1\nLine 2\nLine 3\nLine 4\n"
        (tmp_path / "CLAUDE.md").write_text("# Overwritten\n")
        AgentRunner._guard_claude_md(tmp_path, original, issue_id=2)
        assert (tmp_path / "CLAUDE.md").read_text() == original

    def test_guard_allows_growth(self, tmp_path: Path) -> None:
        original = "# Project\nLine 1\n"
        grown = "# Project\nLine 1\nLine 2 added\nLine 3 added\n"
        (tmp_path / "CLAUDE.md").write_text(grown)
        AgentRunner._guard_claude_md(tmp_path, original, issue_id=3)
        # Should NOT restore — file grew
        assert (tmp_path / "CLAUDE.md").read_text() == grown

    def test_guard_allows_equal_size_modification(self, tmp_path: Path) -> None:
        original = "# Project\nLine 1\nLine 2\n"
        modified = "# Project\nEdited 1\nEdited 2\n"
        (tmp_path / "CLAUDE.md").write_text(modified)
        AgentRunner._guard_claude_md(tmp_path, original, issue_id=4)
        # Same line count — allowed
        assert (tmp_path / "CLAUDE.md").read_text() == modified

    def test_guard_noop_when_snapshot_is_none(self, tmp_path: Path) -> None:
        # No CLAUDE.md existed before — nothing to protect
        AgentRunner._guard_claude_md(tmp_path, None, issue_id=5)
        assert not (tmp_path / "CLAUDE.md").exists()
