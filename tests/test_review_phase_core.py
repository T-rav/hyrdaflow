"""Tests for review_phase.py — core review flow and infrastructure."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from events import EventType
from models import (
    CriterionResult,
    CriterionVerdict,
    JudgeVerdict,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    Task,
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
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        results = await phase.review_prs([pr], [issue])

        phase._reviewers.review.assert_awaited_once()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_marks_pr_status_in_state(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

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
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        phase._prs.merge_pr.assert_awaited_once_with(101)

    @pytest.mark.asyncio
    async def test_review_does_not_merge_rejected_pr(
        self, config: HydraFlowConfig
    ) -> None:
        """review_prs should not merge PRs with REQUEST_CHANGES verdict."""
        phase = make_review_phase(
            config,
            default_mocks=True,
            review_result=ReviewResultFactory.create(
                verdict=ReviewVerdict.REQUEST_CHANGES
            ),
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        phase._prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_merges_main_before_reviewing(
        self, config: HydraFlowConfig
    ) -> None:
        """review_prs should merge main and push before reviewing."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=True)

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
        phase = make_review_phase(config, default_mocks=True, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=False)  # Conflicts
        # But agent resolves them
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

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
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)  # Override for this test
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

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
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)  # Override for this test
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"

    @pytest.mark.asyncio
    async def test_review_merge_failure_sets_hitl_cause(
        self, config: HydraFlowConfig
    ) -> None:
        """Merge failure escalation should record cause in state."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)  # Override for this test
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_cause(42) == "PR merge failed on GitHub"

    @pytest.mark.asyncio
    async def test_review_merge_records_lifetime_stats(
        self, config: HydraFlowConfig
    ) -> None:
        """Merging a PR should record both pr_merged and issue_completed."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.pull_main = AsyncMock()

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.prs_merged == 1
        assert stats.issues_completed == 1

    @pytest.mark.asyncio
    async def test_review_merge_labels_issue_hydraflow_fixed(
        self, config: HydraFlowConfig
    ) -> None:
        """Merging a PR should swap label from hydraflow-review to hydraflow-fixed."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        # Should swap to hydraflow-fixed
        phase._prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-fixed")

    @pytest.mark.asyncio
    async def test_review_merge_failure_does_not_record_lifetime_stats(
        self, config: HydraFlowConfig
    ) -> None:
        """Failed merge should not increment lifetime stats."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)  # Override for this test

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.prs_merged == 0
        assert stats.issues_completed == 0

    @pytest.mark.asyncio
    async def test_review_merge_marks_issue_as_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Successful merge should mark issue status as 'merged'."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "merged"

    @pytest.mark.asyncio
    async def test_review_merge_failure_keeps_reviewed_status(
        self, config: HydraFlowConfig
    ) -> None:
        """Failed merge should leave issue as 'reviewed', not 'merged'."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)  # Override for this test

        await phase.review_prs([pr], [issue])

        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "reviewed"

    @pytest.mark.asyncio
    async def test_review_posts_pr_comment_with_summary(
        self, config: HydraFlowConfig
    ) -> None:
        """post_pr_comment should be called with the review summary."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        phase._prs.post_pr_comment.assert_awaited_once_with(101, "Looks good.")

    @pytest.mark.asyncio
    async def test_review_skips_submit_review_for_approve(
        self, config: HydraFlowConfig
    ) -> None:
        """submit_review should NOT be called for approve to avoid self-approval errors."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

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
        phase = make_review_phase(
            config,
            default_mocks=True,
            review_result=ReviewResultFactory.create(verdict=verdict),
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        phase._prs.submit_review.assert_awaited_once_with(101, verdict, "Looks good.")

    @pytest.mark.asyncio
    async def test_review_request_changes_self_review_falls_back_gracefully(
        self, config: HydraFlowConfig
    ) -> None:
        """When submit_review raises SelfReviewError, state should still be marked."""
        from pr_manager import SelfReviewError

        phase = make_review_phase(
            config,
            default_mocks=True,
            review_result=ReviewResultFactory.create(
                verdict=ReviewVerdict.REQUEST_CHANGES
            ),
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.submit_review = AsyncMock(
            side_effect=SelfReviewError(
                "Can not request changes on your own pull request"
            )
        )

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
        review = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="",
            fixes_made=False,
        )
        phase = make_review_phase(config, default_mocks=True, review_result=review)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

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
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)  # Override for this test

        await phase.review_prs([pr], [issue])

        # Review comment + HITL escalation comment
        comment_bodies = [c.args[1] for c in phase._prs.post_pr_comment.call_args_list]
        assert "Looks good." in comment_bodies
        assert any("Merge failed" in b for b in comment_bodies)
        phase._prs.submit_review.assert_not_awaited()


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
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

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
        phase = make_review_phase(config, default_mocks=True, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

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
        phase = make_review_phase(config, default_mocks=True, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        start_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "start"
        ]
        assert len(start_events) == 1
        assert "worker" in start_events[0].data


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
        phase = make_review_phase(config)
        phase._post_merge._ac_generator = mock_ac
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
        phase = make_review_phase(config)
        phase._post_merge._ac_generator = mock_ac
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
        phase._post_merge._verification_judge = mock_judge
        phase._prs.create_issue = AsyncMock(side_effect=RuntimeError("API failure"))
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
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

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
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        # 0 attempts < max_review_fix_attempts (2 default)
        returned = await phase._handle_rejected_review(pr, result, 0)

        assert returned is True

    @pytest.mark.asyncio
    async def test_under_cap_stores_review_feedback(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, review summary should be saved as feedback for re-implementation."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
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

        await phase._handle_rejected_review(pr, result, 0)

        assert phase._state.get_review_feedback(42) == "Fix the error handling logic"

    @pytest.mark.asyncio
    async def test_under_cap_swaps_labels_on_issue_and_pr(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, should swap labels from review→ready on both issue and PR."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._handle_rejected_review(pr, result, 0)

        phase._prs.transition.assert_awaited_once_with(42, "ready", pr_number=101)

    @pytest.mark.asyncio
    async def test_under_cap_increments_review_attempts(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, should increment the review attempt counter."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._handle_rejected_review(pr, result, 0)

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

        returned = await phase._handle_rejected_review(pr, result, 0)

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
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        await phase._handle_rejected_review(pr, result, 0)

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
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        # Exhaust cap
        phase._state.increment_review_attempts(42)

        await phase._handle_rejected_review(pr, result, 0)

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
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._handle_rejected_review(pr, result, 0)

        comment_calls = [c.args for c in phase._prs.post_comment.call_args_list]
        assert any("Re-queuing for implementation" in c[1] for c in comment_calls)


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


# ---------------------------------------------------------------------------
# Skip guard: no new commits since last review (issue #853)
# ---------------------------------------------------------------------------


class TestSkipGuardNoNewCommits:
    """Tests for the skip guard that avoids re-reviewing when no new commits."""

    @pytest.mark.asyncio
    async def test_skips_when_same_sha(self, config: HydraFlowConfig) -> None:
        """When stored SHA matches current HEAD, review should be skipped."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Pre-store the same SHA that get_pr_head_sha will return
        phase._state.set_last_reviewed_sha(42, "abc123def456")
        phase._prs.get_pr_head_sha = AsyncMock(return_value="abc123def456")

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert len(results) == 1
        assert "skipped" in results[0].summary.lower()
        assert "no new commits" in results[0].summary.lower()
        # Reviewer should NOT have been called
        phase._reviewers.review.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_proceeds_with_new_commits(self, config: HydraFlowConfig) -> None:
        """When stored SHA differs from current HEAD, review should proceed."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Stored SHA differs from current
        phase._state.set_last_reviewed_sha(42, "old_sha_111")
        phase._prs.get_pr_head_sha = AsyncMock(return_value="new_sha_222")

        results = await phase.review_prs([pr], [issue])

        assert len(results) == 1
        phase._reviewers.review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_proceeds_when_no_prior_sha(self, config: HydraFlowConfig) -> None:
        """When no stored SHA exists, review should proceed (first review)."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # No prior SHA stored
        assert phase._state.get_last_reviewed_sha(42) is None
        phase._prs.get_pr_head_sha = AsyncMock(return_value="first_sha_abc")

        results = await phase.review_prs([pr], [issue])

        assert len(results) == 1
        phase._reviewers.review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sha_updated_after_review(self, config: HydraFlowConfig) -> None:
        """After a successful review, the SHA should be stored in state."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Return different SHA on the post-review call
        phase._prs.get_pr_head_sha = AsyncMock(
            side_effect=["first_sha", "post_review_sha"]
        )

        await phase.review_prs([pr], [issue])

        # The post-review SHA should be stored
        assert phase._state.get_last_reviewed_sha(42) == "post_review_sha"

    @pytest.mark.asyncio
    async def test_proceeds_when_sha_fetch_fails(self, config: HydraFlowConfig) -> None:
        """When get_pr_head_sha returns empty string (fail), review should proceed (fail-open)."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Even with a stored SHA, an empty current SHA means we can't compare
        phase._state.set_last_reviewed_sha(42, "old_sha")
        phase._prs.get_pr_head_sha = AsyncMock(return_value="")

        results = await phase.review_prs([pr], [issue])

        assert len(results) == 1
        # Review should proceed despite SHA fetch failure
        phase._reviewers.review.assert_awaited_once()


