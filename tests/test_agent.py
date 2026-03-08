"""Tests for dx/hydraflow/agent.py — AgentRunner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent import AgentRunner
from base_runner import BaseRunner
from events import EventBus, EventType
from models import ReviewVerdict, Task, WorkerStatus
from tests.conftest import TaskFactory, WorkerResultFactory
from tests.helpers import ConfigFactory, make_proc, make_streaming_proc

# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


class TestAgentRunnerInheritance:
    """AgentRunner must extend BaseRunner."""

    def test_inherits_from_base_runner(self, config, event_bus: EventBus) -> None:
        runner = AgentRunner(config, event_bus)
        assert isinstance(runner, BaseRunner)

    def test_has_terminate_method(self, config, event_bus: EventBus) -> None:
        runner = AgentRunner(config, event_bus)
        assert callable(runner.terminate)


# ---------------------------------------------------------------------------
# Helpers (agent-specific)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# agent_task fixture — returns Task instead of GitHubIssue
# ---------------------------------------------------------------------------


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
# AgentRunner._build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    """Tests for AgentRunner._build_command."""

    def test_build_command_starts_with_claude(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Command should start with 'claude'."""
        runner = AgentRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert cmd[0] == "claude"

    def test_build_command_includes_print_flag(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Command should include the -p (print/non-interactive) flag."""
        runner = AgentRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "-p" in cmd

    def test_build_command_does_not_include_cwd(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Command should not include --cwd; cwd is set on the subprocess."""
        runner = AgentRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "--cwd" not in cmd

    def test_build_command_includes_model(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Command should include --model matching config.model."""
        runner = AgentRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "--model" in cmd
        model_index = cmd.index("--model")
        assert cmd[model_index + 1] == config.model

    def test_build_command_includes_output_format_text(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Command should pass --output-format text."""
        runner = AgentRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "--output-format" in cmd
        fmt_index = cmd.index("--output-format")
        assert cmd[fmt_index + 1] == "stream-json"

    def test_build_command_includes_verbose(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Command should include --verbose."""
        runner = AgentRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "--verbose" in cmd

    def test_build_command_supports_codex_backend(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Codex backend should build a non-interactive codex exec command."""
        cfg = ConfigFactory.create(
            implementation_tool="codex",
            model="gpt-5-codex",
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        runner = AgentRunner(cfg, event_bus)
        cmd = runner._build_command(tmp_path)
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"
        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "danger-full-access"
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--skip-git-repo-check" in cmd
        assert "--ask-for-approval" not in cmd


# ---------------------------------------------------------------------------
# AgentRunner._build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """Tests for AgentRunner._build_prompt."""

    def test_prompt_includes_issue_number(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should reference the issue number."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert str(agent_task.id) in prompt

    def test_prompt_includes_title(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include the issue title."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert agent_task.title in prompt

    def test_prompt_includes_body(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include the issue body text."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert agent_task.body in prompt

    def test_prompt_includes_rules(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should contain the mandatory rules section."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "Rules" in prompt or "rules" in prompt.lower()

    def test_prompt_references_make_quality(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should instruct the agent to run make quality."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "make quality" in prompt

    def test_prompt_does_not_reference_make_test_fast(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should not reference make test-fast anywhere (replaced by configurable test_command)."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "make test-fast" not in prompt

    def test_prompt_includes_comments_section_when_comments_exist(
        self, config, event_bus: EventBus
    ) -> None:
        """Prompt should include a Discussion section when the issue has comments."""
        issue_with_comments = Task(
            id=10,
            title="Add feature X",
            body="We need feature X",
            comments=["Please also handle edge case Y", "What about Z?"],
        )
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(issue_with_comments)

        assert "Discussion" in prompt
        assert "Please also handle edge case Y" in prompt
        assert "What about Z?" in prompt

    def test_prompt_omits_comments_section_when_no_comments(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should not include a Discussion section when there are no comments."""
        # Default agent_task fixture has empty comments
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "Discussion" not in prompt

    def test_prompt_extracts_plan_comment_as_dedicated_section(
        self, config, event_bus: EventBus
    ) -> None:
        """When a comment contains '## Implementation Plan', it should be rendered
        as a dedicated plan section with follow-this-plan instruction."""
        issue = Task(
            id=10,
            title="Add feature X",
            body="We need feature X",
            comments=[
                "## Implementation Plan\n\nStep 1: Do this\nStep 2: Do that\n\n---\n*Generated by HydraFlow Planner*",
                "Please also handle edge case Y",
            ],
        )
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(issue)

        assert "## Implementation Plan" in prompt
        assert "Follow this plan closely" in prompt
        assert "Step 1: Do this" in prompt
        assert "Step 2: Do that" in prompt
        # Noise should be stripped
        assert "Generated by HydraFlow Planner" not in prompt
        # The other comment should be in Discussion
        assert "Discussion" in prompt
        assert "Please also handle edge case Y" in prompt

    def test_prompt_plan_comment_excluded_from_discussion(
        self, config, event_bus: EventBus
    ) -> None:
        """The plan comment should NOT appear in the Discussion section."""
        issue = Task(
            id=10,
            title="Add feature X",
            body="We need feature X",
            comments=[
                "## Implementation Plan\n\nStep 1: Do this",
            ],
        )
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(issue)

        # Plan is in dedicated section, no Discussion section at all
        assert "## Implementation Plan" in prompt
        assert "Discussion" not in prompt

    def test_prompt_no_plan_section_when_no_plan_comment(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """When no comment contains a plan, no plan section should appear."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)

        assert "Follow this plan closely" not in prompt

    def test_prompt_includes_ui_guidelines(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include UI guidelines for component reuse and responsive design."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "UI Guidelines" in prompt
        assert "src/ui/src/components/" in prompt
        assert "never duplicate" in prompt.lower()
        assert "minWidth" in prompt
        assert "theme" in prompt.lower()

    def test_prompt_instructs_no_push_or_pr(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should explicitly tell the agent not to push or create PRs."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "push" in prompt.lower() or "Do NOT push" in prompt
        assert "pull request" in prompt.lower() or "pr create" in prompt.lower()

    def test_prompt_forbids_interactive_git(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should forbid interactive git commands (no TTY in Docker)."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "git add -i" in prompt
        assert "git add -p" in prompt
        assert "git rebase -i" in prompt

    def test_prompt_includes_common_feedback_when_reviews_exist(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include Common Review Feedback when review data exists."""
        from review_insights import ReviewInsightStore, ReviewRecord

        store = ReviewInsightStore(config.repo_root / ".hydraflow" / "memory")
        for i in range(4):
            store.append_review(
                ReviewRecord(
                    pr_number=90 + i,
                    issue_number=30 + i,
                    timestamp="2026-02-20T10:00:00Z",
                    verdict=ReviewVerdict.REQUEST_CHANGES,
                    summary="Missing test coverage",
                    fixes_made=False,
                    categories=["missing_tests"],
                )
            )

        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "## Common Review Feedback" in prompt
        assert "Missing or insufficient test coverage" in prompt

    def test_prompt_works_without_review_data(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should work normally when no review data exists."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "## Common Review Feedback" not in prompt
        # The rest of the prompt should still be there
        assert "## Instructions" in prompt
        assert "## Rules" in prompt

    def test_prompt_truncates_long_discussion_comments(
        self, config, event_bus: EventBus
    ) -> None:
        issue = Task(
            id=11,
            title="Fix long comment token blowup",
            body="Normal issue body",
            comments=["A" * 5000],
        )
        runner = AgentRunner(config, event_bus)
        prompt, stats = runner._build_prompt_with_stats(issue)
        assert "[Comment truncated from" in prompt
        assert int(stats["pruned_chars_total"]) > 0

    def test_prompt_truncates_common_feedback_section(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner,
            "_get_review_feedback_section",
            return_value="B" * 10000,
        ):
            prompt, stats = runner._build_prompt_with_stats(agent_task)
        assert "Common review feedback summarized" in prompt
        assert int(stats["pruned_chars_total"]) > 0

    def test_prompt_includes_review_feedback_when_provided(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include Review Feedback section when feedback is provided."""
        runner = AgentRunner(config, event_bus)
        feedback = "Missing error handling in the parse_config function"
        prompt = runner._build_prompt(agent_task, review_feedback=feedback)
        assert "## Review Feedback" in prompt
        assert "Missing error handling in the parse_config function" in prompt
        assert "reviewer rejected" in prompt.lower()

    def test_prompt_omits_review_feedback_when_empty(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should not include Review Feedback section when feedback is empty."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task, review_feedback="")
        assert "## Review Feedback" not in prompt

    def test_prompt_review_feedback_after_plan_section(
        self, config, event_bus: EventBus
    ) -> None:
        """Review feedback should appear after the plan section."""
        issue = Task(
            id=10,
            title="Add feature X",
            body="We need feature X",
            comments=[
                "## Implementation Plan\n\nStep 1: Do this\nStep 2: Do that",
            ],
        )
        runner = AgentRunner(config, event_bus)
        feedback = "Tests are missing for edge cases"
        prompt = runner._build_prompt(issue, review_feedback=feedback)

        plan_pos = prompt.index("## Implementation Plan")
        feedback_pos = prompt.index("## Review Feedback")
        instructions_pos = prompt.index("## Instructions")

        assert plan_pos < feedback_pos < instructions_pos

    def test_prompt_includes_self_check_checklist(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include the self-check checklist section."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "## Self-Check Before Committing" in prompt
        assert "Tests cover all new/changed code" in prompt
        assert "No missing imports" in prompt
        assert "Type hints are correct" in prompt
        assert "Edge cases handled" in prompt
        assert "No leftover debug code" in prompt

    def test_self_check_appears_after_instructions(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Self-check should appear after Instructions and before UI Guidelines."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        instructions_pos = prompt.index("## Instructions")
        self_check_pos = prompt.index("## Self-Check Before Committing")
        ui_pos = prompt.index("## UI Guidelines")
        assert instructions_pos < self_check_pos < ui_pos

    def test_self_check_is_class_constant(self) -> None:
        """_SELF_CHECK_CHECKLIST should be a non-empty class attribute."""
        assert hasattr(AgentRunner, "_SELF_CHECK_CHECKLIST")
        assert len(AgentRunner._SELF_CHECK_CHECKLIST) > 100

    def test_prompt_includes_escalated_mandatory_block_when_recurring(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """When missing_tests is recurring, prompt should include mandatory block."""
        escalation_data = [
            {
                "category": "missing_tests",
                "count": 4,
                "mandatory_block": "## Mandatory Requirements\nEvery new function MUST have a test.",
                "checklist_items": [
                    "- [ ] Every new/modified public function has a dedicated test",
                ],
                "pre_quality_guidance": "Verify all new functions have tests.",
            }
        ]
        runner = AgentRunner(config, event_bus)
        with patch.object(runner, "_get_escalation_data", return_value=escalation_data):
            prompt = runner._build_prompt(agent_task)
        assert "## Mandatory Requirements" in prompt
        assert "Every new function MUST have a test" in prompt

    def test_prompt_no_mandatory_block_when_no_escalations(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """When no escalations, prompt should not include mandatory block."""
        runner = AgentRunner(config, event_bus)
        with patch.object(runner, "_get_escalation_data", return_value=[]):
            prompt = runner._build_prompt(agent_task)
        assert "## Mandatory Requirements" not in prompt

    def test_self_check_includes_dynamic_items_when_escalated(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Self-check should include category-specific items when escalated."""
        escalation_data = [
            {
                "category": "missing_tests",
                "count": 4,
                "mandatory_block": "Must test.",
                "checklist_items": [
                    "- [ ] Every new/modified public function has a dedicated test",
                    "- [ ] Edge cases (None, empty, boundary) are tested",
                ],
                "pre_quality_guidance": "Check tests.",
            }
        ]
        runner = AgentRunner(config, event_bus)
        with patch.object(runner, "_get_escalation_data", return_value=escalation_data):
            prompt = runner._build_prompt(agent_task)
        assert "Every new/modified public function has a dedicated test" in prompt
        assert "Edge cases (None, empty, boundary) are tested" in prompt

    def test_pre_quality_review_includes_escalation_guidance(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Pre-quality review prompt should include escalation guidance when present."""
        escalation_data = [
            {
                "category": "missing_tests",
                "count": 4,
                "mandatory_block": "Must test.",
                "checklist_items": [],
                "pre_quality_guidance": "Verify every new public function has a unit test.",
            }
        ]
        runner = AgentRunner(config, event_bus)
        with patch.object(runner, "_get_escalation_data", return_value=escalation_data):
            prompt = runner._build_pre_quality_review_prompt(agent_task, attempt=1)
        assert "Verify every new public function has a unit test" in prompt

    def test_pre_quality_review_no_escalation_when_empty(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Pre-quality review prompt should not have escalation section when empty."""
        runner = AgentRunner(config, event_bus)
        with patch.object(runner, "_get_escalation_data", return_value=[]):
            prompt = runner._build_pre_quality_review_prompt(agent_task, attempt=1)
        assert "Escalated Requirements" not in prompt

    def test_pre_quality_review_includes_edge_case_checks(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Pre-quality review prompt should include expanded scope items."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_pre_quality_review_prompt(agent_task, attempt=1)
        assert "type hints" in prompt
        assert "edge cases" in prompt
        assert "empty inputs" in prompt

    def test_prompt_forbids_already_satisfied(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt must instruct agent to never claim issue is already satisfied."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "NEVER conclude that the issue is" in prompt
        assert "already satisfied" in prompt.lower()
        assert "Always produce commits" in prompt


# ---------------------------------------------------------------------------
# AgentRunner._get_escalation_data
# ---------------------------------------------------------------------------


class TestGetEscalationData:
    """Tests for the _get_escalation_data method (JSON round-trip and error handling)."""

    def test_returns_empty_list_when_no_reviews(
        self, config, event_bus: EventBus
    ) -> None:
        """Returns [] when context cache returns empty string."""
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner._context_cache,
            "get_or_load",
            return_value=("", False),
        ):
            result = runner._get_escalation_data()
        assert result == []

    def test_returns_deserialized_escalations(
        self, config, event_bus: EventBus
    ) -> None:
        """Deserializes JSON returned from cache back to list of dicts."""
        import json

        escalation = {
            "category": "missing_tests",
            "count": 4,
            "mandatory_block": "## Mandatory Requirements\nTests are required.",
            "checklist_items": ["- [ ] Every function has a test"],
            "pre_quality_guidance": "Check tests.",
        }
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner._context_cache,
            "get_or_load",
            return_value=(json.dumps([escalation]), False),
        ):
            result = runner._get_escalation_data()
        assert len(result) == 1
        assert result[0]["category"] == "missing_tests"
        assert result[0]["count"] == 4

    def test_returns_empty_list_on_json_error(
        self, config, event_bus: EventBus
    ) -> None:
        """Returns [] when cache contains malformed JSON."""
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner._context_cache,
            "get_or_load",
            return_value=("not-valid-json", False),
        ):
            result = runner._get_escalation_data()
        assert result == []

    def test_returns_empty_list_on_cache_exception(
        self, config, event_bus: EventBus
    ) -> None:
        """Returns [] when the cache raises an unexpected exception."""
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner._context_cache,
            "get_or_load",
            side_effect=OSError("disk error"),
        ):
            result = runner._get_escalation_data()
        assert result == []


# ---------------------------------------------------------------------------
# Diff sanity + test adequacy skill loops
# ---------------------------------------------------------------------------


class TestDiffSanityLoop:
    """Tests for the diff sanity check skill integration."""

    @pytest.mark.asyncio
    async def test_skipped_when_disabled(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_diff_sanity_attempts = 0
        runner = AgentRunner(config, event_bus)
        ok, msg = await runner._run_diff_sanity_loop(
            agent_task, tmp_path, "branch", worker_id=0
        )
        assert ok is True
        assert "disabled" in msg

    @pytest.mark.asyncio
    async def test_skipped_when_no_commits(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_diff_sanity_attempts = 1
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner, "_count_commits", new_callable=AsyncMock, return_value=0
        ):
            ok, msg = await runner._run_diff_sanity_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert ok is True
        assert "No commits" in msg

    @pytest.mark.asyncio
    async def test_passes_on_ok_result(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_diff_sanity_attempts = 1
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                return_value="+import os\n",
            ),
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                return_value="DIFF_SANITY_RESULT: OK\nSUMMARY: No issues found",
            ),
        ):
            ok, msg = await runner._run_diff_sanity_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert ok is True

    @pytest.mark.asyncio
    async def test_returns_false_on_retry(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_diff_sanity_attempts = 1
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                return_value="+print('debug')\n",
            ),
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                return_value="DIFF_SANITY_RESULT: RETRY\nSUMMARY: debug code",
            ),
        ):
            ok, msg = await runner._run_diff_sanity_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert ok is False
        assert "debug code" in msg

    @pytest.mark.asyncio
    async def test_run_fails_when_diff_sanity_fails(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """AgentRunner.run should return success=False when diff sanity fails."""
        config.max_diff_sanity_attempts = 1
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner, "_execute", new_callable=AsyncMock, return_value="transcript"
            ),
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                return_value="+print('debug')\n",
            ),
            patch.object(runner, "_save_transcript"),
        ):
            # Mock _execute to return RETRY for diff sanity (second call)
            runner._execute = AsyncMock(
                side_effect=[
                    "transcript",  # implementation run
                    "DIFF_SANITY_RESULT: RETRY\nSUMMARY: scope creep",
                ]
            )
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is False
        assert "Diff sanity" in (result.error or "")


class TestTestAdequacyLoop:
    """Tests for the test adequacy check skill integration."""

    @pytest.mark.asyncio
    async def test_skipped_when_disabled(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_test_adequacy_attempts = 0
        runner = AgentRunner(config, event_bus)
        ok, msg = await runner._run_test_adequacy_loop(
            agent_task, tmp_path, "branch", worker_id=0
        )
        assert ok is True
        assert "disabled" in msg

    @pytest.mark.asyncio
    async def test_skipped_when_no_commits(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_test_adequacy_attempts = 1
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner, "_count_commits", new_callable=AsyncMock, return_value=0
        ):
            ok, msg = await runner._run_test_adequacy_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert ok is True
        assert "No commits" in msg

    @pytest.mark.asyncio
    async def test_passes_on_ok_result(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_test_adequacy_attempts = 1
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                return_value="+def foo(): pass\n",
            ),
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                return_value="TEST_ADEQUACY_RESULT: OK\nSUMMARY: adequate",
            ),
        ):
            ok, msg = await runner._run_test_adequacy_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert ok is True

    @pytest.mark.asyncio
    async def test_returns_false_on_retry(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_test_adequacy_attempts = 1
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                return_value="+def foo(): pass\n",
            ),
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                return_value="TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: missing tests",
            ),
        ):
            ok, msg = await runner._run_test_adequacy_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert ok is False
        assert "missing tests" in msg


# ---------------------------------------------------------------------------
# AgentRunner.run — success path
# ---------------------------------------------------------------------------


class TestRunSuccess:
    """Tests for the happy path of AgentRunner.run."""

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
                return_value=(True, "OK"),
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
                return_value=(True, "OK"),
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
    """Tests for the salvage-commit mechanism (always runs on host)."""

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
    """Tests for failure paths of AgentRunner.run."""

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
                return_value=(False, "Quality failed"),
            ),
            patch.object(
                runner,
                "_run_quality_fix_loop",
                new_callable=AsyncMock,
                return_value=(False, "Still failing", 2),
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
                return_value=(False, "No commits found on branch"),
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
    """Tests for AgentRunner pre-quality review/correction loop."""

    @pytest.mark.asyncio
    async def test_skips_when_no_commits(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner, "_count_commits", new_callable=AsyncMock, return_value=0
        ):
            ok, msg, attempts = await runner._run_pre_quality_review_loop(
                agent_task, tmp_path, "agent/issue-42", worker_id=1
            )
        assert ok is True
        assert attempts == 0
        assert "Skipped" in msg

    @pytest.mark.asyncio
    async def test_retries_bounded_by_config(
        self, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        cfg = ConfigFactory.create(
            max_pre_quality_review_attempts=2,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
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
            ok, _msg, attempts = await runner._run_pre_quality_review_loop(
                agent_task, tmp_path, "agent/issue-42", worker_id=1
            )
        assert ok is False
        assert attempts == 2
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
                return_value=(False, "Quality failed"),
            ),
            patch.object(
                runner,
                "_run_quality_fix_loop",
                new_callable=AsyncMock,
                return_value=(True, "OK", 1),
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
                side_effect=ValueError("unexpected value"),
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
            worktree_base=tmp_path / "wt",
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
                return_value=(False, "Quality failed"),
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
    """Tests for dry-run behaviour of AgentRunner.run."""

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
            success, msg = await runner._verify_result(tmp_path, "agent/issue-42")

        assert success is False
        assert "commit" in msg.lower()

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
            success, msg = await runner._verify_result(tmp_path, "agent/issue-42")

        assert success is True
        assert msg == "OK"
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
            success, msg = await runner._verify_result(tmp_path, "agent/issue-42")

        assert success is False
        assert "make quality" in msg.lower()

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
            success, msg = await runner._verify_result(tmp_path, "agent/issue-42")

        assert success is False
        assert "type mismatch" in msg
        assert "pyright" in msg

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
            success, msg = await runner._verify_result(tmp_path, "agent/issue-42")

        assert success is False
        assert "make" in msg.lower()


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
                return_value=(True, "OK"),
            ),
        ):
            success, msg, attempts = await runner._run_quality_fix_loop(
                agent_task, tmp_path, "agent/issue-42", "initial error", worker_id=0
            )

        assert success is True
        assert msg == "OK"
        assert attempts == 1

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """Fix loop should succeed when second attempt passes quality."""
        runner = AgentRunner(config, event_bus)

        verify_results = iter([(False, "still failing"), (True, "OK")])

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
            success, msg, attempts = await runner._run_quality_fix_loop(
                agent_task, tmp_path, "agent/issue-42", "initial error", worker_id=0
            )

        assert success is True
        assert msg == "OK"
        assert attempts == 2

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
                return_value=(False, "still broken"),
            ),
        ):
            success, msg, attempts = await runner._run_quality_fix_loop(
                agent_task, tmp_path, "agent/issue-42", "initial error", worker_id=0
            )

        assert success is False
        assert "still broken" in msg
        assert attempts == 3

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
                return_value=(True, "OK"),
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
            success, msg, attempts = await runner._run_quality_fix_loop(
                agent_task, tmp_path, "agent/issue-42", "error", worker_id=0
            )

        assert success is False
        assert attempts == 0
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
                return_value=(True, "OK"),
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
                return_value=(True, "OK"),
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
                return_value=(True, "OK"),
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
                return_value=(True, "OK"),
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
                return_value=(True, "OK"),
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
                return_value=(True, "OK"),
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
# AgentRunner._execute — streaming
# ---------------------------------------------------------------------------


class TestTerminate:
    """Tests for AgentRunner.terminate."""

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

        with patch("runner_utils.os.killpg", side_effect=ProcessLookupError):
            runner.terminate()  # Should not raise

    def test_terminate_with_no_active_processes(
        self, config, event_bus: EventBus
    ) -> None:
        """terminate() with empty _active_procs should be a no-op."""
        runner = AgentRunner(config, event_bus)
        runner.terminate()  # Should not raise


class TestExecuteStreaming:
    """Tests for AgentRunner._execute with line-by-line streaming."""

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
    """Tests for AgentRunner._strip_plan_noise."""

    def test_removes_generated_by_footer(self) -> None:
        """Should remove the 'Generated by HydraFlow Planner' footer line."""
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
        """Should remove **Branch:** lines."""
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
        """Should remove HTML comments."""
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
        """Should extract only content between ## Implementation Plan and ---."""
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
        """Should work when there is no --- separator at the end."""
        raw = "## Implementation Plan\n\nStep 1: Do this\nStep 2: Do that"
        result = AgentRunner._strip_plan_noise(raw)
        assert "Step 1: Do this" in result
        assert "Step 2: Do that" in result

    def test_handles_empty_plan(self) -> None:
        """Should return empty string for comment with no plan content."""
        raw = "## Implementation Plan\n\n---\n*Generated by HydraFlow Planner*"
        result = AgentRunner._strip_plan_noise(raw)
        assert result == ""

    def test_preserves_plan_content_with_full_orchestrator_format(self) -> None:
        """Should correctly strip the orchestrator's exact comment format."""
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
    """Tests for AgentRunner._load_plan_fallback."""

    def test_returns_empty_when_file_missing(self, config, event_bus: EventBus) -> None:
        """Should return empty string when plan file does not exist."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = AgentRunner(config, event_bus)
        result = runner._load_plan_fallback(999)
        assert result == ""

    def test_loads_plan_from_file(self, config, event_bus: EventBus) -> None:
        """Should load and return plan content from .hydraflow/plans/issue-N.md."""
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
        """Should log a warning when falling back to plan file."""
        plan_dir = config.repo_root / ".hydraflow" / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "issue-42.md").write_text("# Plan for Issue #42\n\nPlan body\n")

        runner = AgentRunner(config, event_bus)
        with patch("agent.logger") as mock_logger:
            runner._load_plan_fallback(42)
        mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# AgentRunner._build_prompt — fallback and truncation
# ---------------------------------------------------------------------------


class TestBuildPromptFallbackAndTruncation:
    """Tests for plan fallback, body truncation, and test_command in _build_prompt."""

    def test_falls_back_to_plan_file(self, config, event_bus: EventBus) -> None:
        """When no plan comment exists, should fall back to .hydraflow/plans/."""
        plan_dir = config.repo_root / ".hydraflow" / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "issue-10.md").write_text(
            "# Plan for Issue #10\n\nStep 1: saved plan\n"
        )

        issue = Task(
            id=10,
            title="Feature X",
            body="Body text",
            comments=[],
        )
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(issue)
        assert "Step 1: saved plan" in prompt
        assert "Follow this plan closely" in prompt

    def test_logs_error_when_no_plan_found(self, config, event_bus: EventBus) -> None:
        """Should log error when neither comment nor file has a plan."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        issue = Task(
            id=10,
            title="Feature X",
            body="Body text",
            comments=[],
        )
        runner = AgentRunner(config, event_bus)
        with patch("agent.logger") as mock_logger:
            prompt = runner._build_prompt(issue)
        mock_logger.error.assert_called_once()
        # Should still produce a valid prompt without a plan section
        assert "Follow this plan closely" not in prompt
        assert "## Instructions" in prompt

    def test_truncates_long_body(self, config, event_bus: EventBus) -> None:
        """Body exceeding max_issue_body_chars should be truncated with a note."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        long_body = "x" * 15_000
        issue = Task(
            id=10,
            title="Feature X",
            body=long_body,
            comments=[],
        )
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(issue)
        assert "x" * 10_000 in prompt
        assert "x" * 15_000 not in prompt
        assert "Body truncated" in prompt

    def test_preserves_short_body(self, config, event_bus: EventBus) -> None:
        """Body under max_issue_body_chars should pass through unchanged."""
        config.repo_root.mkdir(parents=True, exist_ok=True)
        short_body = "This is a short body."
        issue = Task(
            id=10,
            title="Feature X",
            body=short_body,
            comments=[],
        )
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(issue)
        assert short_body in prompt
        assert "Body truncated" not in prompt

    def test_uses_configured_test_command(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Prompt should use test_command from config."""
        cfg = ConfigFactory.create(
            test_command="npm test",
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
        issue = Task(
            id=10,
            title="Feature X",
            body="Body text",
            comments=[],
        )
        runner = AgentRunner(cfg, event_bus)
        prompt = runner._build_prompt(issue)
        assert "npm test" in prompt
        assert "make test-fast" not in prompt

    def test_default_test_command_is_make_test(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Default test_command should produce 'make test' in the prompt."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_prompt(agent_task)
        assert "`make test`" in prompt


# ---------------------------------------------------------------------------
# AgentRunner._verify_result — timeout
# ---------------------------------------------------------------------------


class TestVerifyResultTimeout:
    """Tests for _verify_result timeout behavior."""

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
            success, msg = await runner._verify_result(tmp_path, "agent/issue-42")

        assert success is False
        assert "timed out" in msg

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
    """Tests for _count_commits timeout behavior."""

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
# AgentRunner._build_prompt — runtime log injection
# ---------------------------------------------------------------------------


class TestBuildPromptRuntimeLogs:
    """Tests for runtime log injection in _build_prompt."""

    def test_prompt_includes_runtime_logs_when_enabled(
        self, tmp_path: Path, event_bus: EventBus
    ) -> None:
        """When inject_runtime_logs is True and logs exist, prompt includes them."""
        config = ConfigFactory.create(
            inject_runtime_logs=True,
            repo_root=tmp_path,
        )
        # Create a log file
        log_dir = tmp_path / ".hydraflow" / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "hydraflow.log").write_text("INFO: server started\nERROR: timeout\n")

        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        with (
            patch("base_runner.load_project_manifest", return_value=""),
            patch("base_runner.load_memory_digest", return_value=""),
        ):
            prompt = runner._build_prompt(issue)

        assert "## Recent Application Logs" in prompt
        assert "ERROR: timeout" in prompt

    def test_prompt_excludes_runtime_logs_when_disabled(
        self, config, event_bus: EventBus
    ) -> None:
        """Default config does not include runtime logs."""
        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        with (
            patch("base_runner.load_project_manifest", return_value=""),
            patch("base_runner.load_memory_digest", return_value=""),
        ):
            prompt = runner._build_prompt(issue)

        assert "## Recent Application Logs" not in prompt

    def test_prompt_excludes_runtime_logs_when_empty(
        self, tmp_path: Path, event_bus: EventBus
    ) -> None:
        """Enabled but no log file — no log section in prompt."""
        config = ConfigFactory.create(
            inject_runtime_logs=True,
            repo_root=tmp_path,
        )
        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        with (
            patch("base_runner.load_project_manifest", return_value=""),
            patch("base_runner.load_memory_digest", return_value=""),
        ):
            prompt = runner._build_prompt(issue)

        assert "## Recent Application Logs" not in prompt


# ---------------------------------------------------------------------------
# Prior failure section in prompt
# ---------------------------------------------------------------------------


class TestPriorFailureInPrompt:
    """Tests that prior_failure is included in the implementation prompt."""

    def test_prior_failure_included_in_prompt(
        self, config, event_bus: EventBus
    ) -> None:
        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        with (
            patch("base_runner.load_project_manifest", return_value=""),
            patch("base_runner.load_memory_digest", return_value=""),
        ):
            prompt = runner._build_prompt(
                issue,
                prior_failure="TDD red phase modified non-test files: docs/adr/001.md",
            )

        assert "## Prior Attempt Failure" in prompt
        assert "TDD red phase modified non-test files: docs/adr/001.md" in prompt
        assert "Avoid repeating the same mistake" in prompt

    def test_no_prior_failure_section_when_empty(
        self, config, event_bus: EventBus
    ) -> None:
        runner = AgentRunner(config, event_bus)
        issue = TaskFactory.create()

        with (
            patch("base_runner.load_project_manifest", return_value=""),
            patch("base_runner.load_memory_digest", return_value=""),
        ):
            prompt = runner._build_prompt(issue, prior_failure="")

        assert "## Prior Attempt Failure" not in prompt
