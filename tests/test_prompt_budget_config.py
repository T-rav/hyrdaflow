"""Tests for prompt budget configuration fields (issue #2578).

Verifies that hardcoded prompt/truncation limits are now configurable
via HydraFlowConfig and that runner classes read from config.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import HydraFlowConfig
from tests.conftest import IssueFactory, PRInfoFactory, TaskFactory
from tests.helpers import ConfigFactory
from verification import format_verification_issue_body

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestPromptBudgetDefaults:
    """All 12 new config fields have the expected defaults."""

    @pytest.fixture
    def cfg(self, tmp_path: Path) -> HydraFlowConfig:
        return ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )

    def test_max_discussion_comment_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_discussion_comment_chars == 500

    def test_max_common_feedback_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_common_feedback_chars == 2_000

    def test_max_impl_plan_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_impl_plan_chars == 6_000

    def test_max_review_feedback_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_review_feedback_chars == 2_000

    def test_max_planner_comment_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_planner_comment_chars == 1_000

    def test_max_planner_line_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_planner_line_chars == 500

    def test_max_planner_failed_plan_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_planner_failed_plan_chars == 4_000

    def test_max_hitl_correction_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_hitl_correction_chars == 4_000

    def test_max_hitl_cause_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_hitl_cause_chars == 2_000

    def test_max_ci_log_prompt_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_ci_log_prompt_chars == 6_000

    def test_max_unsticker_cause_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_unsticker_cause_chars == 3_000

    def test_max_verification_instructions_chars(self, cfg: HydraFlowConfig) -> None:
        assert cfg.max_verification_instructions_chars == 50_000


# ---------------------------------------------------------------------------
# Config overrides propagate to runners
# ---------------------------------------------------------------------------


class TestPromptBudgetOverrides:
    """Overridden config values are used by runner classes."""

    def test_custom_values_accepted(self, tmp_path: Path) -> None:
        """All 12 fields accept non-default values via constructor."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_discussion_comment_chars=1_000,
            max_common_feedback_chars=4_000,
            max_impl_plan_chars=12_000,
            max_review_feedback_chars=4_000,
            max_planner_comment_chars=2_000,
            max_planner_line_chars=1_000,
            max_planner_failed_plan_chars=8_000,
            max_hitl_correction_chars=8_000,
            max_hitl_cause_chars=4_000,
            max_ci_log_prompt_chars=12_000,
            max_unsticker_cause_chars=6_000,
            max_verification_instructions_chars=30_000,
        )
        assert cfg.max_discussion_comment_chars == 1_000
        assert cfg.max_common_feedback_chars == 4_000
        assert cfg.max_impl_plan_chars == 12_000
        assert cfg.max_review_feedback_chars == 4_000
        assert cfg.max_planner_comment_chars == 2_000
        assert cfg.max_planner_line_chars == 1_000
        assert cfg.max_planner_failed_plan_chars == 8_000
        assert cfg.max_hitl_correction_chars == 8_000
        assert cfg.max_hitl_cause_chars == 4_000
        assert cfg.max_ci_log_prompt_chars == 12_000
        assert cfg.max_unsticker_cause_chars == 6_000
        assert cfg.max_verification_instructions_chars == 30_000


# ---------------------------------------------------------------------------
# AgentRunner uses config values
# ---------------------------------------------------------------------------


class TestAgentRunnerUsesConfig:
    """AgentRunner reads truncation limits from config, not class constants."""

    def test_truncate_comment_uses_config(self, tmp_path: Path) -> None:
        """_truncate_comment_for_prompt respects max_discussion_comment_chars."""
        from agent import AgentRunner
        from events import EventBus

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_discussion_comment_chars=100,
        )
        runner = AgentRunner(cfg, EventBus())
        long_comment = "A" * 500

        result = runner._truncate_comment_for_prompt(long_comment)

        assert len(result.splitlines()[0]) <= 100
        assert "truncated" in result.lower()

    def test_truncate_comment_no_truncation_when_short(self, tmp_path: Path) -> None:
        """Short comments are returned unchanged."""
        from agent import AgentRunner
        from events import EventBus

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_discussion_comment_chars=500,
        )
        runner = AgentRunner(cfg, EventBus())
        short_comment = "Fix the bug"

        result = runner._truncate_comment_for_prompt(short_comment)

        assert result == short_comment

    def test_build_prompt_truncates_impl_plan(self, tmp_path: Path) -> None:
        """_build_prompt_with_stats truncates plan via max_impl_plan_chars."""
        from agent import AgentRunner
        from events import EventBus

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_impl_plan_chars=1_000,
        )
        runner = AgentRunner(cfg, EventBus())
        long_plan = "## Implementation Plan\n" + "- Implement feature X\n" * 200
        issue = TaskFactory.create(comments=[long_plan])

        prompt, _stats = runner._build_prompt_with_stats(issue)

        # The full plan should be summarized, not included verbatim
        assert long_plan not in prompt
        assert "summarized" in prompt.lower()

    def test_build_prompt_truncates_review_feedback(self, tmp_path: Path) -> None:
        """_build_prompt_with_stats truncates review feedback via max_review_feedback_chars."""
        from agent import AgentRunner
        from events import EventBus

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_review_feedback_chars=100,
        )
        runner = AgentRunner(cfg, EventBus())
        long_feedback = "- Fix error handling\n" * 100
        issue = TaskFactory.create()

        prompt, _stats = runner._build_prompt_with_stats(
            issue, review_feedback=long_feedback
        )

        # The full feedback should be summarized, not included verbatim
        assert long_feedback not in prompt
        assert "summarized" in prompt.lower()