# ---------------------------------------------------------------------------
# Critical exception propagation through _review_one and _handle_self_fix_re_review
# ---------------------------------------------------------------------------


class TestCriticalExceptionPropagation:
    """Tests that critical exceptions propagate through review handlers."""

    @pytest.mark.asyncio
    async def test_auth_error_propagates_through_review_one(
        self, config: HydraFlowConfig
    ) -> None:
        """AuthenticationError should propagate, not be caught by except Exception."""
        from subprocess_util import AuthenticationError

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            side_effect=AuthenticationError("401 Unauthorized")
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        with pytest.raises(AuthenticationError, match="401"):
            await phase.review_prs([pr], [issue])

    @pytest.mark.asyncio
    async def test_credit_error_propagates_through_review_one(
        self, config: HydraFlowConfig
    ) -> None:
        """CreditExhaustedError should propagate, not be caught by except Exception."""
        from subprocess_util import CreditExhaustedError

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            side_effect=CreditExhaustedError("limit reached")
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        with pytest.raises(CreditExhaustedError, match="limit reached"):
            await phase.review_prs([pr], [issue])

    @pytest.mark.asyncio
    async def test_memory_error_propagates_through_review_one(
        self, config: HydraFlowConfig
    ) -> None:
        """MemoryError should propagate, not be caught by except Exception."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(side_effect=MemoryError("OOM"))
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        with pytest.raises(MemoryError, match="OOM"):
            await phase.review_prs([pr], [issue])

    @pytest.mark.asyncio
    async def test_auth_error_propagates_through_self_fix_re_review(
        self, config: HydraFlowConfig
    ) -> None:
        """AuthenticationError in _handle_self_fix_re_review should propagate."""
        from subprocess_util import AuthenticationError

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.get_pr_diff = AsyncMock(
            side_effect=AuthenticationError("401 Unauthorized")
        )

        original_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        with pytest.raises(AuthenticationError, match="401"):
            await phase._handle_self_fix_re_review(
                pr,
                issue,
                config.worktree_base / "issue-42",
                original_result,
                "diff",
                worker_id=0,
            )

    @pytest.mark.asyncio
    async def test_memory_error_propagates_through_self_fix_re_review(
        self, config: HydraFlowConfig
    ) -> None:
        """MemoryError in _handle_self_fix_re_review should propagate."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.get_pr_diff = AsyncMock(side_effect=MemoryError("OOM"))

        original_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        with pytest.raises(MemoryError, match="OOM"):
            await phase._handle_self_fix_re_review(
                pr,
                issue,
                config.worktree_base / "issue-42",
                original_result,
                "diff",
                worker_id=0,
            )

    @pytest.mark.asyncio
    async def test_review_one_cleans_active_issues_on_critical_error(
        self, config: HydraFlowConfig
    ) -> None:
        """Active issues should be cleaned up even when critical errors propagate."""
        from subprocess_util import AuthenticationError

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            side_effect=AuthenticationError("401 Unauthorized")
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        with pytest.raises(AuthenticationError):
            await phase.review_prs([pr], [issue])

        # finally block should still clean up active issues
        assert 42 not in phase._active_issues


