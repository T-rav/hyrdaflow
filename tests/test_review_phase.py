"""Tests for review_phase.py - ReviewPhase class."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from events import EventType
from models import (
    ConflictResolutionResult,
    CriterionResult,
    CriterionVerdict,
    JudgeResult,
    JudgeVerdict,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    Task,
    VerificationCriterion,
)
from review_phase import ReviewPhase
from tests.conftest import (
    PRInfoFactory,
    ReviewResultFactory,
    TaskFactory,
)
from tests.helpers import make_review_phase

# ---------------------------------------------------------------------------
# review_prs
# ---------------------------------------------------------------------------


class TestReviewPRs:
    """Tests for the ReviewPhase.review_prs method."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_prs(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        results = await phase.review_prs([], [TaskFactory.create()])
        assert results == []

    @pytest.mark.asyncio
    async def test_reviews_non_draft_prs(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        # Ensure worktree path exists
        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        phase._reviewers.review.assert_awaited_once()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_marks_pr_status_in_state(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.to_dict()["reviewed_prs"].get(str(101)) == "approve"

    @pytest.mark.asyncio
    async def test_reviewer_concurrency_limited_by_config_max_reviewers(
        self, config: HydraFlowConfig
    ) -> None:
        """At most config.max_reviewers concurrent reviews."""
        concurrency_counter = {"current": 0, "peak": 0}

        async def fake_review(pr, issue, wt_path, diff, worker_id=0):
            concurrency_counter["current"] += 1
            concurrency_counter["peak"] = max(
                concurrency_counter["peak"],
                concurrency_counter["current"],
            )
            await asyncio.sleep(0)
            concurrency_counter["current"] -= 1
            return ReviewResultFactory.create(
                pr_number=pr.number, issue_number=issue.id
            )

        phase = make_review_phase(config)
        phase._reviewers.review = fake_review  # type: ignore[method-assign]

        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        issues = [TaskFactory.create(id=i) for i in range(1, 7)]
        prs = [
            PRInfoFactory.create(number=100 + i, issue_number=i) for i in range(1, 7)
        ]

        for i in range(1, 7):
            wt = config.worktree_base / f"issue-{i}"
            wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs(prs, issues)

        assert concurrency_counter["peak"] <= config.max_reviewers

    @pytest.mark.asyncio
    async def test_returns_comment_verdict_when_issue_missing(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        # PR with issue_number not in issue_map
        pr = PRInfoFactory.create(issue_number=999)

        phase._prs.get_pr_diff = AsyncMock(return_value="diff")

        # Worktree for issue-999 exists
        wt = config.worktree_base / "issue-999"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [])  # no matching issues

        assert len(results) == 1
        assert results[0].pr_number == 101
        assert results[0].summary == "Issue not found"

    @pytest.mark.asyncio
    async def test_review_merges_approved_pr(self, config: HydraFlowConfig) -> None:
        """review_prs should merge PRs that the reviewer approves."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        phase._prs.merge_pr.assert_awaited_once_with(101)

    @pytest.mark.asyncio
    async def test_review_does_not_merge_rejected_pr(
        self, config: HydraFlowConfig
    ) -> None:
        """review_prs should not merge PRs with REQUEST_CHANGES verdict."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                verdict=ReviewVerdict.REQUEST_CHANGES
            )
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        phase._prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_merges_main_before_reviewing(
        self, config: HydraFlowConfig
    ) -> None:
        """review_prs should merge main and push before reviewing."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        phase._worktrees.merge_main.assert_awaited_once()
        phase._prs.push_branch.assert_awaited()
        phase._reviewers.review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_review_merge_conflict_escalates_to_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails and agent can't resolve, should escalate to HITL."""
        mock_agents = AsyncMock()
        mock_agents._verify_result = AsyncMock(return_value=(False, ""))
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)  # Conflicts
        # Agent resolution also fails
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        assert "conflicts" in results[0].summary.lower()
        # Review should NOT have been called
        phase._reviewers.review.assert_not_awaited()
        # Should escalate to HITL via transition
        phase._prs.transition.assert_awaited_once_with(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_review_conflict_escalation_records_hitl_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """Merge conflict escalation should record review_label as HITL origin."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, ""))
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"

    @pytest.mark.asyncio
    async def test_review_conflict_escalation_sets_hitl_cause(
        self, config: HydraFlowConfig
    ) -> None:
        """Merge conflict escalation should record cause in state."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, ""))
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_cause(42) == "Merge conflict with main branch"

    @pytest.mark.asyncio
    async def test_review_merge_conflict_resolved_by_agent(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails but agent resolves conflicts, review should proceed."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)  # Conflicts
        # But agent resolves them
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        # Agent resolved conflicts, so review should proceed and merge
        phase._reviewers.review.assert_awaited_once()
        assert results[0].merged is True

    @pytest.mark.asyncio
    async def test_review_merge_conflict_no_agent_escalates(
        self, config: HydraFlowConfig
    ) -> None:
        """When no agent runner is configured, conflicts escalate directly to HITL."""
        phase = make_review_phase(config)  # No agents passed
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        assert "conflicts" in results[0].summary.lower()
        phase._prs.transition.assert_awaited_once_with(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_review_merge_failure_escalates_to_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails after successful merge-main, should escalate to HITL."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        hitl_calls = [
            c
            for c in phase._prs.post_pr_comment.call_args_list
            if "Merge failed" in str(c)
        ]
        assert len(hitl_calls) == 1
        phase._prs.transition.assert_any_await(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_review_merge_failure_records_hitl_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """Merge failure escalation should record review_label as HITL origin."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"

    @pytest.mark.asyncio
    async def test_review_merge_failure_sets_hitl_cause(
        self, config: HydraFlowConfig
    ) -> None:
        """Merge failure escalation should record cause in state."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_cause(42) == "PR merge failed on GitHub"

    @pytest.mark.asyncio
    async def test_review_merge_records_lifetime_stats(
        self, config: HydraFlowConfig
    ) -> None:
        """Merging a PR should record both pr_merged and issue_completed."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.pull_main = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.prs_merged == 1
        assert stats.issues_completed == 1

    @pytest.mark.asyncio
    async def test_review_merge_labels_issue_hydraflow_fixed(
        self, config: HydraFlowConfig
    ) -> None:
        """Merging a PR should swap label from hydraflow-review to hydraflow-fixed."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should swap to hydraflow-fixed
        phase._prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-fixed")

    @pytest.mark.asyncio
    async def test_review_merge_failure_does_not_record_lifetime_stats(
        self, config: HydraFlowConfig
    ) -> None:
        """Failed merge should not increment lifetime stats."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.prs_merged == 0
        assert stats.issues_completed == 0

    @pytest.mark.asyncio
    async def test_review_merge_marks_issue_as_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Successful merge should mark issue status as 'merged'."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "merged"

    @pytest.mark.asyncio
    async def test_review_merge_failure_keeps_reviewed_status(
        self, config: HydraFlowConfig
    ) -> None:
        """Failed merge should leave issue as 'reviewed', not 'merged'."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "reviewed"

    @pytest.mark.asyncio
    async def test_review_posts_pr_comment_with_summary(
        self, config: HydraFlowConfig
    ) -> None:
        """post_pr_comment should be called with the review summary."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create()

        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        phase._prs.post_pr_comment.assert_awaited_once_with(101, "Looks good.")

    @pytest.mark.asyncio
    async def test_review_skips_submit_review_for_approve(
        self, config: HydraFlowConfig
    ) -> None:
        """submit_review should NOT be called for approve to avoid self-approval errors."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create()

        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        phase._prs.submit_review.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "verdict",
        [ReviewVerdict.REQUEST_CHANGES, ReviewVerdict.COMMENT],
    )
    async def test_review_submits_review_for_non_approve_verdicts(
        self, config: HydraFlowConfig, verdict: ReviewVerdict
    ) -> None:
        """submit_review should be called for request-changes and comment verdicts."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create(verdict=verdict)

        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        phase._prs.submit_review.assert_awaited_once_with(101, verdict, "Looks good.")

    @pytest.mark.asyncio
    async def test_review_request_changes_self_review_falls_back_gracefully(
        self, config: HydraFlowConfig
    ) -> None:
        """When submit_review raises SelfReviewError, state should still be marked."""
        from pr_manager import SelfReviewError

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock(
            side_effect=SelfReviewError(
                "Can not request changes on your own pull request"
            )
        )

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert len(results) == 1
        # PR should still be marked with request-changes verdict
        assert phase._state.to_dict()["reviewed_prs"].get(str(101)) == "request-changes"
        # Issue should be marked as reviewed
        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "reviewed"
        # Review summary was posted as PR comment
        phase._prs.post_pr_comment.assert_awaited_once_with(101, "Looks good.")
        # No exception propagated — result is returned normally
        assert results[0].verdict == ReviewVerdict.REQUEST_CHANGES

    @pytest.mark.asyncio
    async def test_review_self_review_error_does_not_crash_batch(
        self, config: HydraFlowConfig
    ) -> None:
        """With multiple PRs, a SelfReviewError on one should not block others."""
        from pr_manager import SelfReviewError

        phase = make_review_phase(config)
        issues = [TaskFactory.create(id=1), TaskFactory.create(id=2)]
        prs = [
            PRInfoFactory.create(issue_number=1),
            PRInfoFactory.create(number=102, issue_number=2),
        ]

        async def fake_review(pr, issue, wt_path, diff, worker_id=0):
            return ReviewResultFactory.create(
                pr_number=pr.number,
                issue_number=issue.id,
                verdict=ReviewVerdict.REQUEST_CHANGES,
            )

        async def fake_submit_review(pr_number, verdict, summary):
            if pr_number == 101:
                raise SelfReviewError(
                    "Can not request changes on your own pull request"
                )
            return True

        phase._reviewers.review = fake_review  # type: ignore[method-assign]
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = fake_submit_review  # type: ignore[method-assign]

        for i in (1, 2):
            wt = config.worktree_base / f"issue-{i}"
            wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs(prs, issues)

        # Both PRs should have been processed
        assert len(results) == 2
        # Both PRs marked in state
        assert phase._state.to_dict()["reviewed_prs"].get(str(101)) == "request-changes"
        assert phase._state.to_dict()["reviewed_prs"].get(str(102)) == "request-changes"
        # Both issues marked as reviewed
        assert phase._state.to_dict()["processed_issues"].get(str(1)) == "reviewed"
        assert phase._state.to_dict()["processed_issues"].get(str(2)) == "reviewed"

    @pytest.mark.asyncio
    async def test_review_skips_pr_comment_when_summary_empty(
        self, config: HydraFlowConfig
    ) -> None:
        """post_pr_comment should NOT be called when summary is empty."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="",
            fixes_made=False,
        )

        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        phase._prs.post_pr_comment.assert_not_awaited()
        # submit_review should NOT be called for approve verdict
        phase._prs.submit_review.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_comment_before_merge(self, config: HydraFlowConfig) -> None:
        """post_pr_comment should be called before merge; submit_review skipped for approve."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create()

        phase._reviewers.review = AsyncMock(return_value=review)

        call_order: list[str] = []

        async def fake_post_pr_comment(pr_number: int, body: str) -> None:
            call_order.append("post_pr_comment")

        async def fake_merge(pr_number: int) -> bool:
            call_order.append("merge")
            return True

        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = fake_post_pr_comment
        phase._prs.submit_review = AsyncMock(return_value=True)
        phase._prs.merge_pr = fake_merge
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert call_order.index("post_pr_comment") < call_order.index("merge")
        phase._prs.submit_review.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_posts_comment_even_when_merge_fails(
        self, config: HydraFlowConfig
    ) -> None:
        """post_pr_comment should be called regardless of merge outcome."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create()

        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Review comment + HITL escalation comment
        comment_bodies = [c.args[1] for c in phase._prs.post_pr_comment.call_args_list]
        assert "Looks good." in comment_bodies
        assert any("Merge failed" in b for b in comment_bodies)
        phase._prs.submit_review.assert_not_awaited()


# ---------------------------------------------------------------------------
# CI wait/fix loop (wait_and_fix_ci)
# ---------------------------------------------------------------------------


class TestWaitAndFixCI:
    """Tests for the wait_and_fix_ci method and CI gate in review_prs."""

    @pytest.mark.asyncio
    async def test_ci_passes_on_first_check_merges(
        self, config: HydraFlowConfig
    ) -> None:
        """When CI passes on first check, PR should be merged."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(True, "All 3 checks passed"))
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        assert results[0].ci_passed is True
        phase._prs.merge_pr.assert_awaited_once_with(101)

    @pytest.mark.asyncio
    async def test_ci_fails_all_attempts_does_not_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """When CI fails after all fix attempts, PR should not be merged."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        assert results[0].ci_passed is False
        phase._prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ci_wait_skipped_when_max_attempts_zero(
        self, config: HydraFlowConfig
    ) -> None:
        """When max_ci_fix_attempts=0, CI wait is skipped entirely."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=0,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(True, "passed"))
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        # wait_for_ci should NOT have been called
        phase._prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ci_not_checked_for_non_approve_verdicts(
        self, config: HydraFlowConfig
    ) -> None:
        """CI wait only triggers for APPROVE — REQUEST_CHANGES skips it."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                verdict=ReviewVerdict.REQUEST_CHANGES
            )
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(True, "passed"))

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        phase._prs.wait_for_ci.assert_not_awaited()
        phase._prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fix_loop_retries_after_agent_makes_changes(
        self, config: HydraFlowConfig
    ) -> None:
        """When fix agent makes changes, loop should retry CI."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # CI fails first, then passes after fix
        ci_results = [
            (False, "Failed checks: ci"),
            (True, "All 2 checks passed"),
        ]
        ci_call_count = 0

        async def fake_wait_for_ci(_pr_num, _timeout, _interval, _stop):
            nonlocal ci_call_count
            result = ci_results[ci_call_count]
            ci_call_count += 1
            return result

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = fake_wait_for_ci
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        assert results[0].ci_passed is True
        assert results[0].ci_fix_attempts == 1
        assert ci_call_count == 2

    @pytest.mark.asyncio
    async def test_fix_agent_no_changes_stops_retrying(
        self, config: HydraFlowConfig
    ) -> None:
        """When fix agent makes no changes, loop should stop early."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=3,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=False,  # No changes made
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        assert results[0].ci_passed is False
        # Only 1 fix attempt (stopped early because no changes)
        assert results[0].ci_fix_attempts == 1
        # fix_ci called once, not 3 times
        phase._reviewers.fix_ci.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ci_failure_posts_comment_and_labels_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """CI failure should post a comment and swap label to hydraflow-hitl."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should have posted a CI failure comment
        comment_calls = [c.args for c in phase._prs.post_pr_comment.call_args_list]
        ci_comments = [c for c in comment_calls if "CI failed" in c[1]]
        assert len(ci_comments) == 1
        assert "Failed checks: ci" in ci_comments[0][1]

        # Should swap label to hydraflow-hitl on both issue and PR
        phase._prs.transition.assert_any_await(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_ci_failure_sets_hitl_cause(self, config: HydraFlowConfig) -> None:
        """CI failure escalation should record cause with attempt count in state."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        cause = phase._state.get_hitl_cause(42)
        assert cause is not None
        assert cause.startswith("CI failed after 1 fix attempt(s): ")

    @pytest.mark.asyncio
    async def test_ci_failure_escalation_records_hitl_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """CI failure escalation should record review_label as HITL origin."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"


# ---------------------------------------------------------------------------
# _resolve_merge_conflicts
# ---------------------------------------------------------------------------


class TestResolveMergeConflicts:
    """Tests for the _resolve_merge_conflicts method."""

    @pytest.mark.asyncio
    async def test_returns_false_when_no_agents(self, config: HydraFlowConfig) -> None:
        """Without an agent runner, should return False immediately."""
        phase = make_review_phase(config)  # No agents
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=False, used_rebuild=False)

    @pytest.mark.asyncio
    async def test_returns_true_when_start_merge_is_clean(
        self, config: HydraFlowConfig
    ) -> None:
        """If start_merge_main returns True (no conflicts), return True."""
        mock_agents = AsyncMock()
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=True)

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)
        # Agent should NOT have been invoked
        mock_agents._execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_runs_agent_and_verifies_on_conflicts(
        self, config: HydraFlowConfig
    ) -> None:
        """Should run the agent and verify quality when there are conflicts."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)
        mock_agents._build_command.assert_called_once()
        mock_agents._execute.assert_awaited_once()
        mock_agents._verify_result.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aborts_merge_on_agent_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """On agent exception on all attempts, should abort merge and return False."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(side_effect=RuntimeError("agent crashed"))
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result.success is False
        # abort_merge called between retries + final abort
        assert phase._worktrees.abort_merge.await_count >= 1

    @pytest.mark.asyncio
    async def test_retries_on_verify_failure(self, config: HydraFlowConfig) -> None:
        """Should retry when verify fails, and succeed on second attempt."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "quality failed"), (True, "")]
        )
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)
        assert mock_agents._execute.await_count == 2
        assert mock_agents._verify_result.await_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_all_attempts_then_returns_false(
        self, config: HydraFlowConfig
    ) -> None:
        """When all attempts fail verification, should return False."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, "quality failed"))
        phase = make_review_phase(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, cfg.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=False, used_rebuild=False)
        # Default is 3 attempts
        assert mock_agents._execute.await_count == 3
        assert mock_agents._verify_result.await_count == 3

    @pytest.mark.asyncio
    async def test_feeds_error_to_retry_prompt(self, config: HydraFlowConfig) -> None:
        """On retry, the prompt should include the previous error."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "ruff check failed"), (True, "")]
        )
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        # Second call to _execute should have received a prompt with the error
        second_call_args = mock_agents._execute.call_args_list[1]
        prompt_arg = second_call_args.args[1]
        assert "ruff check failed" in prompt_arg
        assert "Previous Attempt Failed" in prompt_arg

    @pytest.mark.asyncio
    async def test_aborts_merge_between_retries(self, config: HydraFlowConfig) -> None:
        """abort_merge should be called before attempt 2+."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "failed"), (True, "")]
        )
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        # abort_merge called once before attempt 2
        phase._worktrees.abort_merge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_saves_transcript_per_attempt(self, config: HydraFlowConfig) -> None:
        """A transcript file should be saved for each attempt."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript content")
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "failed"), (True, "")]
        )
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "merge_conflict-pr-101-attempt-1.txt").exists()
        assert (log_dir / "merge_conflict-pr-101-attempt-2.txt").exists()

    @pytest.mark.asyncio
    async def test_respects_config_max_attempts(self, config: HydraFlowConfig) -> None:
        """Should honor a custom max_merge_conflict_fix_attempts value."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_merge_conflict_fix_attempts=1,
            enable_fresh_branch_rebuild=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, "quality failed"))
        phase = make_review_phase(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, cfg.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=False, used_rebuild=False)
        assert mock_agents._execute.await_count == 1

    @pytest.mark.asyncio
    async def test_zero_attempts_returns_false(self, config: HydraFlowConfig) -> None:
        """With max_merge_conflict_fix_attempts=0, should return False without trying."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_merge_conflict_fix_attempts=0,
            enable_fresh_branch_rebuild=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        mock_agents = AsyncMock()
        phase = make_review_phase(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, cfg.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=False, used_rebuild=False)
        mock_agents._execute.assert_not_awaited()
        # Final abort_merge should still be called
        phase._worktrees.abort_merge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_conflict_resolution_calls_file_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """file_memory_suggestion should be called with the conflict transcript."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript with suggestion")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

        with patch(
            "merge_conflict_resolver.safe_file_memory_suggestion",
            new_callable=AsyncMock,
        ) as mock_fms:
            await phase._resolve_merge_conflicts(
                pr, issue, config.worktree_base / "issue-42", worker_id=0
            )

            mock_fms.assert_awaited_once_with(
                "transcript with suggestion",
                "merge_conflict",
                f"PR #{pr.number}",
                phase._config,
                phase._prs,
                phase._state,
            )

    @pytest.mark.asyncio
    async def test_conflict_resolution_memory_failure_does_not_propagate(
        self, config: HydraFlowConfig
    ) -> None:
        """Exceptions from file_memory_suggestion must not break conflict resolution."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            result = await phase._resolve_merge_conflicts(
                pr, issue, config.worktree_base / "issue-42", worker_id=0
            )

            assert result == ConflictResolutionResult(success=True, used_rebuild=False)