# ---------------------------------------------------------------------------
# PlannerRunner uses config values
# ---------------------------------------------------------------------------


class TestPlannerRunnerUsesConfig:
    """PlannerRunner reads truncation limits from config."""

    def test_truncate_text_uses_config_line_limit(self, tmp_path: Path) -> None:
        """_truncate_text uses max_planner_line_chars from config."""
        from events import EventBus
        from planner import PlannerRunner

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_planner_line_chars=100,
            max_planner_comment_chars=1_000,
        )
        runner = PlannerRunner(cfg, EventBus())

        long_line = "X" * 500
        result = runner._truncate_text(
            long_line,
            cfg.max_planner_comment_chars,
            cfg.max_planner_line_chars,
        )

        # Line should be capped at 100 chars + ellipsis
        first_line = result.splitlines()[0]
        assert len(first_line) <= 101  # 100 + "…"

    def test_retry_prompt_uses_failed_plan_config(self, tmp_path: Path) -> None:
        """_build_retry_prompt truncates failed plan per max_planner_failed_plan_chars."""
        from events import EventBus
        from planner import PlannerRunner

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_planner_failed_plan_chars=500,
            max_planner_line_chars=500,
        )
        runner = PlannerRunner(cfg, EventBus())
        long_plan = "Step 1: Do something\n" * 200
        issue = TaskFactory.create()

        prompt, _ = runner._build_retry_prompt(
            issue, long_plan, ["Missing section: Files to Modify"]
        )

        # The full plan should be truncated
        assert long_plan not in prompt


# ---------------------------------------------------------------------------
# HITLRunner uses config values
# ---------------------------------------------------------------------------


class TestHITLRunnerUsesConfig:
    """HITLRunner reads truncation limits from config."""

    def test_prompt_truncates_cause_per_config(self, tmp_path: Path) -> None:
        """_build_prompt_with_stats respects max_hitl_cause_chars."""
        from events import EventBus
        from hitl_runner import HITLRunner

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_hitl_cause_chars=100,
        )
        runner = HITLRunner(cfg, EventBus())
        issue = IssueFactory.create(number=42, title="Fix widget")

        prompt, _ = runner._build_prompt_with_stats(issue, "Try this fix", "A" * 500)

        # The cause should be truncated — the full 500-char cause should not appear
        assert "A" * 500 not in prompt

    def test_prompt_truncates_correction_per_config(self, tmp_path: Path) -> None:
        """_build_prompt_with_stats respects max_hitl_correction_chars."""
        from events import EventBus
        from hitl_runner import HITLRunner

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_hitl_correction_chars=500,
        )
        runner = HITLRunner(cfg, EventBus())
        issue = IssueFactory.create(number=42, title="Fix widget")

        prompt, _ = runner._build_prompt_with_stats(issue, "B" * 2000, "CI failed")

        # The correction should be truncated
        assert "B" * 2000 not in prompt


# ---------------------------------------------------------------------------
# ReviewRunner uses config values
# ---------------------------------------------------------------------------


class TestReviewRunnerUsesConfig:
    """ReviewRunner reads CI log prompt limit from config."""

    def test_ci_log_truncation_uses_config(self, tmp_path: Path) -> None:
        """_build_ci_fix_prompt truncates CI logs per max_ci_log_prompt_chars."""
        from events import EventBus
        from reviewer import ReviewRunner

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            max_ci_log_prompt_chars=1_000,
        )
        runner = ReviewRunner(cfg, EventBus())
        pr = PRInfoFactory.create()
        task = TaskFactory.create()

        prompt, _ = runner._build_ci_fix_prompt(
            pr, task, "Some failure", 1, ci_logs="L" * 5_000
        )

        # Full 5000-char logs should not appear; should be truncated
        assert "L" * 5_000 not in prompt
        assert "truncated" in prompt.lower()


# ---------------------------------------------------------------------------
# verification.py uses max_instructions_chars parameter
# ---------------------------------------------------------------------------


class TestVerificationMaxInstructions:
    """format_verification_issue_body respects max_instructions_chars param."""

    def test_default_truncation(self) -> None:
        """Long instructions are truncated at the default limit."""
        from models import JudgeResult

        judge = JudgeResult(
            issue_number=1,
            pr_number=2,
            criteria=[],
            verification_instructions="X" * 60_000,
            summary="ok",
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(judge, issue, pr)

        assert "...truncated" in body

    def test_custom_truncation_limit(self) -> None:
        """Custom max_instructions_chars is honoured."""
        from models import JudgeResult

        judge = JudgeResult(
            issue_number=1,
            pr_number=2,
            criteria=[],
            verification_instructions="Y" * 500,
            summary="ok",
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(
            judge, issue, pr, max_instructions_chars=100
        )

        assert "...truncated" in body
        # The full 500 "Y"s should not appear
        assert "Y" * 500 not in body

    def test_no_truncation_when_under_limit(self) -> None:
        """Instructions under the limit are not truncated."""
        from models import JudgeResult

        instructions = "Check the output"
        judge = JudgeResult(
            issue_number=1,
            pr_number=2,
            criteria=[],
            verification_instructions=instructions,
            summary="ok",
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(
            judge, issue, pr, max_instructions_chars=1_000
        )

        assert instructions in body
        assert "truncated" not in body