# ---------------------------------------------------------------------------
# Extracted helper methods
# ---------------------------------------------------------------------------


class TestCheckShaSkipGuard:
    """Tests for the _check_sha_skip_guard extracted helper."""

    @pytest.mark.asyncio
    async def test_returns_none_for_new_commits(self, config: HydraFlowConfig) -> None:
        """When stored SHA differs from current HEAD, should return None."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        phase._state.set_last_reviewed_sha(pr.issue_number, "old_sha")
        phase._prs.get_pr_head_sha = AsyncMock(return_value="new_sha")

        result = await phase._check_sha_skip_guard(pr)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_result_for_same_sha(self, config: HydraFlowConfig) -> None:
        """When stored SHA matches current HEAD, should return a skip ReviewResult."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        phase._state.set_last_reviewed_sha(pr.issue_number, "abc123")
        phase._prs.get_pr_head_sha = AsyncMock(return_value="abc123")

        result = await phase._check_sha_skip_guard(pr)

        assert result is not None
        assert "skipped" in result.summary.lower()
        assert result.pr_number == pr.number
        assert result.issue_number == pr.issue_number

    @pytest.mark.asyncio
    async def test_returns_none_when_no_stored_sha(
        self, config: HydraFlowConfig
    ) -> None:
        """When there is no stored SHA, should return None (proceed with review)."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        phase._prs.get_pr_head_sha = AsyncMock(return_value="some_sha")

        result = await phase._check_sha_skip_guard(pr)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_head_sha_is_none(
        self, config: HydraFlowConfig
    ) -> None:
        """When get_pr_head_sha returns None, should return None."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        phase._prs.get_pr_head_sha = AsyncMock(return_value=None)

        result = await phase._check_sha_skip_guard(pr)

        assert result is None


