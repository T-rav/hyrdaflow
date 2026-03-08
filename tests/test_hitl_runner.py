"""Tests for hitl_runner.py — HITLRunner class."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_runner import BaseRunner
from config import HydraFlowConfig
from events import EventBus, EventType
from hitl_runner import HITLRunner, _classify_cause
from tests.conftest import HITLResultFactory, IssueFactory


@pytest.fixture
def hitl_runner(config, event_bus):
    return HITLRunner(config, event_bus)


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


class TestHITLRunnerInheritance:
    """HITLRunner must extend BaseRunner."""

    def test_inherits_from_base_runner(self, hitl_runner) -> None:
        assert isinstance(hitl_runner, BaseRunner)

    def test_has_terminate_method(self, hitl_runner) -> None:
        assert callable(hitl_runner.terminate)


# ---------------------------------------------------------------------------
# Cause classification
# ---------------------------------------------------------------------------


class TestClassifyCause:
    """Tests for _classify_cause helper function."""

    def test_ci_failure_maps_to_ci(self) -> None:
        assert _classify_cause("CI failed after 2 fix attempt(s)") == "ci"

    def test_check_keyword_maps_to_ci(self) -> None:
        assert _classify_cause("Failed checks: lint, test") == "ci"

    def test_test_fail_keyword_maps_to_ci(self) -> None:
        assert _classify_cause("test fail in module") == "ci"

    def test_merge_conflict_maps_correctly(self) -> None:
        assert _classify_cause("Merge conflict with main branch") == "merge_conflict"

    def test_insufficient_detail_maps_to_needs_info(self) -> None:
        assert _classify_cause("Insufficient issue detail for triage") == "needs_info"

    def test_needs_more_info_maps_to_needs_info(self) -> None:
        assert _classify_cause("Needs more information") == "needs_info"

    def test_unknown_cause_maps_to_default(self) -> None:
        assert _classify_cause("Unknown escalation") == "default"

    def test_pr_merge_failed_maps_to_default(self) -> None:
        assert _classify_cause("PR merge failed on GitHub") == "default"

    def test_empty_cause_maps_to_default(self) -> None:
        assert _classify_cause("") == "default"

    def test_visual_keyword_maps_to_visual(self) -> None:
        assert _classify_cause("Visual validation failed on 3 screens") == "visual"

    def test_screenshot_keyword_maps_to_visual(self) -> None:
        assert _classify_cause("Screenshot diff exceeded threshold") == "visual"

    def test_diff_image_keyword_maps_to_visual(self) -> None:
        assert _classify_cause("diff image mismatch on login page") == "visual"

    def test_visual_before_ci_priority(self) -> None:
        """Visual keywords should match before CI keywords when both present."""
        assert _classify_cause("Visual check failed in CI") == "visual"

    def test_visual_before_needs_info_priority(self) -> None:
        """Visual keywords should match before needs_info when summary contains 'needs'."""
        assert (
            _classify_cause(
                "Visual validation failed: login screen needs baseline update"
            )
            == "visual"
        )

    def test_ci_word_boundary_not_substring(self) -> None:
        """'ci' as a substring of a longer word should not match the ci category."""
        # "deficit" contains "ci" as a substring — should not misclassify
        assert _classify_cause("deficit in implementation coverage") == "default"


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """Tests for HITLRunner._build_prompt."""

    def test_prompt_includes_issue_title(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42, title="Fix the widget")
        prompt = hitl_runner._build_prompt(issue, "Try mocking the DB", "CI failed")
        assert "Fix the widget" in prompt

    def test_prompt_includes_correction_text(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(
            issue, "Mock the database layer", "CI failed"
        )
        assert "Mock the database layer" in prompt

    def test_prompt_includes_cause(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(
            issue, "Fix it", "CI failed after 2 attempts"
        )
        assert "CI failed after 2 attempts" in prompt

    def test_prompt_uses_ci_instructions_for_ci_cause(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(
            issue, "Fix", "CI failed after 2 fix attempt(s)"
        )
        assert "make quality" in prompt
        assert "do NOT skip or disable tests" in prompt

    def test_prompt_uses_merge_instructions_for_conflict_cause(
        self, hitl_runner
    ) -> None:
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(
            issue, "Fix", "Merge conflict with main branch"
        )
        assert "git status" in prompt
        assert "conflict" in prompt.lower()

    def test_prompt_uses_needs_info_instructions(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(
            issue, "Add logging", "Insufficient issue detail for triage"
        )
        assert "comprehensive tests" in prompt

    def test_prompt_uses_visual_instructions_for_visual_cause(
        self, hitl_runner
    ) -> None:
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(
            issue, "Fix the button", "Visual validation failed on login screen"
        )
        assert "visual" in prompt.lower()
        assert "screenshot" in prompt.lower()
        assert "visual regression" in prompt.lower()

    def test_prompt_includes_issue_number_in_commit_message(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=99)
        prompt = hitl_runner._build_prompt(issue, "Fix it", "Unknown")
        assert "#99" in prompt

    def test_prompt_includes_no_push_rule(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(issue, "Fix", "CI failed")
        assert "Do NOT push to remote" in prompt

    def test_prompt_includes_memory_suggestion_block(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(issue, "Fix", "CI failed")
        assert "MEMORY_SUGGESTION_START" in prompt
        assert "MEMORY_SUGGESTION_END" in prompt

    def test_prompt_includes_project_context_when_manifest_exists(
        self, config, event_bus
    ) -> None:
        """Manifest content appears in prompt as ## Project Context."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        manifest_path = config.repo_root / ".hydraflow" / "manifest" / "manifest.md"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("## Project Manifest\npython, make, pytest")

        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)
        prompt = runner._build_prompt(issue, "Fix", "CI failed")
        assert "## Project Context" in prompt
        assert "python, make, pytest" in prompt

    def test_prompt_omits_project_context_when_no_manifest(self, hitl_runner) -> None:
        """Without a manifest file, ## Project Context is not in the prompt."""
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(issue, "Fix", "CI failed")
        assert "## Project Context" not in prompt

    def test_prompt_includes_accumulated_learnings_when_digest_exists(
        self, config, event_bus
    ) -> None:
        """Memory digest content appears in prompt as ## Accumulated Learnings."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        digest_path = config.repo_root / ".hydraflow" / "memory" / "digest.md"
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.write_text("## Memory Digest\nAlways check edge cases")

        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)
        prompt = runner._build_prompt(issue, "Fix", "CI failed")
        assert "## Accumulated Learnings" in prompt
        assert "Always check edge cases" in prompt

    def test_prompt_omits_accumulated_learnings_when_no_digest(
        self, hitl_runner
    ) -> None:
        """Without a digest file, ## Accumulated Learnings is not in the prompt."""
        issue = IssueFactory.create(number=42)
        prompt = hitl_runner._build_prompt(issue, "Fix", "CI failed")
        assert "## Accumulated Learnings" not in prompt


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------


