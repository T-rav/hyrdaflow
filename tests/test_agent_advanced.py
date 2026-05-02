"""Tests for agent — advanced."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent import AgentRunner
from events import EventBus, EventType
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_streaming_proc


@pytest.fixture
def agent_task():
    return TaskFactory.create()


# ---------------------------------------------------------------------------
# AgentRunner._execute — streaming
# ---------------------------------------------------------------------------


class TestTerminate:
    def test_terminate_kills_active_processes(
        self, config, event_bus: EventBus
    ) -> None:
        """terminate() should use os.killpg() on all tracked processes."""
        runner = AgentRunner(config, event_bus)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        runner._active_procs.add(mock_proc)

        with patch("runner_utils.os.killpg") as mock_killpg:
            runner.terminate()

        mock_killpg.assert_called_once()

    def test_terminate_handles_process_lookup_error(
        self, config, event_bus: EventBus
    ) -> None:
        """terminate() should not raise when a process has already exited."""
        runner = AgentRunner(config, event_bus)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        runner._active_procs.add(mock_proc)

        with patch(
            "runner_utils.os.killpg", side_effect=ProcessLookupError
        ) as mock_killpg:
            runner.terminate()  # Should not raise

        mock_killpg.assert_called_once()


class TestExecuteStreaming:
    @pytest.mark.asyncio
    async def test_execute_returns_transcript(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """_execute should return the full transcript from stdout lines."""
        runner = AgentRunner(config, event_bus)
        output = "Line one\nLine two\nLine three"
        mock_create = make_streaming_proc(returncode=0, stdout=output)

        with patch("asyncio.create_subprocess_exec", mock_create):
            transcript = await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": agent_task.id}
            )

        assert transcript == output

    @pytest.mark.asyncio
    async def test_execute_publishes_transcript_line_events(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """_execute should publish a TRANSCRIPT_LINE event per non-empty line."""
        runner = AgentRunner(config, event_bus)
        output = "Line one\nLine two\nLine three"
        mock_create = make_streaming_proc(returncode=0, stdout=output)

        with patch("asyncio.create_subprocess_exec", mock_create):
            await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": agent_task.id}
            )

        events = event_bus.get_history()
        transcript_events = [e for e in events if e.type == EventType.TRANSCRIPT_LINE]
        assert len(transcript_events) == 3
        lines = [e.data["line"] for e in transcript_events]
        assert "Line one" in lines
        assert "Line two" in lines
        assert "Line three" in lines
        for ev in transcript_events:
            assert ev.data["issue"] == agent_task.id

    @pytest.mark.asyncio
    async def test_execute_skips_empty_lines_for_events(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """_execute should not publish events for blank/whitespace-only lines."""
        runner = AgentRunner(config, event_bus)
        output = "Line one\n\n   \nLine two"
        mock_create = make_streaming_proc(returncode=0, stdout=output)

        with patch("asyncio.create_subprocess_exec", mock_create):
            await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": agent_task.id}
            )

        events = event_bus.get_history()
        transcript_events = [e for e in events if e.type == EventType.TRANSCRIPT_LINE]
        assert len(transcript_events) == 2

    @pytest.mark.asyncio
    async def test_execute_logs_warning_on_nonzero_exit(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """_execute should log a warning when the process exits non-zero."""
        runner = AgentRunner(config, event_bus)
        mock_create = make_streaming_proc(
            returncode=1, stdout="output", stderr="error details"
        )

        mock_logger = MagicMock()
        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            patch.object(runner, "_log", mock_logger),
        ):
            await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": agent_task.id}
            )

        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_uses_large_stream_limit(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """_execute should set limit=1MB on subprocess to handle large stream-json lines."""
        runner = AgentRunner(config, event_bus)
        mock_create = make_streaming_proc(returncode=0, stdout="ok")

        with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
            await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": agent_task.id}
            )

        kwargs = mock_exec.call_args[1]
        assert kwargs["limit"] == 1024 * 1024


# ---------------------------------------------------------------------------
# AgentRunner._strip_plan_noise
# ---------------------------------------------------------------------------


class TestStripPlanNoise:
    def test_removes_generated_by_footer(self) -> None:
        raw = (
            "## Implementation Plan\n\n"
            "Step 1: Do this\n\n"
            "---\n"
            "*Generated by HydraFlow Planner*"
        )
        result = AgentRunner._strip_plan_noise(raw)
        assert "Generated by HydraFlow Planner" not in result
        assert "Step 1: Do this" in result

    def test_removes_branch_info(self) -> None:
        raw = (
            "## Implementation Plan\n\n"
            "Step 1: Do this\n\n"
            "**Branch:** `agent/issue-10`\n\n"
            "---\n"
            "*Generated by HydraFlow Planner*"
        )
        result = AgentRunner._strip_plan_noise(raw)
        assert "**Branch:**" not in result
        assert "agent/issue-10" not in result

    def test_removes_html_comments(self) -> None:
        raw = (
            "<!-- plan metadata -->\n"
            "## Implementation Plan\n\n"
            "Step 1: Do this\n"
            "<!-- internal note -->\n"
            "Step 2: Do that"
        )
        result = AgentRunner._strip_plan_noise(raw)
        assert "<!-- plan metadata -->" not in result
        assert "<!-- internal note -->" not in result
        assert "Step 1: Do this" in result
        assert "Step 2: Do that" in result

    def test_extracts_plan_body_between_header_and_separator(self) -> None:
        raw = (
            "## Implementation Plan\n\n"
            "The actual plan content here.\n\n"
            "---\n"
            "Footer stuff that should be removed"
        )
        result = AgentRunner._strip_plan_noise(raw)
        assert "The actual plan content here." in result
        assert "Footer stuff that should be removed" not in result

    def test_handles_no_separator(self) -> None:
        raw = "## Implementation Plan\n\nStep 1: Do this\nStep 2: Do that"
        result = AgentRunner._strip_plan_noise(raw)
        assert "Step 1: Do this" in result
        assert "Step 2: Do that" in result

    def test_handles_empty_plan(self) -> None:
        raw = "## Implementation Plan\n\n---\n*Generated by HydraFlow Planner*"
        result = AgentRunner._strip_plan_noise(raw)
        assert result == ""

    def test_preserves_plan_content_with_full_orchestrator_format(self) -> None:
        raw = (
            "## Implementation Plan\n\n"
            "1. Add field to config\n"
            "2. Update agent prompt\n"
            "3. Write tests\n\n"
            "**Branch:** `agent/issue-42`\n\n"
            "---\n"
            "*Generated by HydraFlow Planner*"
        )
        result = AgentRunner._strip_plan_noise(raw)
        assert "1. Add field to config" in result
        assert "2. Update agent prompt" in result
        assert "3. Write tests" in result
        assert "**Branch:**" not in result
        assert "Generated by HydraFlow Planner" not in result


# ---------------------------------------------------------------------------
# AgentRunner._load_plan_fallback
# ---------------------------------------------------------------------------


class TestLoadPlanFallback:
    def test_returns_empty_when_file_missing(self, config, event_bus: EventBus) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = AgentRunner(config, event_bus)
        result = runner._load_plan_fallback(999)
        assert result == ""

    def test_loads_plan_from_file(self, config, event_bus: EventBus) -> None:
        plan_dir = config.repo_root / ".hydraflow" / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "issue-42.md"
        plan_file.write_text(
            "# Plan for Issue #42\n\n"
            "Step 1: Do this\nStep 2: Do that\n\n"
            "---\n**Summary:** A plan"
        )

        runner = AgentRunner(config, event_bus)
        result = runner._load_plan_fallback(42)
        assert "Step 1: Do this" in result
        assert "Step 2: Do that" in result
        # Header and footer should be stripped
        assert "# Plan for Issue #42" not in result
        assert "**Summary:**" not in result

    def test_logs_warning_on_fallback(self, config, event_bus: EventBus) -> None:
        plan_dir = config.repo_root / ".hydraflow" / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "issue-42.md").write_text("# Plan for Issue #42\n\nPlan body\n")

        runner = AgentRunner(config, event_bus)
        with patch("agent.logger") as mock_logger:
            runner._load_plan_fallback(42)
        mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# AgentRunner._build_prompt_with_stats — fallback and truncation
# ---------------------------------------------------------------------------


class TestBuildPromptFallbackAndTruncation:
    @pytest.mark.asyncio
    async def test_falls_back_to_plan_file(self, config, event_bus: EventBus) -> None:
        """When no plan comment exists, should fall back to .hydraflow/plans/."""
        plan_dir = config.repo_root / ".hydraflow" / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "issue-10.md").write_text(
            "# Plan for Issue #10\n\nStep 1: saved plan\n"
        )

        issue = TaskFactory.create(
            id=10,
            title="Feature X",
            body="Body text",
            comments=[],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = await runner._build_prompt_with_stats(issue)
        assert "Step 1: saved plan" in prompt
        assert "Follow this plan closely" in prompt

    @pytest.mark.asyncio
    async def test_logs_error_when_no_plan_found(
        self, config, event_bus: EventBus
    ) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        issue = TaskFactory.create(
            id=10,
            title="Feature X",
            body="Body text",
            comments=[],
        )
        runner = AgentRunner(config, event_bus)
        with patch("agent.logger") as mock_logger:
            prompt, _ = await runner._build_prompt_with_stats(issue)
        mock_logger.error.assert_called_once()
        # Should still produce a valid prompt without a plan section
        assert "Follow this plan closely" not in prompt
        assert "## Instructions" in prompt

    @pytest.mark.asyncio
    async def test_truncates_long_body(self, config, event_bus: EventBus) -> None:
        """Body exceeding max_issue_body_chars should be truncated with a note."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        long_body = "x" * 15_000
        issue = TaskFactory.create(
            id=10,
            title="Feature X",
            body=long_body,
            comments=[],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = await runner._build_prompt_with_stats(issue)
        assert "x" * 10_000 in prompt
        assert "x" * 15_000 not in prompt
        assert "Body truncated" in prompt

    @pytest.mark.asyncio
    async def test_preserves_short_body(self, config, event_bus: EventBus) -> None:
        """Body under max_issue_body_chars should pass through unchanged."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        short_body = "This is a short body."
        issue = TaskFactory.create(
            id=10,
            title="Feature X",
            body=short_body,
            comments=[],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = await runner._build_prompt_with_stats(issue)
        assert short_body in prompt
        assert "Body truncated" not in prompt

    @pytest.mark.asyncio
    async def test_uses_configured_test_command(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Prompt should use test_command from config."""
        cfg = ConfigFactory.create(
            test_command="npm test",
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
        issue = TaskFactory.create(
            id=10,
            title="Feature X",
            body="Body text",
            comments=[],
        )
        runner = AgentRunner(cfg, event_bus)
        prompt, _ = await runner._build_prompt_with_stats(issue)
        assert "npm test" in prompt
        assert "make test-fast" not in prompt

    @pytest.mark.asyncio
    async def test_default_test_command_is_make_test(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Default test_command should produce 'make test' in the prompt."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = await runner._build_prompt_with_stats(agent_task)
        assert "`make test`" in prompt


# ---------------------------------------------------------------------------
# AgentRunner._verify_result — timeout
# ---------------------------------------------------------------------------


class TestVerifyResultTimeout:
    @pytest.mark.asyncio
    async def test_verify_result_timeout_returns_failure(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_verify_result should return (False, ...) when make quality times out."""
        runner = AgentRunner(config, event_bus)

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
            patch(
                "asyncio.wait_for",
                side_effect=TimeoutError,
            ),
        ):
            result = await runner._verify_result(tmp_path, "agent/issue-42")

        assert result.passed is False
        assert "timed out" in result.summary

    @pytest.mark.asyncio
    async def test_verify_result_timeout_kills_process(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_verify_result should kill the process on timeout."""
        runner = AgentRunner(config, event_bus)

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
            patch(
                "asyncio.wait_for",
                side_effect=TimeoutError,
            ),
        ):
            await runner._verify_result(tmp_path, "agent/issue-42")

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited()


# ---------------------------------------------------------------------------
# AgentRunner._count_commits — timeout
# ---------------------------------------------------------------------------


class TestCountCommitsTimeout:
    @pytest.mark.asyncio
    async def test_count_commits_timeout_returns_zero(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """_count_commits should return 0 when git rev-list times out."""
        runner = AgentRunner(config, event_bus)
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=mock_proc),
            ),
            patch(
                "asyncio.wait_for",
                side_effect=TimeoutError,
            ),
        ):
            result = await runner._count_commits(tmp_path, "agent/issue-42")

        assert result == 0


# ---------------------------------------------------------------------------
# AgentRunner._build_prompt_with_stats — runtime log injection
# ---------------------------------------------------------------------------


class TestBuildPromptRuntimeLogs:
    @pytest.mark.asyncio
    async def test_prompt_includes_runtime_logs_when_present(
        self, tmp_path: Path, event_bus: EventBus
    ) -> None:
        """When logs exist, prompt includes them."""
        config = ConfigFactory.create(
            repo_root=tmp_path,
        )
        # Create a log file
        log_dir = tmp_path / ".hydraflow" / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "hydraflow.log").write_text("INFO: server started\nERROR: timeout\n")

        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        prompt, _ = await runner._build_prompt_with_stats(issue)

        assert "## Recent Application Logs" in prompt
        assert "ERROR: timeout" in prompt

    @pytest.mark.asyncio
    async def test_prompt_excludes_runtime_logs_when_disabled(
        self, config, event_bus: EventBus
    ) -> None:
        """Default config does not include runtime logs."""
        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        prompt, _ = await runner._build_prompt_with_stats(issue)

        assert "## Recent Application Logs" not in prompt

    @pytest.mark.asyncio
    async def test_prompt_excludes_runtime_logs_when_empty(
        self, tmp_path: Path, event_bus: EventBus
    ) -> None:
        """No log file — no log section in prompt."""
        config = ConfigFactory.create(
            repo_root=tmp_path,
        )
        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        prompt, _ = await runner._build_prompt_with_stats(issue)

        assert "## Recent Application Logs" not in prompt


# ---------------------------------------------------------------------------
# Prior failure section in prompt
# ---------------------------------------------------------------------------


class TestPriorFailureInPrompt:
    @pytest.mark.asyncio
    async def test_prior_failure_included_in_prompt(
        self, config, event_bus: EventBus
    ) -> None:
        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        prompt, _ = await runner._build_prompt_with_stats(
            issue,
            prior_failure="TDD red phase modified non-test files: docs/adr/001.md",
        )

        assert "## Prior Attempt Failure" in prompt
        assert "TDD red phase modified non-test files: docs/adr/001.md" in prompt
        assert "Avoid repeating the same mistake" in prompt

    @pytest.mark.asyncio
    async def test_no_prior_failure_section_when_empty(
        self, config, event_bus: EventBus
    ) -> None:
        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        prompt, _ = await runner._build_prompt_with_stats(issue, prior_failure="")

        assert "## Prior Attempt Failure" not in prompt