# ---------------------------------------------------------------------------
# Review exception isolation
# ---------------------------------------------------------------------------


class TestReviewExceptionIsolation:
    """Tests that _review_one catches exceptions and returns failed results."""

    @pytest.mark.asyncio
    async def test_review_exception_returns_failed_result(
        self, config: HydraFlowConfig
    ) -> None:
        """When reviewer.review raises, should return ReviewResult with error summary."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            side_effect=RuntimeError("reviewer crashed")
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert len(results) == 1
        assert results[0].pr_number == 101
        assert "unexpected error" in results[0].summary.lower()

    @pytest.mark.asyncio
    async def test_review_exception_releases_active_issues(
        self, config: HydraFlowConfig
    ) -> None:
        """When review crashes, issue should be removed from active_issues."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            side_effect=RuntimeError("reviewer crashed")
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert not phase._store.is_active(42)

    @pytest.mark.asyncio
    async def test_review_exception_does_not_crash_batch(
        self, config: HydraFlowConfig
    ) -> None:
        """With 2 PRs, first review crashing should not prevent the second."""
        phase = make_review_phase(config)
        issues = [TaskFactory.create(id=1), TaskFactory.create(id=2)]
        prs = [
            PRInfoFactory.create(issue_number=1),
            PRInfoFactory.create(number=102, issue_number=2),
        ]

        call_count = 0

        async def sometimes_crashing_review(
            pr: PRInfo,
            issue: Task,
            wt_path: Path,
            diff: str,
            worker_id: int = 0,
        ) -> ReviewResult:
            nonlocal call_count
            call_count += 1
            if pr.issue_number == 1:
                raise RuntimeError("reviewer crashed for PR 1")
            return ReviewResultFactory.create(
                pr_number=pr.number, issue_number=issue.id
            )

        phase._reviewers.review = sometimes_crashing_review  # type: ignore[method-assign]
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        for i in (1, 2):
            wt = config.worktree_base / f"issue-{i}"
            wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs(prs, issues)

        # Both results should be returned
        assert len(results) == 2
        result_map = {r.pr_number: r for r in results}
        # PR 101 (issue 1) should have error summary
        assert "unexpected error" in result_map[101].summary.lower()
        # PR 102 (issue 2) should have succeeded
        assert result_map[102].summary == "Looks good."


