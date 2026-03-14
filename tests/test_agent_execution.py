"""Tests for agent — execution."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, patch

import pytest

from agent import AgentRunner
from base_runner import BaseRunner
from events import EventBus
from models import ReviewVerdict
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


@pytest.fixture
def agent_task():
    return TaskFactory.create()


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
# AgentRunner._build_prompt_with_stats
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """Tests for AgentRunner._build_prompt_with_stats."""

    def test_prompt_includes_issue_number(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should reference the issue number."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert str(agent_task.id) in prompt

    def test_prompt_includes_title(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include the issue title."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert agent_task.title in prompt

    def test_prompt_includes_body(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include the issue body text."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert agent_task.body in prompt

    def test_prompt_includes_rules(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should contain the mandatory rules section."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "Rules" in prompt or "rules" in prompt.lower()

    def test_prompt_references_make_quality(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should instruct the agent to run make quality."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "make quality" in prompt

    def test_prompt_does_not_reference_make_test_fast(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should not reference make test-fast anywhere (replaced by configurable test_command)."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "make test-fast" not in prompt

    def test_prompt_includes_comments_section_when_comments_exist(
        self, config, event_bus: EventBus
    ) -> None:
        """Prompt should include a Discussion section when the issue has comments."""
        issue_with_comments = TaskFactory.create(
            id=10,
            title="Add feature X",
            body="We need feature X",
            comments=["Please also handle edge case Y", "What about Z?"],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(issue_with_comments)

        assert "Discussion" in prompt
        assert "Please also handle edge case Y" in prompt
        assert "What about Z?" in prompt

    def test_prompt_omits_comments_section_when_no_comments(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should not include a Discussion section when there are no comments."""
        # Default agent_task fixture has empty comments
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "Discussion" not in prompt

    def test_prompt_extracts_plan_comment_as_dedicated_section(
        self, config, event_bus: EventBus
    ) -> None:
        """When a comment contains '## Implementation Plan', it should be rendered
        as a dedicated plan section with follow-this-plan instruction."""
        issue = TaskFactory.create(
            id=10,
            title="Add feature X",
            body="We need feature X",
            comments=[
                "## Implementation Plan\n\nStep 1: Do this\nStep 2: Do that\n\n---\n*Generated by HydraFlow Planner*",
                "Please also handle edge case Y",
            ],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(issue)

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
        issue = TaskFactory.create(
            id=10,
            title="Add feature X",
            body="We need feature X",
            comments=[
                "## Implementation Plan\n\nStep 1: Do this",
            ],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(issue)

        # Plan is in dedicated section, no Discussion section at all
        assert "## Implementation Plan" in prompt
        assert "Discussion" not in prompt

    def test_prompt_no_plan_section_when_no_plan_comment(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """When no comment contains a plan, no plan section should appear."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)

        assert "Follow this plan closely" not in prompt

    def test_prompt_uses_tdd_subagent_instructions_for_task_graph(
        self, config, event_bus: EventBus
    ) -> None:
        """When plan has Task Graph, prompt has concrete per-phase sub-agent instructions."""
        issue = TaskFactory.create(
            id=10,
            title="Add widget feature",
            body="We need widgets",
            comments=[
                "## Implementation Plan\n\n## Task Graph\n\n"
                "### P1 \u2014 Model\n**Files:** src/models.py\n"
                "**Tests:**\n- Widget persists\n**Depends on:** (none)\n\n"
                "### P2 \u2014 API\n**Files:** src/api.py\n"
                "**Tests:**\n- GET returns list\n**Depends on:** P1\n",
            ],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(issue)

        # Header and structure
        assert "TDD Sub-Agent Isolation" in prompt
        assert "Agent tool" in prompt

        # Concrete parsed phase content
        assert "Phase 1: P1" in prompt
        assert "Phase 2: P2" in prompt
        assert "`src/models.py`" in prompt
        assert "`src/api.py`" in prompt
        assert "Widget persists" in prompt
        assert "GET returns list" in prompt

        # Sub-agent steps per phase
        assert "RED sub-agent" in prompt
        assert "GREEN sub-agent" in prompt
        assert "REFACTOR sub-agent" in prompt

        # Max fix attempts from config
        assert "max 4 attempts" in prompt

        # Dependency ordering: P1 appears before P2
        p1_pos = prompt.index("Phase 1: P1")
        p2_pos = prompt.index("Phase 2: P2")
        assert p1_pos < p2_pos

        # Old generic instructions NOT present
        assert "Execute phases in order" not in prompt

    def test_prompt_uses_standard_instructions_when_plan_has_no_task_graph(
        self, config, event_bus: EventBus
    ) -> None:
        """When the plan has no Task Graph, the standard follow-plan instruction is used."""
        issue = TaskFactory.create(
            id=10,
            title="Fix bug",
            body="Something is broken",
            comments=[
                "## Implementation Plan\n\nStep 1: Fix the thing\nStep 2: Test it\n",
            ],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(issue)

        assert "Follow this plan closely" in prompt
        assert "Execute phases in order" not in prompt

    def test_prompt_includes_ui_guidelines(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include UI guidelines for component reuse and responsive design."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
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
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "push" in prompt.lower() or "Do NOT push" in prompt
        assert "pull request" in prompt.lower() or "pr create" in prompt.lower()

    def test_prompt_forbids_interactive_git(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should forbid interactive git commands (no TTY in Docker)."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
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
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "## Common Review Feedback" in prompt
        assert "Missing or insufficient test coverage" in prompt

    def test_prompt_includes_escalation_block_when_threshold_met(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include mandatory escalation block when patterns exceed threshold."""
        from review_insights import ReviewInsightStore, ReviewRecord

        store = ReviewInsightStore(config.repo_root / ".hydraflow" / "memory")
        for i in range(3):
            store.append_review(
                ReviewRecord(
                    pr_number=200 + i,
                    issue_number=50 + i,
                    timestamp="2026-02-20T11:00:00Z",
                    verdict=ReviewVerdict.REQUEST_CHANGES,
                    summary="Missing coverage",
                    fixes_made=False,
                    categories=["missing_tests"],
                )
            )

        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "Mandatory Requirements: Test Coverage" in prompt
        assert "missing or insufficient test coverage" in prompt

    def test_prompt_omits_escalation_below_threshold(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        from review_insights import ReviewInsightStore, ReviewRecord

        store = ReviewInsightStore(config.repo_root / ".hydraflow" / "memory")
        # Below default threshold of 3
        for i in range(2):
            store.append_review(
                ReviewRecord(
                    pr_number=300 + i,
                    issue_number=70 + i,
                    timestamp="2026-02-22T11:00:00Z",
                    verdict=ReviewVerdict.REQUEST_CHANGES,
                    summary="Missing coverage",
                    fixes_made=False,
                    categories=["missing_tests"],
                )
            )

        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "Mandatory Requirements" not in prompt
        assert "## Common Review Feedback" in prompt

    def test_prompt_includes_new_self_check_items(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include the new dead-code and failure-path checklist items."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "New code is reachable" in prompt
        assert "Tests verify issue requirements" in prompt
        assert "Failure paths are tested" in prompt

    def test_prompt_works_without_review_data(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should work normally when no review data exists."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "## Common Review Feedback" not in prompt
        # The rest of the prompt should still be there
        assert "## Instructions" in prompt
        assert "## Rules" in prompt

    def test_prompt_truncates_long_discussion_comments(
        self, config, event_bus: EventBus
    ) -> None:
        issue = TaskFactory.create(
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
        prompt, _ = runner._build_prompt_with_stats(
            agent_task, review_feedback=feedback
        )
        assert "## Review Feedback" in prompt
        assert "Missing error handling in the parse_config function" in prompt
        assert "reviewer rejected" in prompt.lower()

    def test_prompt_omits_review_feedback_when_empty(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should not include Review Feedback section when feedback is empty."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task, review_feedback="")
        assert "## Review Feedback" not in prompt

    def test_prompt_review_feedback_after_plan_section(
        self, config, event_bus: EventBus
    ) -> None:
        """Review feedback should appear after the plan section."""
        issue = TaskFactory.create(
            id=10,
            title="Add feature X",
            body="We need feature X",
            comments=[
                "## Implementation Plan\n\nStep 1: Do this\nStep 2: Do that",
            ],
        )
        runner = AgentRunner(config, event_bus)
        feedback = "Tests are missing for edge cases"
        prompt, _ = runner._build_prompt_with_stats(issue, review_feedback=feedback)

        plan_pos = prompt.index("## Implementation Plan")
        feedback_pos = prompt.index("## Review Feedback")
        instructions_pos = prompt.index("## Instructions")

        assert plan_pos < feedback_pos < instructions_pos

    def test_prompt_includes_self_check_checklist(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt should include the self-check checklist section."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
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
        prompt, _ = runner._build_prompt_with_stats(agent_task)
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
            prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "## Mandatory Requirements" in prompt
        assert "Every new function MUST have a test" in prompt

    def test_prompt_no_mandatory_block_when_no_escalations(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """When no escalations, prompt should not include mandatory block."""
        runner = AgentRunner(config, event_bus)
        with patch.object(runner, "_get_escalation_data", return_value=[]):
            prompt, _ = runner._build_prompt_with_stats(agent_task)
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
            prompt, _ = runner._build_prompt_with_stats(agent_task)
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

    def test_pre_quality_review_checks_logic_errors(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Pre-quality review should check for logic errors."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_pre_quality_review_prompt(agent_task, attempt=1)
        assert "logic errors" in prompt

    def test_pre_quality_review_checks_failure_paths(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Pre-quality review should verify failure paths are tested."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_pre_quality_review_prompt(agent_task, attempt=1)
        assert "failure/error paths" in prompt

    def test_pre_quality_review_checks_missing_implementation(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Pre-quality review should check for gaps vs plan/issue description."""
        runner = AgentRunner(config, event_bus)
        prompt = runner._build_pre_quality_review_prompt(agent_task, attempt=1)
        assert "is anything missing" in prompt

    def test_prompt_includes_test_step(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Implementation prompt should include a test-writing step."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "Write tests" in prompt
        assert "prevent regressions" in prompt

    def test_self_check_includes_dead_code_check(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Self-check checklist should verify no dead code is introduced."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "New code is reachable" in prompt
        assert "dead code" in prompt

    def test_self_check_includes_issue_requirements_check(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Self-check checklist should verify tests match issue requirements."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
        assert "Tests verify issue requirements" in prompt

    def test_prompt_forbids_already_satisfied(
        self, config, event_bus: EventBus, agent_task
    ) -> None:
        """Prompt must instruct agent to never claim issue is already satisfied."""
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(agent_task)
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
        result = await runner._run_diff_sanity_loop(
            agent_task, tmp_path, "branch", worker_id=0
        )
        assert result.passed is True
        assert "disabled" in result.summary

    @pytest.mark.asyncio
    async def test_skipped_when_no_commits(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_diff_sanity_attempts = 1
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner, "_count_commits", new_callable=AsyncMock, return_value=0
        ):
            result = await runner._run_diff_sanity_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert result.passed is True
        assert "No commits" in result.summary

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
            result = await runner._run_diff_sanity_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert result.passed is True

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
            result = await runner._run_diff_sanity_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert result.passed is False
        assert "debug code" in result.summary
        assert result.attempts == 1

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

    @pytest.mark.asyncio
    async def test_recovers_on_second_attempt(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """_run_diff_sanity_loop should recover if a later attempt returns OK."""
        config.max_diff_sanity_attempts = 2
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
                side_effect=[
                    "DIFF_SANITY_RESULT: RETRY\nSUMMARY: debug code",
                    "DIFF_SANITY_RESULT: OK\nSUMMARY: No issues found",
                ],
            ),
        ):
            result = await runner._run_diff_sanity_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert result.passed is True
        assert result.attempts == 2


class TestTestAdequacyLoop:
    """Tests for the test adequacy check skill integration."""

    @pytest.mark.asyncio
    async def test_skipped_when_disabled(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_test_adequacy_attempts = 0
        runner = AgentRunner(config, event_bus)
        result = await runner._run_test_adequacy_loop(
            agent_task, tmp_path, "branch", worker_id=0
        )
        assert result.passed is True
        assert "disabled" in result.summary

    @pytest.mark.asyncio
    async def test_skipped_when_no_commits(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_test_adequacy_attempts = 1
        runner = AgentRunner(config, event_bus)
        with patch.object(
            runner, "_count_commits", new_callable=AsyncMock, return_value=0
        ):
            result = await runner._run_test_adequacy_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert result.passed is True
        assert "No commits" in result.summary

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
            result = await runner._run_test_adequacy_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert result.passed is True

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
            result = await runner._run_test_adequacy_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert result.passed is False
        assert "missing tests" in result.summary
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_recovers_on_second_attempt(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """_run_test_adequacy_loop should recover if a later attempt returns OK."""
        config.max_test_adequacy_attempts = 2
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
                side_effect=[
                    "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: missing tests",
                    "TEST_ADEQUACY_RESULT: OK\nSUMMARY: coverage sufficient",
                ],
            ),
        ):
            result = await runner._run_test_adequacy_loop(
                agent_task, tmp_path, "branch", worker_id=0
            )
        assert result.passed is True
        assert result.attempts == 2