class TestRecordReviewOutcome:
    """Tests for the _record_review_outcome extracted helper."""

    @pytest.mark.asyncio
    async def test_records_all_state(self, config: HydraFlowConfig) -> None:
        """Should call all expected state tracker methods."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(duration_seconds=42.0)
        phase._prs.get_pr_head_sha = AsyncMock(return_value="sha_after_review")

        await phase._record_review_outcome(pr, result)

        assert phase._state._data.reviewed_prs[str(pr.number)] == "approve"
        assert phase._state._data.processed_issues[str(pr.issue_number)] == "reviewed"
        assert phase._state.get_last_reviewed_sha(pr.issue_number) == "sha_after_review"

    @pytest.mark.asyncio
    async def test_records_harness_failure_on_rejection(
        self, config: HydraFlowConfig
    ) -> None:
        """Should record harness failure when verdict is not APPROVE."""
        from unittest.mock import MagicMock, patch

        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)
        phase._prs.get_pr_head_sha = AsyncMock(return_value="sha")
        phase._harness_insights = MagicMock()

        with patch("review_phase.record_harness_failure") as mock_record:
            await phase._record_review_outcome(pr, result)
            mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_records_harness_failure_on_comment_verdict(
        self, config: HydraFlowConfig
    ) -> None:
        """Should record harness failure when verdict is COMMENT (also non-APPROVE)."""
        from unittest.mock import MagicMock, patch

        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(verdict=ReviewVerdict.COMMENT)
        phase._prs.get_pr_head_sha = AsyncMock(return_value="sha")
        phase._harness_insights = MagicMock()

        with patch("review_phase.record_harness_failure") as mock_record:
            await phase._record_review_outcome(pr, result)
            mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_harness_failure_on_approve(
        self, config: HydraFlowConfig
    ) -> None:
        """Should NOT record harness failure when verdict is APPROVE."""
        from unittest.mock import MagicMock, patch

        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(verdict=ReviewVerdict.APPROVE)
        phase._prs.get_pr_head_sha = AsyncMock(return_value="sha")
        phase._harness_insights = MagicMock()

        with patch("review_phase.record_harness_failure") as mock_record:
            await phase._record_review_outcome(pr, result)
            mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_duration_recording_when_zero(
        self, config: HydraFlowConfig
    ) -> None:
        """Should not record duration when duration_seconds is 0."""
        from unittest.mock import patch

        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(duration_seconds=0.0)
        phase._prs.get_pr_head_sha = AsyncMock(return_value="sha")

        with patch.object(phase._state, "record_review_duration") as mock_duration:
            await phase._record_review_outcome(pr, result)
            mock_duration.assert_not_called()


class TestCleanupWorktree:
    """Tests for the _cleanup_worktree extracted helper."""

    @pytest.mark.asyncio
    async def test_destroys_when_not_skipped(self, config: HydraFlowConfig) -> None:
        """Worktree should be destroyed when skip=False and stop_event not set."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()

        await phase._cleanup_worktree(pr, result, skip=False)

        phase._worktrees.destroy.assert_awaited_once_with(pr.issue_number)

    @pytest.mark.asyncio
    async def test_preserves_when_skipped(self, config: HydraFlowConfig) -> None:
        """Worktree should NOT be destroyed when skip=True."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()

        await phase._cleanup_worktree(pr, result, skip=True)

        phase._worktrees.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preserves_when_stop_event_set_and_not_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Worktree preserved when stop_event is set and PR not merged."""
        phase = make_review_phase(config)
        phase._stop_event.set()
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()
        result.merged = False

        await phase._cleanup_worktree(pr, result, skip=False)

        phase._worktrees.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_destroys_when_stop_event_set_but_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Worktree should be destroyed when stop_event is set but PR was merged."""
        phase = make_review_phase(config)
        phase._stop_event.set()
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()
        result.merged = True

        await phase._cleanup_worktree(pr, result, skip=False)

        phase._worktrees.destroy.assert_awaited_once_with(pr.issue_number)


class TestConstructorDefaultHelpers:
    """Tests that ReviewPhase builds default helpers when not provided."""

    def test_builds_default_conflict_resolver(self, config: HydraFlowConfig) -> None:
        """ReviewPhase should build a MergeConflictResolver when not provided."""
        from merge_conflict_resolver import MergeConflictResolver

        phase = make_review_phase(config)

        assert isinstance(phase._conflict_resolver, MergeConflictResolver)

    def test_builds_default_post_merge_handler(self, config: HydraFlowConfig) -> None:
        """ReviewPhase should build a PostMergeHandler with all optional deps None."""
        from post_merge_handler import PostMergeHandler

        phase = make_review_phase(config)

        assert isinstance(phase._post_merge, PostMergeHandler)
        # Verify all optional post-merge dependencies default to None, not to
        # values carried over from removed ReviewPhase constructor parameters.
        assert phase._post_merge._ac_generator is None
        assert phase._post_merge._retrospective is None
        assert phase._post_merge._verification_judge is None
        assert phase._post_merge._epic_checker is None