# ---------------------------------------------------------------------------
# _store active-issue cleanup
# ---------------------------------------------------------------------------


class TestActiveIssuesCleanup:
    """Tests that _store marks issues complete on all code paths."""

    @pytest.mark.asyncio
    async def test_active_issues_cleaned_on_early_return_issue_not_found(
        self, config: HydraFlowConfig
    ) -> None:
        """When issue is not in issue_map, store must mark_complete."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create(issue_number=999)

        wt = config.worktree_base / "issue-999"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [])  # no matching issues

        assert not phase._store.is_active(999)
        assert len(results) == 1
        assert results[0].summary == "Issue not found"

    @pytest.mark.asyncio
    async def test_active_issues_cleaned_on_exception_during_merge_main(
        self, config: HydraFlowConfig
    ) -> None:
        """If merge_main raises, store must still mark_complete."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(
            side_effect=RuntimeError("merge exploded")
        )

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        # Exception isolation catches the error and returns a failed result
        results = await phase.review_prs([pr], [issue])

        assert not phase._store.is_active(42)
        assert len(results) == 1
        assert "unexpected error" in results[0].summary.lower()

    @pytest.mark.asyncio
    async def test_active_issues_cleaned_on_exception_during_review(
        self, config: HydraFlowConfig
    ) -> None:
        """If reviewers.review raises, store must still mark_complete."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(side_effect=RuntimeError("review crashed"))
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        # Exception isolation catches the error and returns a failed result
        results = await phase.review_prs([pr], [issue])

        assert not phase._store.is_active(42)
        assert len(results) == 1
        assert "unexpected error" in results[0].summary.lower()

    @pytest.mark.asyncio
    async def test_active_issues_cleaned_on_exception_during_worktree_create(
        self, config: HydraFlowConfig
    ) -> None:
        """If worktrees.create raises, store must still mark_complete."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.create = AsyncMock(
            side_effect=RuntimeError("worktree create failed")
        )

        # No worktree dir exists, so create() will be called
        # Exception isolation catches the error and returns a failed result
        results = await phase.review_prs([pr], [issue])

        assert not phase._store.is_active(42)
        assert len(results) == 1
        assert "unexpected error" in results[0].summary.lower()

    @pytest.mark.asyncio
    async def test_active_issues_cleaned_on_happy_path(
        self, config: HydraFlowConfig
    ) -> None:
        """On the happy path, store must mark_complete after review_prs."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert not phase._store.is_active(42)


# ---------------------------------------------------------------------------
# REVIEW_UPDATE start event
# ---------------------------------------------------------------------------


class TestReviewUpdateStartEvent:
    """Tests that a REVIEW_UPDATE event is published at the start of _review_one()."""

    @pytest.mark.asyncio
    async def test_review_update_start_event_published_before_review(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A REVIEW_UPDATE 'start' event should be published when _review_one() starts."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Check that a REVIEW_UPDATE event with status "start" was published
        history = event_bus.get_history()
        start_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "start"
        ]
        assert len(start_events) == 1
        assert start_events[0].data["pr"] == 101
        assert start_events[0].data["issue"] == 42
        assert start_events[0].data["role"] == "reviewer"

    @pytest.mark.asyncio
    async def test_review_update_start_event_published_even_when_issue_not_found(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A REVIEW_UPDATE 'start' event is published even if the issue is missing."""
        phase = make_review_phase(config, event_bus=event_bus)
        pr = PRInfoFactory.create(issue_number=999)

        wt = config.worktree_base / "issue-999"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [])

        history = event_bus.get_history()
        start_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "start"
        ]
        assert len(start_events) == 1
        assert start_events[0].data["pr"] == 101
        assert start_events[0].data["issue"] == 999

    @pytest.mark.asyncio
    async def test_review_update_start_event_includes_worker_id(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """The start event should include the worker ID."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        start_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "start"
        ]
        assert len(start_events) == 1
        assert "worker" in start_events[0].data


# ---------------------------------------------------------------------------
# Lifecycle metric recording
# ---------------------------------------------------------------------------


class TestLifecycleMetricRecording:
    """Tests that review_prs records new lifecycle metrics in state."""

    @pytest.mark.asyncio
    async def test_records_review_verdict_approve(
        self, config: HydraFlowConfig
    ) -> None:
        """Approving a PR should record an approval verdict in state."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_review_approvals == 1
        assert stats.total_review_request_changes == 0

    @pytest.mark.asyncio
    async def test_records_review_verdict_request_changes(
        self, config: HydraFlowConfig
    ) -> None:
        """Request-changes verdict should record in state."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Needs changes.",
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_review_request_changes == 1
        assert stats.total_review_approvals == 0

    @pytest.mark.asyncio
    async def test_records_reviewer_fixes(self, config: HydraFlowConfig) -> None:
        """When reviewer makes fixes, it should be counted."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="Fixed and approved.",
            fixes_made=True,
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_reviewer_fixes == 1

    @pytest.mark.asyncio
    async def test_records_review_duration(self, config: HydraFlowConfig) -> None:
        """Review duration should be recorded when positive."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="OK",
            duration_seconds=45.5,
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_review_seconds == pytest.approx(45.5)

    @pytest.mark.asyncio
    async def test_does_not_record_zero_review_duration(
        self, config: HydraFlowConfig
    ) -> None:
        """Zero duration should not be recorded."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="OK",
            duration_seconds=0.0,
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_review_seconds == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_merge_conflict_records_hitl_escalation(
        self, config: HydraFlowConfig
    ) -> None:
        """Merge conflict HITL escalation should increment the hitl counter."""
        mock_agents = AsyncMock()
        mock_agents._verify_result = AsyncMock(return_value=(False, ""))
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_hitl_escalations == 1

    @pytest.mark.asyncio
    async def test_merge_failure_records_hitl_escalation(
        self, config: HydraFlowConfig
    ) -> None:
        """PR merge failure should increment the hitl counter."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_hitl_escalations == 1

    @pytest.mark.asyncio
    async def test_ci_failure_records_ci_fix_rounds_and_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """CI failure escalation should record ci fix rounds and hitl escalation."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_ci_fix_rounds == 1
        assert stats.total_hitl_escalations == 1

    @pytest.mark.asyncio
    async def test_successful_merge_with_ci_fixes_records_rounds(
        self, config: HydraFlowConfig
    ) -> None:
        """When CI eventually passes after fix(es), ci_fix_rounds should be recorded."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        ci_results = [
            (False, "Failed checks: ci"),
            (True, "All 2 checks passed"),
        ]
        ci_call_count = 0

        async def fake_wait_for_ci(_pr_num, _timeout, _interval, _stop):
            nonlocal ci_call_count
            result = ci_results[ci_call_count]
            ci_call_count += 1
            return result

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = fake_wait_for_ci
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        stats = phase._state.get_lifetime_stats()
        assert stats.total_ci_fix_rounds == 1  # 1 fix attempt before success


# ---------------------------------------------------------------------------
# Retrospective integration
# ---------------------------------------------------------------------------


class TestRetrospectiveIntegration:
    """Tests that retrospective.record() is called correctly after merge."""

    @pytest.mark.asyncio
    async def test_retrospective_called_on_successful_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """retrospective.record() should be called when PR is merged."""
        mock_retro = AsyncMock()
        phase = make_review_phase(config)
        phase._retrospective = mock_retro
        phase._post_merge._retrospective = mock_retro

        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        mock_retro.record.assert_awaited_once()
        call_kwargs = mock_retro.record.call_args[1]
        assert call_kwargs["issue_number"] == 42
        assert call_kwargs["pr_number"] == 101
        assert call_kwargs["review_result"].merged is True

    @pytest.mark.asyncio
    async def test_retrospective_not_called_on_failed_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """retrospective.record() should NOT be called when merge fails."""
        mock_retro = AsyncMock()
        phase = make_review_phase(config)
        phase._retrospective = mock_retro
        phase._post_merge._retrospective = mock_retro

        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        mock_retro.record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retrospective_failure_does_not_crash_review(
        self, config: HydraFlowConfig
    ) -> None:
        """If retrospective.record() raises, it should not crash the review."""
        mock_retro = AsyncMock()
        mock_retro.record = AsyncMock(side_effect=RuntimeError("retro boom"))
        phase = make_review_phase(config)
        phase._retrospective = mock_retro
        phase._post_merge._retrospective = mock_retro

        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        # Should not raise despite retro failure
        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True

    @pytest.mark.asyncio
    async def test_retrospective_not_called_when_not_configured(
        self, config: HydraFlowConfig
    ) -> None:
        """When no retrospective is set, merge should work normally."""
        phase = make_review_phase(config)
        # phase._retrospective is None by default

        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True


# ---------------------------------------------------------------------------
# Review insight integration
# ---------------------------------------------------------------------------


class TestReviewInsightIntegration:
    """Tests for review insight recording during the review flow."""

    @pytest.mark.asyncio
    async def test_review_records_insight_after_review(
        self, config: HydraFlowConfig
    ) -> None:
        """After a review, a record should be appended to the insight store."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Check that a review record was written
        reviews_path = config.repo_root / ".hydraflow" / "memory" / "reviews.jsonl"
        assert reviews_path.exists()
        lines = reviews_path.read_text().strip().splitlines()
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_review_insight_files_proposal_when_threshold_met(
        self, config: HydraFlowConfig
    ) -> None:
        """When a category crosses the threshold, an improvement issue is filed."""
        from review_insights import ReviewInsightStore, ReviewRecord

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Pre-populate the insight store with records near threshold
        store = ReviewInsightStore(config.repo_root / ".hydraflow" / "memory")
        for i in range(3):
            store.append_review(
                ReviewRecord(
                    pr_number=90 + i,
                    issue_number=30 + i,
                    timestamp="2026-02-20T10:00:00Z",
                    verdict="request-changes",
                    summary="Missing test coverage",
                    fixes_made=False,
                    categories=["missing_tests"],
                )
            )

        # This review will also have "test" in summary → missing_tests
        review_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Missing test coverage for edge cases",
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(return_value=review_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.create_task = AsyncMock(return_value=999)
        phase._prs.submit_review = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should have filed an improvement issue
        phase._prs.create_task.assert_awaited_once()
        call_args = phase._prs.create_task.call_args
        assert "[Review Insight]" in call_args.args[0]
        assert "hydraflow-improve" in call_args.args[2]
        assert "hydraflow-hitl" in call_args.args[2]

    @pytest.mark.asyncio
    async def test_review_insight_does_not_refile_proposed_category(
        self, config: HydraFlowConfig
    ) -> None:
        """Once a category has been proposed, it should not be re-filed."""
        from review_insights import ReviewInsightStore, ReviewRecord

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Pre-populate and mark as proposed
        store = ReviewInsightStore(config.repo_root / ".hydraflow" / "memory")
        for i in range(4):
            store.append_review(
                ReviewRecord(
                    pr_number=90 + i,
                    issue_number=30 + i,
                    timestamp="2026-02-20T10:00:00Z",
                    verdict="request-changes",
                    summary="Missing test coverage",
                    fixes_made=False,
                    categories=["missing_tests"],
                )
            )
        store.mark_category_proposed("missing_tests")

        review_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Missing test coverage",
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(return_value=review_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.create_task = AsyncMock(return_value=999)
        phase._prs.submit_review = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should NOT have filed an improvement issue
        phase._prs.create_task.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_insight_failure_does_not_crash_review(
        self, config: HydraFlowConfig
    ) -> None:
        """If insight recording fails, the review should still complete."""
        from unittest.mock import patch

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        # Make the insight store raise
        with patch.object(
            phase._insights, "append_review", side_effect=OSError("disk full")
        ):
            results = await phase.review_prs([pr], [issue])

        # Review should still succeed
        assert len(results) == 1
        assert results[0].merged is True


# ---------------------------------------------------------------------------
# Granular REVIEW_UPDATE status events
# ---------------------------------------------------------------------------


class TestGranularReviewStatusEvents:
    """Tests that review_phase emits granular status events at each lifecycle stage."""

    @pytest.mark.asyncio
    async def test_merge_main_status_emitted(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'merge_main' event should be published before merging main."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        merge_main_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE
            and e.data.get("status") == "merge_main"
        ]
        assert len(merge_main_events) == 1
        assert merge_main_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_merge_fix_status_emitted(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'merge_fix' event should be published when resolving conflicts."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        conflict_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "merge_fix"
        ]
        # One event from the caller in review_prs, one from the retry loop
        assert len(conflict_events) == 2
        assert conflict_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_escalating_status_emitted_on_conflict_failure(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """An 'escalating' event should be published when conflicts can't be resolved."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, ""))
        phase = make_review_phase(config, agents=mock_agents, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        escalating_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE
            and e.data.get("status") == "escalating"
        ]
        assert len(escalating_events) == 1
        assert escalating_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_merging_status_emitted_before_merge(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'merging' event should be published before merging the PR."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        merging_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "merging"
        ]
        assert len(merging_events) == 1
        assert merging_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_escalating_status_emitted_on_merge_failure(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """An 'escalating' event should be published when PR merge fails."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        escalating_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE
            and e.data.get("status") == "escalating"
        ]
        assert len(escalating_events) == 1
        assert escalating_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_ci_wait_status_emitted(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'ci_wait' event should be published before waiting for CI."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(True, "All checks passed"))
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        ci_wait_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "ci_wait"
        ]
        assert len(ci_wait_events) == 1
        assert ci_wait_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_ci_fix_status_emitted(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'ci_fix' event should be published before running the CI fix agent."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        ci_results = [
            (False, "Failed checks: ci"),
            (True, "All checks passed"),
        ]
        ci_call_count = 0

        async def fake_wait_for_ci(_pr_num, _timeout, _interval, _stop):
            nonlocal ci_call_count
            result = ci_results[ci_call_count]
            ci_call_count += 1
            return result

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = fake_wait_for_ci
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        ci_fix_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "ci_fix"
        ]
        assert len(ci_fix_events) == 1
        assert ci_fix_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_escalating_status_emitted_on_ci_exhaustion(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """An 'escalating' event should be published when CI fix attempts are exhausted."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        escalating_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE
            and e.data.get("status") == "escalating"
        ]
        assert len(escalating_events) == 1
        assert escalating_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_event_ordering_happy_path(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Events should be emitted in order: start -> merge_main -> reviewing -> merging."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        review_statuses = [
            e.data["status"] for e in history if e.type == EventType.REVIEW_UPDATE
        ]
        assert review_statuses.index("start") < review_statuses.index("merge_main")
        assert review_statuses.index("merge_main") < review_statuses.index("merging")
        assert review_statuses[-1] == "done"


class TestHITLEscalationEvents:
    """Tests that HITL escalation points emit HITL_ESCALATION events."""

    @pytest.mark.asyncio
    async def test_merge_conflict_escalation_emits_hitl_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Merge conflict escalation should emit HITL_ESCALATION with cause merge_conflict."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, ""))
        phase = make_review_phase(config, agents=mock_agents, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "escalated"
        assert data["role"] == "reviewer"
        assert data["cause"] == "merge_conflict"

    @pytest.mark.asyncio
    async def test_merge_failure_escalation_emits_hitl_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Merge failure escalation should emit HITL_ESCALATION with cause merge_failed."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "escalated"
        assert data["role"] == "reviewer"
        assert data["cause"] == "merge_failed"

    @pytest.mark.asyncio
    async def test_ci_failure_escalation_emits_hitl_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """CI failure escalation should emit HITL_ESCALATION with cause ci_failed."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "escalated"
        assert data["role"] == "reviewer"
        assert data["cause"] == "ci_failed"
        assert data["ci_fix_attempts"] == 1

    @pytest.mark.asyncio
    async def test_successful_merge_does_not_emit_hitl_escalation(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Happy path (approve + merge) should NOT emit HITL_ESCALATION."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 0

    @pytest.mark.asyncio
    async def test_review_fix_cap_exceeded_emits_hitl_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Review fix cap exceeded should emit HITL_ESCALATION with cause review_fix_cap_exceeded."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Set attempts to max so cap is exceeded
        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                verdict=ReviewVerdict.REQUEST_CHANGES
            )
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "escalated"
        assert data["role"] == "reviewer"
        assert data["cause"] == "review_fix_cap_exceeded"


# ---------------------------------------------------------------------------
# REQUEST_CHANGES retry logic
# ---------------------------------------------------------------------------


class TestRequestChangesRetry:
    """Tests for the REQUEST_CHANGES → retry → HITL escalation flow."""

    def _setup_phase_for_retry(
        self, config: HydraFlowConfig
    ) -> tuple[ReviewPhase, PRInfo, Task]:
        """Helper to set up a ReviewPhase ready for retry tests."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                verdict=ReviewVerdict.REQUEST_CHANGES
            )
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        return phase, pr, issue

    @pytest.mark.asyncio
    async def test_request_changes_under_cap_swaps_label_to_ready(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES under cap should swap labels from review to ready."""
        phase, pr, issue = self._setup_phase_for_retry(config)

        await phase.review_prs([pr], [issue])

        phase._prs.transition.assert_any_await(42, "ready", pr_number=101)

    @pytest.mark.asyncio
    async def test_request_changes_under_cap_preserves_worktree(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES under cap should NOT destroy the worktree."""
        phase, pr, issue = self._setup_phase_for_retry(config)

        await phase.review_prs([pr], [issue])

        phase._worktrees.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_request_changes_under_cap_stores_feedback(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES under cap should store review feedback in state."""
        phase, pr, issue = self._setup_phase_for_retry(config)

        await phase.review_prs([pr], [issue])

        feedback = phase._state.get_review_feedback(42)
        assert feedback is not None
        assert feedback == "Looks good."

    @pytest.mark.asyncio
    async def test_request_changes_under_cap_increments_attempt_counter(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES under cap should increment the attempt counter."""
        phase, pr, issue = self._setup_phase_for_retry(config)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_review_attempts(42) == 1

    @pytest.mark.asyncio
    async def test_request_changes_at_cap_escalates_to_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES at cap should escalate to HITL."""
        phase, pr, issue = self._setup_phase_for_retry(config)
        # Set attempts to max
        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        await phase.review_prs([pr], [issue])

        phase._prs.transition.assert_any_await(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_request_changes_at_cap_posts_escalation_comment(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES at cap should post an escalation comment."""
        phase, pr, issue = self._setup_phase_for_retry(config)
        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        await phase.review_prs([pr], [issue])

        phase._prs.post_comment.assert_awaited()
        comment_arg = phase._prs.post_comment.call_args[0][1]
        assert "cap exceeded" in comment_arg.lower()

    @pytest.mark.asyncio
    async def test_comment_verdict_treated_as_soft_rejection(
        self, config: HydraFlowConfig
    ) -> None:
        """COMMENT verdict should trigger the same retry flow as REQUEST_CHANGES."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(verdict=ReviewVerdict.COMMENT)
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should swap to ready label (same as REQUEST_CHANGES)
        phase._prs.transition.assert_any_await(42, "ready", pr_number=101)
        # Worktree should be preserved
        phase._worktrees.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_approve_resets_review_attempts(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE should reset review attempt counter on successful merge."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Simulate previous review attempts
        phase._state.increment_review_attempts(42)

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_review_attempts(42) == 0

    @pytest.mark.asyncio
    async def test_approve_clears_review_feedback(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE should clear stored review feedback on successful merge."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Simulate stored feedback from a previous review
        phase._state.set_review_feedback(42, "Old feedback")

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_review_feedback(42) is None


# ---------------------------------------------------------------------------
# Adversarial review threshold
# ---------------------------------------------------------------------------


class TestAdversarialReview:
    """Tests for the adversarial review re-check logic."""

    @pytest.mark.asyncio
    async def test_approve_with_enough_findings_is_accepted(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE with >= min_review_findings should be accepted without re-review."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Summary with 3+ findings (bullets)
        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="- Fix A\n- Fix B\n- Fix C",
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should only call review once (no re-review)
        assert phase._reviewers.review.await_count == 1

    @pytest.mark.asyncio
    async def test_approve_with_thorough_review_complete_accepted(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE with THOROUGH_REVIEW_COMPLETE block should be accepted."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="All good",
            fixes_made=False,
            transcript="...THOROUGH_REVIEW_COMPLETE\nCorrectness: No issues...",
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should only call review once (no re-review)
        assert phase._reviewers.review.await_count == 1

    @pytest.mark.asyncio
    async def test_approve_under_threshold_triggers_re_review(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE with too few findings and no justification should trigger re-review."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # First review: few findings, no THOROUGH_REVIEW_COMPLETE
        first_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="Looks good",
            fixes_made=False,
            transcript="VERDICT: APPROVE\nSUMMARY: Looks good",
        )
        # Second review: has enough findings
        second_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="- Fix A\n- Fix B\n- Fix C",
            fixes_made=False,
            transcript="VERDICT: APPROVE\nSUMMARY: - Fix A",
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should call review twice (initial + re-review)
        assert phase._reviewers.review.await_count == 2


# ---------------------------------------------------------------------------
# _count_review_findings
# ---------------------------------------------------------------------------


class TestCountReviewFindings:
    """Tests for ReviewPhase._count_review_findings."""

    def test_counts_bullet_points(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("- Fix A\n- Fix B\n- Fix C") == 3

    def test_counts_numbered_items(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("1. Fix A\n2. Fix B") == 2

    def test_counts_asterisk_bullets(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("* Fix A\n* Fix B") == 2

    def test_counts_mixed_formats(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        summary = "- Bullet item\n1. Numbered item\n* Star item"
        assert phase._count_review_findings(summary) == 3

    def test_returns_zero_for_no_findings(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("All looks good.") == 0

    def test_returns_zero_for_empty_string(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("") == 0


# ---------------------------------------------------------------------------
# Self-fix re-review
# ---------------------------------------------------------------------------


class TestSelfFixReReview:
    """Tests for the self-fix re-review logic.

    When the reviewer fixes its own findings (fixes_made=True) but still
    returns REQUEST_CHANGES or COMMENT, the phase should re-review the
    updated code and upgrade the verdict to APPROVE if the re-review passes.
    """

    def _setup_phase(self, config: HydraFlowConfig) -> tuple[ReviewPhase, PRInfo, Task]:
        """Helper to set up a ReviewPhase ready for self-fix re-review tests."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        return phase, pr, issue

    @pytest.mark.asyncio
    async def test_self_fix_with_re_review_approve_upgrades_verdict(
        self, config: HydraFlowConfig
    ) -> None:
        """fixes_made=True + REQUEST_CHANGES → re-review APPROVE → merge."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        results = await phase.review_prs([pr], [issue])

        assert phase._reviewers.review.await_count == 2
        phase._prs.merge_pr.assert_awaited_once()
        assert results[0].verdict == ReviewVerdict.APPROVE
        # Label should NOT be swapped to ready
        for call_args in phase._prs.add_labels.call_args_list:
            assert call_args[0][1] != config.ready_label

    @pytest.mark.asyncio
    async def test_self_fix_with_re_review_reject_preserves_behavior(
        self, config: HydraFlowConfig
    ) -> None:
        """fixes_made=True + REQUEST_CHANGES → re-review REQUEST_CHANGES → re-queue."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        await phase.review_prs([pr], [issue])

        assert phase._reviewers.review.await_count == 2
        phase._prs.merge_pr.assert_not_awaited()
        # Should swap labels to ready (re-queue)
        phase._prs.transition.assert_any_await(
            pr.issue_number, "ready", pr_number=pr.number
        )
        assert phase._state.get_review_attempts(42) == 1

    @pytest.mark.asyncio
    async def test_no_fixes_no_re_review(self, config: HydraFlowConfig) -> None:
        """fixes_made=False + REQUEST_CHANGES → no re-review, just re-queue."""
        phase, pr, issue = self._setup_phase(config)

        result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(return_value=result)

        await phase.review_prs([pr], [issue])

        assert phase._reviewers.review.await_count == 1
        phase._prs.transition.assert_any_await(
            pr.issue_number, "ready", pr_number=pr.number
        )

    @pytest.mark.asyncio
    async def test_self_fix_comment_verdict_triggers_re_review(
        self, config: HydraFlowConfig
    ) -> None:
        """fixes_made=True + COMMENT → re-review APPROVE → merge."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.COMMENT,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        results = await phase.review_prs([pr], [issue])

        assert phase._reviewers.review.await_count == 2
        phase._prs.merge_pr.assert_awaited_once()
        assert results[0].verdict == ReviewVerdict.APPROVE

    @pytest.mark.asyncio
    async def test_self_fix_re_review_pushes_additional_fixes(
        self, config: HydraFlowConfig
    ) -> None:
        """Re-review with fixes_made=True should push additional fixes."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            fixes_made=True,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        await phase.review_prs([pr], [issue])

        # push_branch called for: merge-main, initial fixes (in _run_and_post_review),
        # and re-review fixes
        assert phase._prs.push_branch.await_count == 3

    @pytest.mark.asyncio
    async def test_self_fix_re_review_approve_does_not_increment_attempts(
        self, config: HydraFlowConfig
    ) -> None:
        """Self-fix + re-review APPROVE should NOT increment review attempts."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        await phase.review_prs([pr], [issue])

        assert phase._state.get_review_attempts(42) == 0

    @pytest.mark.asyncio
    async def test_re_review_exception_falls_back_to_rejection(
        self, config: HydraFlowConfig
    ) -> None:
        """Re-review exception falls back gracefully to original rejection (re-queue)."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        phase._reviewers.review = AsyncMock(
            side_effect=[first_result, RuntimeError("transient re-review failure")]
        )

        await phase.review_prs([pr], [issue])

        # Both calls attempted
        assert phase._reviewers.review.await_count == 2
        # Exception falls back to original rejection — no merge
        phase._prs.merge_pr.assert_not_awaited()
        # Label swapped to ready (re-queue as original REQUEST_CHANGES)
        phase._prs.transition.assert_any_await(
            pr.issue_number, "ready", pr_number=pr.number
        )
        assert phase._state.get_review_attempts(pr.issue_number) == 1


# ---------------------------------------------------------------------------
# Verification Issue Creation
# ---------------------------------------------------------------------------


def _make_judge_result(
    issue_number: int = 42,
    pr_number: int = 101,
    criteria: list[VerificationCriterion] | None = None,
    verification_instructions: str = "1. Run the app\n2. Click the button",
    all_pass: bool = True,
) -> JudgeResult:
    """Build a JudgeResult for testing."""
    if criteria is None:
        if all_pass:
            criteria = [
                VerificationCriterion(
                    description="Unit tests pass", passed=True, details="All pass"
                ),
                VerificationCriterion(
                    description="Lint passes", passed=True, details="Clean"
                ),
            ]
        else:
            criteria = [
                VerificationCriterion(
                    description="Unit tests pass", passed=True, details="All pass"
                ),
                VerificationCriterion(
                    description="Lint passes", passed=False, details="3 errors found"
                ),
            ]
    return JudgeResult(
        issue_number=issue_number,
        pr_number=pr_number,
        criteria=criteria,
        verification_instructions=verification_instructions,
    )


class TestCreateVerificationIssue:
    """Tests for ReviewPhase._create_verification_issue."""

    @pytest.mark.asyncio
    async def test_creates_issue_all_criteria_passed(
        self, config: HydraFlowConfig
    ) -> None:
        """Judge with all criteria passing creates issue with correct title and label."""
        phase = make_review_phase(config)
        issue = TaskFactory.create(title="Fix the frobnicator")
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        phase._prs.create_issue = AsyncMock(return_value=500)

        result = await phase._create_verification_issue(issue, pr, judge)

        assert result == 500
        phase._prs.create_issue.assert_awaited_once()
        call_args = phase._prs.create_issue.call_args
        title = call_args[0][0]
        body = call_args[0][1]
        labels = call_args[0][2]

        assert title == "Verify: Fix the frobnicator"
        assert labels == ["hydraflow-hitl"]
        assert "All criteria passed at code level" in body
        assert "#42" in body
        assert "#101" in body

    @pytest.mark.asyncio
    async def test_creates_issue_with_failed_criteria(
        self, config: HydraFlowConfig
    ) -> None:
        """Judge with mixed results highlights failures in the body."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result(all_pass=False)

        phase._prs.create_issue = AsyncMock(return_value=500)

        await phase._create_verification_issue(issue, pr, judge)

        body = phase._prs.create_issue.call_args[0][1]
        assert "failed at code level" in body
        assert "pay extra attention" in body
        assert "\u274c FAIL" in body

    @pytest.mark.asyncio
    async def test_creates_issue_includes_verification_instructions(
        self, config: HydraFlowConfig
    ) -> None:
        """Body includes the verification instructions from judge result."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result(
            verification_instructions="1. Start server\n2. Check /health"
        )

        phase._prs.create_issue = AsyncMock(return_value=500)

        await phase._create_verification_issue(issue, pr, judge)

        body = phase._prs.create_issue.call_args[0][1]
        assert "Verification Instructions" in body
        assert "Start server" in body
        assert "Check /health" in body

    @pytest.mark.asyncio
    async def test_creates_issue_includes_links(self, config: HydraFlowConfig) -> None:
        """Body contains references to the original issue and PR."""
        phase = make_review_phase(config)
        issue = TaskFactory.create(id=99, title="Add auth")
        pr = PRInfoFactory.create(number=200, issue_number=99)
        judge = _make_judge_result(issue_number=99, pr_number=200)

        phase._prs.create_issue = AsyncMock(return_value=500)

        await phase._create_verification_issue(issue, pr, judge)

        body = phase._prs.create_issue.call_args[0][1]
        assert "#99" in body
        assert "#200" in body

    @pytest.mark.asyncio
    async def test_returns_zero_on_failure(self, config: HydraFlowConfig) -> None:
        """When create_issue returns 0, method returns 0."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        phase._prs.create_issue = AsyncMock(return_value=0)

        result = await phase._create_verification_issue(issue, pr, judge)

        assert result == 0

    @pytest.mark.asyncio
    async def test_state_tracked_on_success(self, config: HydraFlowConfig) -> None:
        """After successful creation, state tracks the verification issue."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        phase._prs.create_issue = AsyncMock(return_value=500)

        await phase._create_verification_issue(issue, pr, judge)

        assert phase._state.get_verification_issue(42) == 500

    @pytest.mark.asyncio
    async def test_state_not_tracked_on_failure(self, config: HydraFlowConfig) -> None:
        """When create_issue returns 0, state is not updated."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        phase._prs.create_issue = AsyncMock(return_value=0)

        await phase._create_verification_issue(issue, pr, judge)

        assert phase._state.get_verification_issue(42) is None


# ---------------------------------------------------------------------------
# _get_judge_result conversion
# ---------------------------------------------------------------------------


class TestGetJudgeResult:
    """Tests for ReviewPhase._get_judge_result verdict-to-result conversion."""

    def test_returns_none_when_verdict_is_none(self, config: HydraFlowConfig) -> None:
        """When no verdict is produced, returns None."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = phase._get_judge_result(issue, pr, None)

        assert result is None

    def test_maps_pass_criterion(self, config: HydraFlowConfig) -> None:
        """PASS criterion is converted with passed=True."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="Tests pass",
                ),
            ],
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert len(result.criteria) == 1
        assert result.criteria[0].description == "AC-1"
        assert result.criteria[0].passed is True
        assert result.criteria[0].details == "Tests pass"

    def test_maps_fail_criterion(self, config: HydraFlowConfig) -> None:
        """FAIL criterion is converted with passed=False."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            criteria_results=[
                CriterionResult(
                    criterion="AC-2",
                    verdict=CriterionVerdict.FAIL,
                    reasoning="No test coverage",
                ),
            ],
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert len(result.criteria) == 1
        assert result.criteria[0].passed is False
        assert result.criteria[0].details == "No test coverage"

    def test_maps_mixed_criteria(self, config: HydraFlowConfig) -> None:
        """Multiple criteria with mixed verdicts are all converted."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="OK",
                ),
                CriterionResult(
                    criterion="AC-2",
                    verdict=CriterionVerdict.FAIL,
                    reasoning="Missing",
                ),
                CriterionResult(
                    criterion="AC-3",
                    verdict=CriterionVerdict.PASS,
                    reasoning="Covered",
                ),
            ],
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert len(result.criteria) == 3
        assert result.criteria[0].passed is True
        assert result.criteria[1].passed is False
        assert result.criteria[2].passed is True

    def test_passes_through_verification_instructions(
        self, config: HydraFlowConfig
    ) -> None:
        """verification_instructions from verdict flows to result."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            verification_instructions="1. Run app\n2. Check output",
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert result.verification_instructions == "1. Run app\n2. Check output"

    def test_passes_through_summary(self, config: HydraFlowConfig) -> None:
        """summary from verdict flows to result."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            summary="2/3 criteria passed, instructions: ready",
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert result.summary == "2/3 criteria passed, instructions: ready"

    def test_uses_issue_and_pr_numbers(self, config: HydraFlowConfig) -> None:
        """issue_number and pr_number come from the issue/pr args, not verdict."""
        phase = make_review_phase(config)
        issue = TaskFactory.create(id=99)
        pr = PRInfoFactory.create(number=200, issue_number=99)
        verdict = JudgeVerdict(issue_number=99)

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert result.issue_number == 99
        assert result.pr_number == 200

    def test_empty_criteria(self, config: HydraFlowConfig) -> None:
        """Verdict with no criteria produces result with empty criteria list."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(issue_number=issue.id)

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert result.criteria == []


# ---------------------------------------------------------------------------
# Extracted method unit tests
# ---------------------------------------------------------------------------


class TestEscalateToHitl:
    """Unit tests for the shared _escalate_to_hitl helper."""

    @pytest.mark.asyncio
    async def test_sets_hitl_origin_and_cause(self, config: HydraFlowConfig) -> None:
        """Should set HITL origin label and cause in state."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test failure",
            origin_label="hydraflow-review",
            comment="Escalation comment",
        )

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"
        assert phase._state.get_hitl_cause(42) == "Test failure"

    @pytest.mark.asyncio
    async def test_records_hitl_escalation_counter(
        self, config: HydraFlowConfig
    ) -> None:
        """Should increment the HITL escalation counter."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="comment",
        )

        stats = phase._state.get_lifetime_stats()
        assert stats.total_hitl_escalations == 1

    @pytest.mark.asyncio
    async def test_swaps_labels_on_issue_and_pr(self, config: HydraFlowConfig) -> None:
        """Should remove review labels and add HITL labels."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="comment",
        )

        phase._prs.transition.assert_awaited_once_with(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_posts_comment_on_pr_by_default(
        self, config: HydraFlowConfig
    ) -> None:
        """By default, the comment is posted on the PR."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="Escalation!",
        )

        phase._prs.post_pr_comment.assert_awaited_once_with(101, "Escalation!")
        phase._prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_posts_comment_on_issue_when_post_on_pr_false(
        self, config: HydraFlowConfig
    ) -> None:
        """When post_on_pr=False, comment is posted on the issue."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="Escalation!",
            post_on_pr=False,
        )

        phase._prs.post_comment.assert_awaited_once_with(42, "Escalation!")
        phase._prs.post_pr_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publishes_hitl_escalation_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Should publish an HITL_ESCALATION event."""
        phase = make_review_phase(config, event_bus=event_bus)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test cause",
            origin_label="hydraflow-review",
            comment="comment",
            event_cause="test_event",
        )

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type == EventType.HITL_ESCALATION]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["pr"] == 101
        assert hitl_events[0].data["cause"] == "test_event"

    @pytest.mark.asyncio
    async def test_extra_event_data_included(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Extra event data should be merged into the HITL event."""
        phase = make_review_phase(config, event_bus=event_bus)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="CI failed",
            origin_label="hydraflow-review",
            comment="comment",
            extra_event_data={"ci_fix_attempts": 3},
        )

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type == EventType.HITL_ESCALATION]
        assert hitl_events[0].data["ci_fix_attempts"] == 3


class TestMergeWithMain:
    """Unit tests for the _merge_with_main helper."""

    @pytest.mark.asyncio
    async def test_returns_true_on_clean_merge(self, config: HydraFlowConfig) -> None:
        """When merge_main succeeds, should push and return True."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=True)
        phase._prs.push_branch = AsyncMock(return_value=True)

        result = await phase._merge_with_main(
            pr, issue, config.worktree_base / "issue-42", 0
        )

        assert result is True
        phase._prs.push_branch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_true_after_conflict_resolution(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails but conflict resolution succeeds, should return True."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._prs.push_branch = AsyncMock(return_value=True)

        result = await phase._merge_with_main(
            pr, issue, config.worktree_base / "issue-42", 0
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_and_escalates_on_failure(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """When conflict resolution fails, should escalate and return False."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._prs.push_branch = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()

        result = await phase._merge_with_main(
            pr, issue, config.worktree_base / "issue-42", 0
        )

        assert result is False
        assert phase._state.get_hitl_origin(42) == "hydraflow-review"
        phase._store.enqueue_transition.assert_called_once_with(issue, "hitl")


class TestRunAndPostReview:
    """Unit tests for the _run_and_post_review helper."""

    @pytest.mark.asyncio
    async def test_pushes_fixes_when_made(self, config: HydraFlowConfig) -> None:
        """When reviewer makes fixes, branch should be pushed."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="Fixed.",
            fixes_made=True,
            transcript="THOROUGH_REVIEW_COMPLETE",
        )
        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = AsyncMock()

        result = await phase._run_and_post_review(
            pr, issue, config.worktree_base / "issue-42", "diff", 0
        )

        assert result.fixes_made is True
        phase._prs.push_branch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_posts_summary_as_pr_comment(self, config: HydraFlowConfig) -> None:
        """Review summary should be posted as a PR comment."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create()
        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.push_branch = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._run_and_post_review(
            pr, issue, config.worktree_base / "issue-42", "diff", 0
        )

        phase._prs.post_pr_comment.assert_awaited_once_with(101, "Looks good.")

    @pytest.mark.asyncio
    async def test_skips_submit_review_for_approve(
        self, config: HydraFlowConfig
    ) -> None:
        """submit_review should not be called for APPROVE verdicts."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create()
        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.push_branch = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()

        await phase._run_and_post_review(
            pr, issue, config.worktree_base / "issue-42", "diff", 0
        )

        phase._prs.submit_review.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_submits_review_for_request_changes(
        self, config: HydraFlowConfig
    ) -> None:
        """submit_review should be called for REQUEST_CHANGES verdicts."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)
        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.push_branch = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()

        await phase._run_and_post_review(
            pr, issue, config.worktree_base / "issue-42", "diff", 0
        )

        phase._prs.submit_review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_self_review_error(self, config: HydraFlowConfig) -> None:
        """SelfReviewError should be caught gracefully."""
        from pr_manager import SelfReviewError

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        review = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)
        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.push_branch = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock(
            side_effect=SelfReviewError("cannot review own PR")
        )

        result = await phase._run_and_post_review(
            pr, issue, config.worktree_base / "issue-42", "diff", 0
        )

        assert result.verdict == ReviewVerdict.REQUEST_CHANGES


class TestHandleApprovedMerge:
    """Unit tests for the _handle_approved_merge helper."""

    @pytest.mark.asyncio
    async def test_merge_success_marks_merged(self, config: HydraFlowConfig) -> None:
        """Successful merge should set result.merged and update state."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase._handle_approved_merge(pr, issue, result, "diff", 0)

        assert result.merged is True
        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "merged"

    @pytest.mark.asyncio
    async def test_merge_failure_escalates(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Failed merge should escalate to HITL."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase._handle_approved_merge(pr, issue, result, "diff", 0)

        assert result.merged is False
        assert phase._state.get_hitl_origin(42) == "hydraflow-review"

    @pytest.mark.asyncio
    async def test_merge_success_swaps_labels(self, config: HydraFlowConfig) -> None:
        """Successful merge should swap review label to fixed label."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase._handle_approved_merge(pr, issue, result, "diff", 0)

        phase._prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-fixed")


class TestRunPostMergeHooks:
    """Unit tests for the _run_post_merge_hooks helper."""

    @pytest.mark.asyncio
    async def test_calls_ac_generator(self, config: HydraFlowConfig) -> None:
        """Should call ac_generator.generate when configured."""
        mock_ac = AsyncMock()
        phase = make_review_phase(config, ac_generator=mock_ac)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        await phase._run_post_merge_hooks(pr, issue, result, "diff")

        mock_ac.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_calls_retrospective(self, config: HydraFlowConfig) -> None:
        """Should call retrospective.record when configured."""
        mock_retro = AsyncMock()
        phase = make_review_phase(config)
        phase._retrospective = mock_retro
        phase._post_merge._retrospective = mock_retro
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        await phase._run_post_merge_hooks(pr, issue, result, "diff")

        mock_retro.record.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hook_failure_does_not_block_others(
        self, config: HydraFlowConfig
    ) -> None:
        """If one hook fails, others should still be called."""
        mock_ac = AsyncMock()
        mock_ac.generate = AsyncMock(side_effect=RuntimeError("AC failed"))
        mock_retro = AsyncMock()
        phase = make_review_phase(config, ac_generator=mock_ac)
        phase._retrospective = mock_retro
        phase._post_merge._retrospective = mock_retro
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        # Should not raise
        await phase._run_post_merge_hooks(pr, issue, result, "diff")

        # AC failed but retrospective still called
        mock_retro.record.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_hooks_configured(self, config: HydraFlowConfig) -> None:
        """When no hooks are configured, should complete without errors."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        # Should not raise
        await phase._run_post_merge_hooks(pr, issue, result, "diff")

        # No judge configured — verification issue must never be attempted
        phase._prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_judge_verdict_creates_verification_issue(
        self, config: HydraFlowConfig
    ) -> None:
        """When judge returns a verdict, a verification issue should be created."""
        mock_judge = AsyncMock()
        issue = TaskFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="OK",
                ),
            ],
            summary="1/1 criteria passed, instructions: ready",
            verification_instructions="1. Open the UI page\n2. Click Save",
        )
        mock_judge.judge = AsyncMock(return_value=verdict)
        phase = make_review_phase(config)
        phase._verification_judge = mock_judge
        phase._post_merge._verification_judge = mock_judge
        phase._prs.create_issue = AsyncMock(return_value=500)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()

        await phase._run_post_merge_hooks(
            pr,
            issue,
            result,
            "+++ b/src/ui/App.tsx\n@@\n+<button>Save</button>",
        )

        mock_judge.judge.assert_awaited_once()
        phase._prs.create_issue.assert_awaited_once()
        body = phase._prs.create_issue.call_args[0][1]
        assert "Click Save" in body
        assert phase._state.get_verification_issue(issue.id) == 500

    @pytest.mark.asyncio
    async def test_judge_returns_none_no_verification_issue(
        self, config: HydraFlowConfig
    ) -> None:
        """When judge returns None (no criteria file), no verification issue is created."""
        mock_judge = AsyncMock()
        mock_judge.judge = AsyncMock(return_value=None)
        phase = make_review_phase(config)
        phase._verification_judge = mock_judge
        phase._post_merge._verification_judge = mock_judge
        phase._prs.create_issue = AsyncMock(return_value=0)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        await phase._run_post_merge_hooks(pr, issue, result, "diff")

        mock_judge.judge.assert_awaited_once()
        phase._prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_judge_failure_does_not_create_verification_issue(
        self, config: HydraFlowConfig
    ) -> None:
        """When judge raises, no verification issue is created."""
        mock_judge = AsyncMock()
        mock_judge.judge = AsyncMock(side_effect=RuntimeError("judge failed"))
        phase = make_review_phase(config)
        phase._verification_judge = mock_judge
        phase._post_merge._verification_judge = mock_judge
        phase._prs.create_issue = AsyncMock(return_value=0)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        await phase._run_post_merge_hooks(pr, issue, result, "diff")

        phase._prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_verification_issue_creation_failure_does_not_block_epic_checker(
        self, config: HydraFlowConfig
    ) -> None:
        """When _create_verification_issue raises, epic checker still runs."""
        mock_judge = AsyncMock()
        verdict = JudgeVerdict(issue_number=42)
        mock_judge.judge = AsyncMock(return_value=verdict)
        mock_epic = AsyncMock()
        phase = make_review_phase(config)
        phase._verification_judge = mock_judge
        phase._post_merge._verification_judge = mock_judge
        phase._prs.create_issue = AsyncMock(side_effect=RuntimeError("API failure"))
        phase._epic_checker = mock_epic
        phase._post_merge._epic_checker = mock_epic
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        await phase._run_post_merge_hooks(pr, issue, result, "diff")

        mock_epic.check_and_close_epics.assert_awaited_once()


class TestReviewOneInner:
    """Unit tests for the _review_one_inner coordinator method."""

    @pytest.mark.asyncio
    async def test_returns_issue_not_found(self, config: HydraFlowConfig) -> None:
        """When issue is not in the map, should return 'Issue not found'."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create(issue_number=999)

        wt = config.worktree_base / "issue-999"
        wt.mkdir(parents=True, exist_ok=True)

        result = await phase._review_one_inner(0, pr, {})

        assert result.summary == "Issue not found"

    @pytest.mark.asyncio
    async def test_coordinates_merge_review_and_verdict(
        self, config: HydraFlowConfig
    ) -> None:
        """Should coordinate merge, review, state recording, and verdict handling."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        result = await phase._review_one_inner(0, pr, {42: issue})

        assert result.merged is True
        assert phase._state.to_dict()["reviewed_prs"].get(str(101)) == "approve"

    @pytest.mark.asyncio
    async def test_returns_merge_conflict_summary_when_merge_fails(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """When merge fails and escalates to HITL, should return early with conflict summary."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._prs.push_branch = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        result = await phase._review_one_inner(0, pr, {42: issue})

        assert "Merge conflicts" in result.summary
        assert result.merged is False


# ---------------------------------------------------------------------------
# _handle_rejected_review unit tests
# ---------------------------------------------------------------------------


class TestHandleRejectedReview:
    """Unit tests for the _handle_rejected_review helper."""

    @pytest.mark.asyncio
    async def test_under_cap_returns_true(self, config: HydraFlowConfig) -> None:
        """When under the review fix cap, should return True (preserve worktree)."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=42)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        # 0 attempts < max_review_fix_attempts (2 default)
        returned = await phase._handle_rejected_review(pr, task, result, 0)

        assert returned is True

    @pytest.mark.asyncio
    async def test_under_cap_stores_review_feedback(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, review summary should be saved as feedback for re-implementation."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=42)
        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Fix the error handling logic",
        )

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._handle_rejected_review(pr, task, result, 0)

        assert phase._state.get_review_feedback(42) == "Fix the error handling logic"

    @pytest.mark.asyncio
    async def test_under_cap_swaps_labels_on_issue_and_pr(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, should swap labels from review→ready on both issue and PR."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=42)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._handle_rejected_review(pr, task, result, 0)

        phase._prs.transition.assert_awaited_once_with(42, "ready", pr_number=101)

    @pytest.mark.asyncio
    async def test_under_cap_increments_review_attempts(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, should increment the review attempt counter."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=42)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._handle_rejected_review(pr, task, result, 0)

        assert phase._state.get_review_attempts(42) == 1

    @pytest.mark.asyncio
    async def test_cap_exceeded_returns_false(self, tmp_path: Path) -> None:
        """When review fix cap is exhausted, should return False (destroy worktree)."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_review_fix_attempts=2,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=42)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        # Exhaust cap: 2 attempts already recorded
        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        returned = await phase._handle_rejected_review(pr, task, result, 0)

        assert returned is False

    @pytest.mark.asyncio
    async def test_cap_exceeded_escalates_to_hitl(
        self, tmp_path: Path, event_bus
    ) -> None:
        """When cap is exceeded, should escalate issue to HITL and set state."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_review_fix_attempts=2,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config, event_bus=event_bus)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=42)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        await phase._handle_rejected_review(pr, task, result, 0)

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"
        phase._prs.transition.assert_any_await(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_cap_exceeded_posts_comment_on_issue(self, tmp_path: Path) -> None:
        """When cap exceeded, HITL escalation comment should be posted on the issue."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_review_fix_attempts=1,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=42)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        # Exhaust cap
        phase._state.increment_review_attempts(42)

        await phase._handle_rejected_review(pr, task, result, 0)

        # post_on_pr=False, so comment goes to the issue
        comment_calls = [c.args for c in phase._prs.post_comment.call_args_list]
        assert any("cap exceeded" in c[1].lower() for c in comment_calls)
        phase._prs.post_pr_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_under_cap_posts_requeue_comment(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, should post a re-queue notification on the issue."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=42)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._handle_rejected_review(pr, task, result, 0)

        comment_calls = [c.args for c in phase._prs.post_comment.call_args_list]
        assert any("Re-queuing for implementation" in c[1] for c in comment_calls)

    @pytest.mark.asyncio
    async def test_cap_exceeded_enqueues_hitl_transition(self, tmp_path: Path) -> None:
        """When review fix cap is exceeded, should enqueue HITL transition via store."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_review_fix_attempts=1,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=42)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        # Exhaust cap
        phase._state.increment_review_attempts(42)

        await phase._handle_rejected_review(pr, task, result, 0)

        phase._store.enqueue_transition.assert_called_once_with(task, "hitl")


# ---------------------------------------------------------------------------
# Edge case tests: fix_ci exception and stop_event during CI
# ---------------------------------------------------------------------------


class TestWaitAndFixCIEdgeCases:
    """Edge case tests for wait_and_fix_ci and _review_one error handling."""

    @pytest.mark.asyncio
    async def test_fix_ci_exception_propagates_to_review_one_handler(
        self, config: HydraFlowConfig
    ) -> None:
        """When fix_ci raises, the outer _review_one except catches it."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create(id=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                pr_number=101, issue_number=42, verdict=ReviewVerdict.APPROVE
            )
        )
        # fix_ci raises an exception
        phase._reviewers.fix_ci = AsyncMock(side_effect=RuntimeError("agent crashed"))
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: tests"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        # Exception caught by _review_one outer handler
        assert len(results) == 1
        assert results[0].pr_number == 101
        assert results[0].summary == "Review failed due to unexpected error"
        # PR should NOT have been merged
        phase._prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stop_event_during_ci_wait_returns_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """When stop_event is set, wait_for_ci returns (False, 'Stopped')."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create(id=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                pr_number=101, issue_number=42, verdict=ReviewVerdict.APPROVE
            )
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Stopped"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        # Set stop_event before running
        phase._stop_event.set()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert len(results) == 1
        # PR should NOT have been merged due to CI failure
        assert results[0].merged is False


# ---------------------------------------------------------------------------
# _handle_self_fix_re_review — extracted helper
# ---------------------------------------------------------------------------


class TestHandleSelfFixReReview:
    """Direct tests for the extracted _handle_self_fix_re_review helper."""

    def _setup(self, config: HydraFlowConfig) -> tuple[ReviewPhase, PRInfo, Task, Path]:
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        phase._prs.get_pr_diff = AsyncMock(return_value="updated diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        wt = config.worktree_base / f"issue-{pr.issue_number}"
        wt.mkdir(parents=True, exist_ok=True)
        return phase, pr, issue, wt

    @pytest.mark.asyncio
    async def test_approve_upgrades_result_and_updates_diff(
        self, config: HydraFlowConfig
    ) -> None:
        """Re-review APPROVE should return the new result and updated diff."""
        phase, pr, issue, wt = self._setup(config)
        original = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=True
        )
        approved = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE, fixes_made=False
        )
        phase._reviewers.review = AsyncMock(return_value=approved)

        result, diff = await phase._handle_self_fix_re_review(
            pr, issue, wt, original, "old diff", 0
        )

        assert result.verdict == ReviewVerdict.APPROVE
        assert diff == "updated diff"

    @pytest.mark.asyncio
    async def test_non_approve_preserves_original_result(
        self, config: HydraFlowConfig
    ) -> None:
        """Re-review non-APPROVE should return the original result unchanged."""
        phase, pr, issue, wt = self._setup(config)
        original = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=True
        )
        still_bad = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=False
        )
        phase._reviewers.review = AsyncMock(return_value=still_bad)

        result, _ = await phase._handle_self_fix_re_review(
            pr, issue, wt, original, "old diff", 0
        )

        assert result is original

    @pytest.mark.asyncio
    async def test_non_approve_still_updates_diff(
        self, config: HydraFlowConfig
    ) -> None:
        """Re-review non-APPROVE should still return the refreshed diff for post-merge hooks."""
        phase, pr, issue, wt = self._setup(config)
        original = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=True
        )
        still_bad = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=False
        )
        phase._reviewers.review = AsyncMock(return_value=still_bad)

        _, diff = await phase._handle_self_fix_re_review(
            pr, issue, wt, original, "old diff", 0
        )

        assert diff == "updated diff"

    @pytest.mark.asyncio
    async def test_pushes_fixes_on_re_review(self, config: HydraFlowConfig) -> None:
        """Re-review with fixes_made=True should push the additional fixes."""
        phase, pr, issue, wt = self._setup(config)
        original = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=True
        )
        re_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE, fixes_made=True
        )
        phase._reviewers.review = AsyncMock(return_value=re_result)

        await phase._handle_self_fix_re_review(pr, issue, wt, original, "old diff", 0)

        phase._prs.push_branch.assert_awaited_once_with(wt, pr.branch)

    @pytest.mark.asyncio
    async def test_exception_falls_back_gracefully(
        self, config: HydraFlowConfig
    ) -> None:
        """Exception during re-review should return original result and original diff."""
        phase, pr, issue, wt = self._setup(config)
        original = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=True
        )
        phase._reviewers.review = AsyncMock(
            side_effect=RuntimeError("transient failure")
        )

        result, diff = await phase._handle_self_fix_re_review(
            pr, issue, wt, original, "old diff", 0
        )

        assert result is original
        assert diff == "old diff"