class TestBuildCommand:
    """Tests for HITLRunner._build_command."""

    def test_command_includes_claude(self, hitl_runner) -> None:
        cmd = hitl_runner._build_command(Path("/tmp/wt"))
        assert cmd[0] == "claude"
        assert "-p" in cmd

    def test_command_includes_model(self, hitl_runner, config) -> None:
        cmd = hitl_runner._build_command(Path("/tmp/wt"))
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == config.model

    def test_command_excludes_budget_flag(self, hitl_runner) -> None:
        cmd = hitl_runner._build_command(Path("/tmp/wt"))
        assert "--max-budget-usd" not in cmd

    def test_command_supports_codex_backend(self, event_bus) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            implementation_tool="codex",
            model="gpt-5-codex",
        )
        runner = HITLRunner(cfg, event_bus)
        cmd = runner._build_command(Path("/tmp/wt"))
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


# ---------------------------------------------------------------------------
# Run — dry run mode
# ---------------------------------------------------------------------------


class TestRunDryMode:
    """Tests for HITLRunner.run in dry-run mode."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_success(self, dry_config, event_bus) -> None:
        runner = HITLRunner(dry_config, event_bus)
        issue = IssueFactory.create(number=42)
        result = await runner.run(issue, "correction", "cause", Path("/tmp/wt"))
        assert result.success is True
        assert result.issue_number == 42

    @pytest.mark.asyncio
    async def test_dry_run_publishes_event(self, dry_config, event_bus) -> None:
        runner = HITLRunner(dry_config, event_bus)
        issue = IssueFactory.create(number=42)
        await runner.run(issue, "correction", "cause", Path("/tmp/wt"))

        events = [e for e in event_bus.get_history() if e.type == EventType.HITL_UPDATE]
        assert len(events) >= 1
        assert events[0].data["status"] == "running"


# ---------------------------------------------------------------------------
# Run — execution
# ---------------------------------------------------------------------------


class TestRunExecution:
    """Tests for HITLRunner.run with mocked execution."""

    @pytest.mark.asyncio
    async def test_run_success_returns_result(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(return_value="transcript text")  # type: ignore[method-assign]
        runner._verify_quality = AsyncMock(return_value=(True, "OK"))  # type: ignore[method-assign]
        runner._save_transcript = lambda *a: None  # type: ignore[method-assign]

        result = await runner.run(issue, "fix the test", "CI failed", Path("/tmp/wt"))

        assert result.success is True
        assert result.issue_number == 42
        assert result.transcript == "transcript text"
        assert result.duration_seconds > 0
        telemetry = runner._execute.await_args.kwargs["telemetry_stats"]
        assert int(telemetry["pruned_chars_total"]) >= 0

    @pytest.mark.asyncio
    async def test_run_failure_sets_error(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(return_value="transcript text")  # type: ignore[method-assign]
        runner._verify_quality = AsyncMock(  # type: ignore[method-assign]
            return_value=(False, "`make quality` failed:\ntest_foo FAILED")
        )
        runner._save_transcript = lambda *a: None  # type: ignore[method-assign]

        result = await runner.run(issue, "fix the test", "CI failed", Path("/tmp/wt"))

        assert result.success is False
        assert result.error is not None
        assert "make quality" in result.error

    def test_build_prompt_with_stats_prunes_large_guidance(
        self, config, event_bus
    ) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42, body="b" * 200)
        _prompt, stats = runner._build_prompt_with_stats(
            issue,
            correction="x" * 10_000,
            cause="y" * 6000,
        )
        assert stats["pruned_chars_total"] > 0

    @pytest.mark.asyncio
    async def test_run_exception_sets_error(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        result = await runner.run(issue, "fix the test", "CI failed", Path("/tmp/wt"))

        assert result.success is False
        assert result.error == "boom"

    @pytest.mark.asyncio
    async def test_run_publishes_start_and_end_events(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(return_value="transcript")  # type: ignore[method-assign]
        runner._verify_quality = AsyncMock(return_value=(True, "OK"))  # type: ignore[method-assign]
        runner._save_transcript = lambda *a: None  # type: ignore[method-assign]

        await runner.run(issue, "fix it", "CI failed", Path("/tmp/wt"))

        hitl_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_UPDATE
        ]
        statuses = [e.data["status"] for e in hitl_events]
        assert "running" in statuses
        assert "done" in statuses

    @pytest.mark.asyncio
    async def test_run_failure_publishes_failed_status(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(return_value="transcript")  # type: ignore[method-assign]
        runner._verify_quality = AsyncMock(  # type: ignore[method-assign]
            return_value=(False, "quality failed")
        )
        runner._save_transcript = lambda *a: None  # type: ignore[method-assign]

        await runner.run(issue, "fix it", "CI failed", Path("/tmp/wt"))

        hitl_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_UPDATE
        ]
        statuses = [e.data["status"] for e in hitl_events]
        assert "failed" in statuses


# ---------------------------------------------------------------------------
# Transcript saving
# ---------------------------------------------------------------------------


class TestSaveTranscript:
    """Tests for HITLRunner._save_transcript."""

    def test_saves_transcript_to_disk(self, hitl_runner, config) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        hitl_runner._save_transcript("hitl-issue", 42, "test transcript content")

        path = config.repo_root / ".hydraflow" / "logs" / "hitl-issue-42.txt"
        assert path.exists()
        assert path.read_text() == "test transcript content"

    def test_save_transcript_handles_oserror(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = HITLRunner(config, EventBus())

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            runner._save_transcript("hitl-issue", 42, "transcript")  # should not raise

        assert "Could not save transcript" in caplog.text


# ---------------------------------------------------------------------------
# Terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    """Tests for HITLRunner.terminate."""

    def test_terminate_with_no_active_procs(self, hitl_runner) -> None:
        hitl_runner.terminate()  # Should not raise

    def test_terminate_calls_terminate_processes(self, hitl_runner) -> None:
        with patch("base_runner.terminate_processes") as mock_term:
            hitl_runner.terminate()
            mock_term.assert_called_once_with(hitl_runner._active_procs)


# ---------------------------------------------------------------------------
# HITLResult model
# ---------------------------------------------------------------------------


class TestHITLResult:
    """Tests for the HITLResult Pydantic model."""

    def test_hitl_result_failure_has_empty_transcript_and_zero_duration(self) -> None:
        result = HITLResultFactory.create(success=False)
        assert result.issue_number == 42
        assert result.success is False
        assert result.error is None
        assert result.transcript == ""
        assert result.duration_seconds == 0.0

    def test_hitl_result_success_sets_true_and_stores_transcript(self) -> None:
        result = HITLResultFactory.create(transcript="done")
        assert result.success is True
        assert result.transcript == "done"


# ---------------------------------------------------------------------------
# _verify_quality — timeout
# ---------------------------------------------------------------------------


class TestVerifyQualityTimeout:
    """Tests for _verify_quality timeout behavior."""

    @pytest.mark.asyncio
    async def test_verify_quality_timeout_returns_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """_verify_quality should return (False, ...) when make quality times out."""
        runner = HITLRunner(config, EventBus())

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("asyncio.wait_for", side_effect=TimeoutError),
        ):
            success, msg = await runner._verify_quality(Path("/tmp/wt"))

        assert success is False
        assert "timed out" in msg

    @pytest.mark.asyncio
    async def test_verify_quality_timeout_kills_process(
        self, config: HydraFlowConfig
    ) -> None:
        """_verify_quality should kill the process on timeout."""
        runner = HITLRunner(config, EventBus())

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("asyncio.wait_for", side_effect=TimeoutError),
        ):
            await runner._verify_quality(Path("/tmp/wt"))

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()
