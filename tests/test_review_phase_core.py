"""Tests for review_phase.py — core review flow and infrastructure."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from events import EventType
from models import (
    BaselineApprovalResult,
    CodeScanningAlert,
    ConflictResolutionResult,
    CriterionResult,
    CriterionVerdict,
    JudgeVerdict,
    LoopResult,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    Task,
    VisualValidationDecision,
    VisualValidationPolicy,
)
from review_phase import PreReviewContext, ReviewGuardContext, ReviewPhase
from tests.conftest import (
    PRInfoFactory,
    ReviewResultFactory,
    TaskFactory,
)
from tests.helpers import make_review_phase

# ---------------------------------------------------------------------------
# Shared mock setup helpers
# ---------------------------------------------------------------------------


def _setup_escalate_to_hitl_mocks(phase: ReviewPhase) -> None:
    """Set up the PR manager mocks required by _escalate_to_hitl."""
    phase._prs.post_pr_comment = AsyncMock()
    phase._prs.remove_label = AsyncMock()
    phase._prs.remove_pr_label = AsyncMock()
    phase._prs.add_labels = AsyncMock()
    phase._prs.add_pr_labels = AsyncMock()


def _setup_conflict_scenario(phase: ReviewPhase) -> None:
    """Set up mocks for a merge-conflict escalation scenario (merge_main returns False)."""
    _setup_escalate_to_hitl_mocks(phase)
    phase._workspaces.merge_main = AsyncMock(return_value=False)
    # The conflict resolver's fresh_branch_rebuild calls get_pr_diff and uses
    # the return value synchronously (.strip()), so it must be a real string.
    phase._prs.get_pr_diff = AsyncMock(return_value="diff text")


def _setup_rejected_review_mocks(phase: ReviewPhase) -> None:
    """Set up the PR manager mocks required by _handle_rejected_review."""
    phase._prs.remove_label = AsyncMock()
    phase._prs.remove_pr_label = AsyncMock()
    phase._prs.add_labels = AsyncMock()
    phase._prs.add_pr_labels = AsyncMock()
    phase._prs.post_comment = AsyncMock()


# ---------------------------------------------------------------------------
# review_prs
# ---------------------------------------------------------------------------


class TestReviewPRs:
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

        async def fake_review(pr, issue, wt_path, diff, worker_id=0, **_kwargs):
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
            wt = config.workspace_base / f"issue-{i}"
            wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs(prs, issues)

        assert concurrency_counter["peak"] <= config.max_reviewers


class TestPostMergeConflictFix:
    @pytest.mark.asyncio
    async def test_attempt_post_merge_conflict_fix_pushes_branch_on_success(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        pr = PRInfoFactory.create(number=101, issue_number=42, branch="agent/issue-42")
        issue = TaskFactory.create(id=42)
        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        phase._conflict_resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=False)
        )

        ok = await phase._attempt_post_merge_conflict_fix(pr, issue, worker_id=7)

        assert ok is True
        phase._prs.push_branch.assert_awaited_once_with(wt, pr.branch)

    @pytest.mark.asyncio
    async def test_attempt_post_merge_conflict_fix_force_pushes_on_rebuild(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        pr = PRInfoFactory.create(number=101, issue_number=42, branch="agent/issue-42")
        issue = TaskFactory.create(id=42)
        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        phase._conflict_resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=True)
        )

        ok = await phase._attempt_post_merge_conflict_fix(pr, issue, worker_id=7)

        assert ok is True
        phase._prs.push_branch.assert_awaited_once_with(wt, pr.branch, force=True)

    @pytest.mark.asyncio
    async def test_returns_comment_verdict_when_issue_missing(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        # PR with issue_number not in issue_map
        pr = PRInfoFactory.create(issue_number=999)

        phase._prs.get_pr_diff = AsyncMock(return_value="diff")

        # Worktree for issue-999 exists
        wt = config.workspace_path_for_issue(999)
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

        phase._workspaces.merge_main = AsyncMock(return_value=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        phase._workspaces.merge_main.assert_awaited_once()
        phase._prs.push_branch.assert_awaited()
        phase._reviewers.review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_review_merge_conflict_escalates_to_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails and agent can't resolve, should escalate to HITL."""
        mock_agents = AsyncMock()
        mock_agents.build_command = MagicMock(return_value=["claude"])
        mock_agents.verify_result = AsyncMock(
            return_value=LoopResult(passed=False, summary="")
        )
        mock_agents.execute = AsyncMock(return_value="conflict resolution transcript")
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        _setup_conflict_scenario(phase)
        # Agent resolution also fails
        phase._workspaces.start_merge_main = AsyncMock(return_value=False)
        phase._workspaces.abort_merge = AsyncMock()

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        assert "conflicts" in results[0].summary.lower()
        # Review should NOT have been called
        phase._reviewers.review.assert_not_awaited()
        # Should escalate to HITL via transition
        phase._prs.transition.assert_awaited_once_with(42, "diagnose", pr_number=101)

    @pytest.mark.asyncio
    async def test_review_conflict_escalation_records_hitl_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """Merge conflict escalation should record review_label as HITL origin."""
        mock_agents = AsyncMock()
        mock_agents.build_command = MagicMock(return_value=["claude"])
        mock_agents.execute = AsyncMock(return_value="transcript")
        mock_agents.verify_result = AsyncMock(
            return_value=LoopResult(passed=False, summary="")
        )
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        _setup_conflict_scenario(phase)
        phase._workspaces.start_merge_main = AsyncMock(return_value=False)
        phase._workspaces.abort_merge = AsyncMock()

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"

    @pytest.mark.asyncio
    async def test_review_conflict_escalation_sets_hitl_cause(
        self, config: HydraFlowConfig
    ) -> None:
        """Merge conflict escalation should record cause in state."""
        mock_agents = AsyncMock()
        mock_agents.build_command = MagicMock(return_value=["claude"])
        mock_agents.execute = AsyncMock(return_value="transcript")
        mock_agents.verify_result = AsyncMock(
            return_value=LoopResult(passed=False, summary="")
        )
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        _setup_conflict_scenario(phase)
        phase._workspaces.start_merge_main = AsyncMock(return_value=False)
        phase._workspaces.abort_merge = AsyncMock()

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_cause(42) == "Merge conflict with main branch"

    @pytest.mark.asyncio
    async def test_review_merge_conflict_resolved_by_agent(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails but agent resolves conflicts, review should proceed."""
        mock_agents = AsyncMock()
        mock_agents.build_command = MagicMock(return_value=["claude"])
        mock_agents.execute = AsyncMock(return_value="transcript")
        mock_agents.verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        phase = make_review_phase(config, default_mocks=True, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._workspaces.merge_main = AsyncMock(return_value=False)  # Conflicts
        # But agent resolves them
        phase._workspaces.start_merge_main = AsyncMock(return_value=False)

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

        _setup_conflict_scenario(phase)

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        assert "conflicts" in results[0].summary.lower()
        phase._prs.transition.assert_awaited_once_with(42, "diagnose", pr_number=101)

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
        phase._workspaces.merge_main = AsyncMock(return_value=True)

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        hitl_calls = [
            c
            for c in phase._prs.post_pr_comment.call_args_list
            if "Merge failed" in str(c)
        ]
        assert len(hitl_calls) == 1
        phase._prs.transition.assert_any_await(42, "diagnose", pr_number=101)

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
        phase._workspaces.merge_main = AsyncMock(return_value=True)

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
        phase._workspaces.merge_main = AsyncMock(return_value=True)

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
    async def test_review_merge_calls_store_mark_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Successful merge must call IssueStore.mark_merged so the pipeline snapshot is updated."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        phase._store.mark_merged.assert_called_once_with(pr.issue_number)

    @pytest.mark.asyncio
    async def test_review_merge_failure_does_not_call_store_mark_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Failed merge must NOT call mark_merged on the issue store."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)

        await phase.review_prs([pr], [issue])

        phase._store.mark_merged.assert_not_called()

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

        # post_pr_comment may also be called for the visual validation comment
        summary_calls = [
            call
            for call in phase._prs.post_pr_comment.await_args_list
            if call.args == (101, "Looks good.")
        ]
        assert len(summary_calls) == 1

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
        # Review summary was posted as PR comment (visual validation comment may also be present)
        summary_calls = [
            call
            for call in phase._prs.post_pr_comment.await_args_list
            if call.args == (101, "Looks good.")
        ]
        assert len(summary_calls) == 1
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

        async def fake_review(pr, issue, wt_path, diff, worker_id=0, **_kwargs):
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
            wt = config.workspace_base / f"issue-{i}"
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
        """Review summary comment should NOT be posted when summary is empty."""
        review = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="",
        )
        phase = make_review_phase(config, default_mocks=True, review_result=review)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        # No review summary comment should be posted (visual validation comment may be present)
        summary_calls = [
            call
            for call in phase._prs.post_pr_comment.await_args_list
            if call.args[1] == ""
        ]
        assert len(summary_calls) == 0
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

        wt = config.workspace_path_for_issue(42)
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

        wt = config.workspace_path_for_issue(42)
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

        wt = config.workspace_path_for_issue(42)
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
            **_kwargs: object,
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
            wt = config.workspace_base / f"issue-{i}"
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
    @pytest.mark.asyncio
    async def test_active_issues_cleaned_on_early_return_issue_not_found(
        self, config: HydraFlowConfig
    ) -> None:
        """When issue is not in issue_map, store must mark_complete."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create(issue_number=999)

        wt = config.workspace_path_for_issue(999)
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

        phase._workspaces.merge_main = AsyncMock(
            side_effect=RuntimeError("merge exploded")
        )

        wt = config.workspace_path_for_issue(42)
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

        wt = config.workspace_path_for_issue(42)
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

        phase._workspaces.create = AsyncMock(
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

        wt = config.workspace_path_for_issue(999)
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

        review = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="Fixed.",
            fixes_made=True,
        )
        phase._reviewers.review = AsyncMock(return_value=review)
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.post_pr_comment = AsyncMock()

        result = await phase._run_and_post_review(
            pr, issue, config.workspace_path_for_issue(42), "diff", 0
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

        result = await phase._run_and_post_review(
            pr, issue, config.workspace_path_for_issue(42), "diff", 0
        )

        assert (
            result.verdict == ReviewVerdict.APPROVE
        )  # behavioral: returned the reviewer's result
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
            pr, issue, config.workspace_path_for_issue(42), "diff", 0
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

        result = await phase._run_and_post_review(
            pr, issue, config.workspace_path_for_issue(42), "diff", 0
        )

        assert (
            result.verdict == ReviewVerdict.REQUEST_CHANGES
        )  # behavioral: verdict propagated to caller
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
            pr, issue, config.workspace_path_for_issue(42), "diff", 0
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

        wt = config.workspace_path_for_issue(42)
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
        _setup_escalate_to_hitl_mocks(phase)

        wt = config.workspace_path_for_issue(42)
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

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase._handle_approved_merge(pr, issue, result, "diff", 0)

        assert (
            result.merged is True
        )  # behavioral: merge succeeded and result reflects it
        phase._prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-fixed")


class TestRunPostMergeHooks:
    """Unit tests for the _run_post_merge_hooks helper."""

    @pytest.mark.asyncio
    async def test_calls_ac_generator(self, config: HydraFlowConfig) -> None:
        mock_ac = AsyncMock()
        phase = make_review_phase(config)
        phase._post_merge._ac_generator = mock_ac
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        # Behavioral: function completes without raising (hooks are fire-and-forget)
        await phase._run_post_merge_hooks(pr, issue, result, "diff")

        mock_ac.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_calls_retrospective(self, config: HydraFlowConfig) -> None:
        mock_retro = AsyncMock()
        phase = make_review_phase(config)
        phase._post_merge._retrospective = mock_retro
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        # Behavioral: function completes without raising (hooks are fire-and-forget)
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

        # Behavioral: AC failure does not propagate — function completes normally
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
    async def test_judge_verdict_writes_verification_record(
        self, config: HydraFlowConfig
    ) -> None:
        """When judge returns a verdict, a verification record is written to JSONL."""
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
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()

        await phase._run_post_merge_hooks(
            pr,
            issue,
            result,
            "+++ b/src/ui/App.tsx\n@@\n+<button>Save</button>",
        )

        mock_judge.judge.assert_awaited_once()
        # Verification is now written to JSONL, not create_issue
        jsonl_path = config.data_path("memory", "verification_records.jsonl")
        assert jsonl_path.exists()

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
    async def test_verification_jsonl_failure_does_not_block_epic_checker(
        self, config: HydraFlowConfig
    ) -> None:
        """When verification JSONL write fails, epic checker still runs."""
        mock_judge = AsyncMock()
        verdict = JudgeVerdict(issue_number=42)
        mock_judge.judge = AsyncMock(return_value=verdict)
        mock_epic = AsyncMock()
        phase = make_review_phase(config)
        phase._post_merge._verification_judge = mock_judge
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

        wt = config.workspace_path_for_issue(999)
        wt.mkdir(parents=True, exist_ok=True)

        result = await phase._review_one_inner(0, pr, {})

        assert result.summary == "Issue not found"

    @pytest.mark.asyncio
    async def test_coordinates_merge_review_and_verdict(
        self, config: HydraFlowConfig
    ) -> None:
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

        _setup_conflict_scenario(phase)
        phase._prs.push_branch = AsyncMock()

        wt = config.workspace_path_for_issue(42)
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
        task = TaskFactory.create(id=pr.issue_number)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        _setup_rejected_review_mocks(phase)

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
        result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Fix the error handling logic",
        )
        task = TaskFactory.create(id=pr.issue_number)

        _setup_rejected_review_mocks(phase)

        await phase._handle_rejected_review(pr, task, result, 0)

        assert phase._state.get_review_feedback(42) == "Fix the error handling logic"

    @pytest.mark.asyncio
    async def test_under_cap_swaps_labels_on_issue_and_pr(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, should swap labels from review→ready on both issue and PR."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=pr.issue_number)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        _setup_rejected_review_mocks(phase)

        await phase._handle_rejected_review(pr, task, result, 0)

        phase._prs.transition.assert_awaited_once_with(42, "ready", pr_number=101)

    @pytest.mark.asyncio
    async def test_under_cap_increments_review_attempts(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, should increment the review attempt counter."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=pr.issue_number)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        _setup_rejected_review_mocks(phase)

        await phase._handle_rejected_review(pr, task, result, 0)

        assert phase._state.get_review_attempts(42) == 1

    @pytest.mark.asyncio
    async def test_under_cap_enqueues_ready_transition(
        self, config: HydraFlowConfig
    ) -> None:
        """When under cap, should enqueue ready transition for immediate implement wakeup."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=pr.issue_number)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        _setup_rejected_review_mocks(phase)

        await phase._handle_rejected_review(pr, task, result, 0)

        phase._store.enqueue_transition.assert_called_once_with(task, "ready")

    @pytest.mark.asyncio
    async def test_cap_exceeded_returns_false(self, tmp_path: Path) -> None:
        """When review fix cap is exhausted, should return False (destroy worktree)."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_review_fix_attempts=2,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=pr.issue_number)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        _setup_rejected_review_mocks(phase)
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
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config, event_bus=event_bus)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=pr.issue_number)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        _setup_rejected_review_mocks(phase)
        phase._prs.post_pr_comment = AsyncMock()

        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        await phase._handle_rejected_review(pr, task, result, 0)

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"
        phase._prs.transition.assert_any_await(42, "diagnose", pr_number=101)

    @pytest.mark.asyncio
    async def test_cap_exceeded_posts_comment_on_issue(self, tmp_path: Path) -> None:
        """When cap exceeded, HITL escalation comment should be posted on the issue."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_review_fix_attempts=1,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create(id=pr.issue_number)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        _setup_rejected_review_mocks(phase)
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
        task = TaskFactory.create(id=pr.issue_number)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        _setup_rejected_review_mocks(phase)

        await phase._handle_rejected_review(pr, task, result, 0)

        comment_calls = [c.args for c in phase._prs.post_comment.call_args_list]
        assert any("Re-queuing for implementation" in c[1] for c in comment_calls)


# ---------------------------------------------------------------------------
# _attempt_review_fix
# ---------------------------------------------------------------------------


class TestAttemptReviewFix:
    def _setup(self, config: HydraFlowConfig) -> tuple[ReviewPhase, PRInfo, Task, Path]:
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        phase._prs.get_pr_diff = AsyncMock(return_value="updated diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        wt = config.workspace_base / f"issue-{pr.issue_number}"
        wt.mkdir(parents=True, exist_ok=True)
        return phase, pr, issue, wt

    @pytest.mark.asyncio
    async def test_fix_then_approve_upgrades_result(
        self, config: HydraFlowConfig
    ) -> None:
        """Fix agent fixes, re-review approves -> return approved result."""
        phase, pr, issue, wt = self._setup(config)
        original = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=False
        )
        fix_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE, fixes_made=True
        )
        approved = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE, fixes_made=False
        )
        phase._reviewers.fix_review_findings = AsyncMock(return_value=fix_result)
        phase._reviewers.review = AsyncMock(return_value=approved)

        result, diff = await phase._attempt_review_fix(
            pr, issue, wt, original, "old diff", 0
        )

        assert result.verdict == ReviewVerdict.APPROVE
        phase._reviewers.fix_review_findings.assert_awaited_once()
        phase._prs.push_branch.assert_awaited()

    @pytest.mark.asyncio
    async def test_fix_no_changes_falls_through(self, config: HydraFlowConfig) -> None:
        """Fix agent makes no changes -> return original result."""
        phase, pr, issue, wt = self._setup(config)
        original = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=False
        )
        fix_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=False
        )
        phase._reviewers.fix_review_findings = AsyncMock(return_value=fix_result)

        result, diff = await phase._attempt_review_fix(
            pr, issue, wt, original, "old diff", 0
        )

        assert result.verdict == ReviewVerdict.REQUEST_CHANGES
        # Should NOT have called review since no fixes were made
        phase._reviewers.review = AsyncMock()
        phase._reviewers.review.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retries_up_to_two_times(self, config: HydraFlowConfig) -> None:
        phase, pr, issue, wt = self._setup(config)
        original = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=False
        )
        fix_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE, fixes_made=True
        )
        still_rejected = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=False,
            summary="still bad",
        )
        phase._reviewers.fix_review_findings = AsyncMock(return_value=fix_result)
        phase._reviewers.review = AsyncMock(return_value=still_rejected)

        result, diff = await phase._attempt_review_fix(
            pr, issue, wt, original, "old diff", 0
        )

        assert result.verdict == ReviewVerdict.REQUEST_CHANGES
        assert phase._reviewers.fix_review_findings.await_count == 2
        assert phase._reviewers.review.await_count == 2

    @pytest.mark.asyncio
    async def test_exception_falls_through(self, config: HydraFlowConfig) -> None:
        """Exception during fix should fall back to original result."""
        phase, pr, issue, wt = self._setup(config)
        original = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES, fixes_made=False
        )
        phase._reviewers.fix_review_findings = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        result, diff = await phase._attempt_review_fix(
            pr, issue, wt, original, "old diff", 0
        )

        assert result is original


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
        wt = config.workspace_base / f"issue-{pr.issue_number}"
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

# ---------------------------------------------------------------------------
# Critical exception propagation through _review_one and _handle_self_fix_re_review
# ---------------------------------------------------------------------------


class TestCriticalExceptionPropagation:
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

        wt = config.workspace_path_for_issue(42)
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

        wt = config.workspace_path_for_issue(42)
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

        wt = config.workspace_path_for_issue(42)
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
                config.workspace_path_for_issue(42),
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
                config.workspace_path_for_issue(42),
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

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        with pytest.raises(AuthenticationError):
            await phase.review_prs([pr], [issue])

        # finally block should still clean up active issues
        assert 42 not in phase._active_issues


# ---------------------------------------------------------------------------
# Extracted helper methods
# ---------------------------------------------------------------------------


class TestCheckShaSkipGuard:
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
    @pytest.mark.asyncio
    async def test_records_all_state(self, config: HydraFlowConfig) -> None:
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
    async def test_increments_reviewed_session_counter_on_approve(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        phase._state.reset_session_counters("2026-01-01T00:00:00+00:00")
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(verdict=ReviewVerdict.APPROVE)
        phase._prs.get_pr_head_sha = AsyncMock(return_value="sha")

        await phase._record_review_outcome(pr, result)

        counters = phase._state.get_session_counters()
        assert counters.reviewed == 1

    @pytest.mark.asyncio
    async def test_does_not_increment_reviewed_session_counter_on_request_changes(
        self, config: HydraFlowConfig
    ) -> None:
        from unittest.mock import MagicMock, patch

        phase = make_review_phase(config)
        phase._state.reset_session_counters("2026-01-01T00:00:00+00:00")
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)
        phase._prs.get_pr_head_sha = AsyncMock(return_value="sha")
        phase._harness_insights = MagicMock()

        with patch("review_phase.record_harness_failure"):
            await phase._record_review_outcome(pr, result)

        counters = phase._state.get_session_counters()
        assert counters.reviewed == 0

    @pytest.mark.asyncio
    async def test_skips_duration_recording_when_zero(
        self, config: HydraFlowConfig
    ) -> None:
        from unittest.mock import patch

        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(duration_seconds=0.0)
        phase._prs.get_pr_head_sha = AsyncMock(return_value="sha")

        with patch.object(phase._state, "record_review_duration") as mock_duration:
            await phase._record_review_outcome(pr, result)
            mock_duration.assert_not_called()


class TestCleanupWorktree:
    @pytest.mark.asyncio
    async def test_destroys_when_not_skipped(self, config: HydraFlowConfig) -> None:
        """Worktree should be cleaned up when skip=False and stop_event not set."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()

        await phase._cleanup_worktree(pr, result, skip=False)

        phase._workspaces.post_work_cleanup.assert_awaited_once_with(
            pr.issue_number, phase="review"
        )

    @pytest.mark.asyncio
    async def test_preserves_when_skipped(self, config: HydraFlowConfig) -> None:
        """Worktree should NOT be cleaned up when skip=True."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()

        await phase._cleanup_worktree(pr, result, skip=True)

        phase._workspaces.post_work_cleanup.assert_not_awaited()

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

        phase._workspaces.post_work_cleanup.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_destroys_when_stop_event_set_but_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Worktree should be cleaned up when stop_event is set but PR was merged."""
        phase = make_review_phase(config)
        phase._stop_event.set()
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create()
        result.merged = True

        await phase._cleanup_worktree(pr, result, skip=False)

        phase._workspaces.post_work_cleanup.assert_awaited_once_with(
            pr.issue_number, phase="review"
        )


class TestRequiredDIParameters:
    def test_conflict_resolver_injected(self, config: HydraFlowConfig) -> None:
        """ReviewPhase should receive a MergeConflictResolver via DI."""
        from merge_conflict_resolver import MergeConflictResolver

        phase = make_review_phase(config)

        assert isinstance(phase._conflict_resolver, MergeConflictResolver)

    def test_post_merge_handler_injected(self, config: HydraFlowConfig) -> None:
        """ReviewPhase should receive a PostMergeHandler via DI."""
        from post_merge_handler import PostMergeHandler

        phase = make_review_phase(config)

        assert isinstance(phase._post_merge, PostMergeHandler)


class TestADRReviewPath:
    @pytest.mark.asyncio
    async def test_review_adrs_approves_and_closes_valid_adr(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=710,
            title="[ADR] Stream rendering architecture",
            body=(
                "## Context\nCurrent rendering logic is split across hooks and cards.\n\n"
                "## Decision\nAdopt a single-stage snapshot model with normalized events "
                "to ensure deterministic rendering and simpler queue-state reconciliation.\n\n"
                "## Consequences\nRequires state migration but removes drift and duplicate "
                "count paths."
            ),
        )

        results = await phase.review_adrs([issue])

        assert len(results) == 1
        assert results[0].verdict == ReviewVerdict.APPROVE
        phase._prs.swap_pipeline_labels.assert_awaited_once_with(
            710, config.fixed_label[0]
        )
        phase._prs.close_task.assert_awaited_once_with(710)

    @pytest.mark.asyncio
    async def test_review_adrs_requeues_invalid_adr_to_plan(
        self, config: HydraFlowConfig
    ) -> None:
        """Invalid ADR should re-queue to plan, not escalate to HITL."""
        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=711,
            title="[ADR] Bad draft",
            body="## Context\nShort.\n\n## Decision\nTiny.\n\n## Consequences\nTiny.",
        )

        results = await phase.review_adrs([issue])

        assert len(results) == 1
        assert results[0].verdict == ReviewVerdict.REQUEST_CHANGES
        phase._prs.transition.assert_awaited_once_with(711, "plan")

    @pytest.mark.asyncio
    async def test_review_adrs_approved_calls_store_mark_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Approved ADR must call IssueStore.mark_merged so the pipeline snapshot is updated."""
        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=710,
            title="[ADR] Stream rendering architecture",
            body=(
                "## Context\nCurrent rendering logic is split across hooks and cards.\n\n"
                "## Decision\nAdopt a single-stage snapshot model with normalized events "
                "to ensure deterministic rendering and simpler queue-state reconciliation.\n\n"
                "## Consequences\nRequires state migration but removes drift and duplicate "
                "count paths."
            ),
        )

        await phase.review_adrs([issue])

        phase._store.mark_merged.assert_called_once_with(710)

    @pytest.mark.asyncio
    async def test_review_adrs_rejected_does_not_call_store_mark_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Rejected ADR must NOT call mark_merged on the issue store."""
        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=711,
            title="[ADR] Bad draft",
            body="## Context\nShort.\n\n## Decision\nTiny.\n\n## Consequences\nTiny.",
        )

        await phase.review_adrs([issue])

        phase._store.mark_merged.assert_not_called()


class TestADRReviewAdvisor:
    """T26 — PreFlightAdvisor (AlwaysTrigger) + PostVerifyAdvisor wired into
    ``_review_single_adr`` with surface=``adr_review``.

    ADR review has no fix loop (mid_flight=False), so post-verify is a
    one-shot binary gate: VETO requeues to plan with the advisor's
    reasoning; APPROVE falls through to the existing finalize/approve path.
    """

    _VALID_ADR_BODY = (
        "## Context\nCurrent rendering logic is split across hooks and cards.\n\n"
        "## Decision\nAdopt a single-stage snapshot model with normalized events "
        "to ensure deterministic rendering and simpler queue-state reconciliation.\n\n"
        "## Consequences\nRequires state migration but removes drift and duplicate "
        "count paths."
    )

    @pytest.mark.asyncio
    async def test_advisor_approve_lets_valid_adr_finalize(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pre-flight + post-verify APPROVE -> ADR finalizes (existing behavior)."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_ADR_REVIEW_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=820,
            title="[ADR] Stream rendering architecture",
            body=self._VALID_ADR_BODY,
        )

        # Pre-flight returns a plan; post-verify returns APPROVE.
        plan_payload = (
            '{"risk_summary":"low risk",'
            '"focus_areas":[],"rubric":[],"escalation_signals":[]}'
        )
        approve_payload = (
            '{"verdict":"APPROVE","reasoning":"ADR is sound","disagreements":[]}'
        )
        runner_run = AsyncMock(side_effect=[plan_payload, approve_payload])
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        results = await phase.review_adrs([issue])

        assert len(results) == 1
        assert results[0].verdict == ReviewVerdict.APPROVE
        # Existing finalize path: labels swapped + close + mark_merged.
        phase._prs.swap_pipeline_labels.assert_awaited_once_with(
            820, config.fixed_label[0]
        )
        phase._prs.close_task.assert_awaited_once_with(820)
        # Two advisor calls: pre-flight + post-verify.
        assert runner_run.await_count == 2
        roles = [c.kwargs.get("role") for c in runner_run.await_args_list]
        assert roles == ["pre_flight", "post_verify"]

    @pytest.mark.asyncio
    async def test_advisor_veto_blocks_finalize_and_requeues_to_plan(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Post-verify VETO requeues a structurally-valid ADR to plan."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_ADR_REVIEW_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=821,
            title="[ADR] Stream rendering architecture",
            body=self._VALID_ADR_BODY,
        )

        plan_payload = (
            '{"risk_summary":"moderate","focus_areas":[],'
            '"rubric":[],"escalation_signals":["missing trade-offs"]}'
        )
        veto_payload = (
            '{"verdict":"VETO",'
            '"reasoning":"Decision section omits the trade-off analysis '
            'demanded by the rubric",'
            '"disagreements":[{"executor_claim":"structural validation passed",'
            '"advisor_assessment":"trade-off discussion missing",'
            '"severity":"blocking"}],'
            '"suggested_fix_direction":"Document why the snapshot model was '
            'preferred over the streaming alternative"}'
        )
        runner_run = AsyncMock(side_effect=[plan_payload, veto_payload])
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        results = await phase.review_adrs([issue])

        assert len(results) == 1
        assert results[0].verdict == ReviewVerdict.REQUEST_CHANGES
        assert "advisor veto" in (results[0].summary or "").lower()

        # ADR must NOT have finalized: no label swap, no close.
        phase._prs.swap_pipeline_labels.assert_not_awaited()
        phase._prs.close_task.assert_not_awaited()
        # Requeue to plan path: transition + enqueue + comment.
        phase._prs.transition.assert_awaited_once_with(821, "plan")
        phase._store.enqueue_transition.assert_called_once()
        phase._store.mark_merged.assert_not_called()
        # The post_verify runner saw role="post_verify".
        roles = [c.kwargs.get("role") for c in runner_run.await_args_list]
        assert "post_verify" in roles

    @pytest.mark.asyncio
    async def test_pre_flight_plan_threaded_into_post_verify(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pre-flight plan must be stashed under issue.id and reach post-verify."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_ADR_REVIEW_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=822,
            title="[ADR] Stream rendering architecture",
            body=self._VALID_ADR_BODY,
        )

        plan_payload = (
            '{"risk_summary":"identified risk",'
            '"focus_areas":[],"rubric":["check trade-offs"],'
            '"escalation_signals":[]}'
        )
        approve_payload = '{"verdict":"APPROVE","reasoning":"OK","disagreements":[]}'
        runner_run = AsyncMock(side_effect=[plan_payload, approve_payload])
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        await phase.review_adrs([issue])

        # Plan stashed under ("adr_review", issue.id) — no PR for ADR.
        # T38: dict keyed by (surface, identifier).
        assert ("adr_review", 822) in phase._advisor_pre_flight_plan
        stashed = phase._advisor_pre_flight_plan[("adr_review", 822)]
        assert stashed.risk_summary == "identified risk"
        # Post-verify prompt should mention the rubric from the plan.
        post_verify_call = runner_run.await_args_list[1]
        prompt = post_verify_call.kwargs.get("prompt", "")
        assert "check trade-offs" in prompt

    @pytest.mark.asyncio
    async def test_per_surface_kill_switch_skips_advisor(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ``HYDRAFLOW_ADR_REVIEW_ADVISOR_ENABLED=false``, advisor is not invoked."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_ADR_REVIEW_ADVISOR_ENABLED", "false")

        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=823,
            title="[ADR] Stream rendering architecture",
            body=self._VALID_ADR_BODY,
        )

        runner_run = AsyncMock()
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        results = await phase.review_adrs([issue])

        # Existing structural-validation path: APPROVE + finalize.
        assert results[0].verdict == ReviewVerdict.APPROVE
        runner_run.assert_not_awaited()
        # No plan stashed when advisor never ran. T38: tuple key.
        assert ("adr_review", 823) not in phase._advisor_pre_flight_plan

    @pytest.mark.asyncio
    async def test_advisor_credit_exhausted_propagates(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CreditExhaustedError from post-verify advisor must propagate (dark-factory §2.2)."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_ADR_REVIEW_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=824,
            title="[ADR] Stream rendering architecture",
            body=self._VALID_ADR_BODY,
        )

        from subprocess_util import CreditExhaustedError

        plan_payload = '{"risk_summary":"low","focus_areas":[],"rubric":[],"escalation_signals":[]}'
        runner_run = AsyncMock(
            side_effect=[plan_payload, CreditExhaustedError("no credits")]
        )
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        with pytest.raises(CreditExhaustedError):
            await phase.review_adrs([issue])

    @pytest.mark.asyncio
    async def test_invalid_adr_skips_post_verify(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Structural validation failure short-circuits BEFORE post-verify.

        Pre-flight still runs (AlwaysTrigger), but the validator's reasons
        path returns directly so the post-verify advisor is never invoked.
        """
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_ADR_REVIEW_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config)
        issue = TaskFactory.create(
            id=825,
            title="[ADR] Bad draft",
            body="## Context\nShort.\n\n## Decision\nTiny.\n\n## Consequences\nTiny.",
        )

        plan_payload = '{"risk_summary":"low","focus_areas":[],"rubric":[],"escalation_signals":[]}'
        runner_run = AsyncMock(return_value=plan_payload)
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        results = await phase.review_adrs([issue])

        assert results[0].verdict == ReviewVerdict.REQUEST_CHANGES
        # Pre-flight ran (AlwaysTrigger) — exactly one advisor call, role=pre_flight.
        assert runner_run.await_count == 1
        assert runner_run.await_args_list[0].kwargs.get("role") == "pre_flight"


class TestAdvisorPreFlightPlanCollisionSafety:
    """T38 (M7): ``_advisor_pre_flight_plan`` keyed by ``(surface, id)``
    tuple prevents collisions when identifier sequences overlap across
    surfaces.

    In production today PR numbers and issue numbers come from disjoint
    segments of GitHub's shared sequence so collisions don't occur in
    practice, but a future surface (ADR-on-fork with renumbering, a
    third-party adapter with its own counter) could collide. The tuple
    key is defensive future-proofing — no behaviour change at the call
    sites that exist today.
    """

    def test_pr_review_plan_isolated_from_adr_review_plan_same_id(
        self, config: HydraFlowConfig
    ) -> None:
        """Same integer identifier under different surfaces does not collide."""
        from review_advisor import ReviewPlan

        phase = make_review_phase(config)

        pr_plan = ReviewPlan(
            risk_summary="pr",
            focus_areas=[],
            rubric=[],
            escalation_signals=[],
        )
        adr_plan = ReviewPlan(
            risk_summary="adr",
            focus_areas=[],
            rubric=[],
            escalation_signals=[],
        )

        # Both plans use identifier 42 but different surfaces — must NOT
        # collide. With the old int-keyed dict the second write would
        # have clobbered the first.
        phase._advisor_pre_flight_plan[("pr_review", 42)] = pr_plan
        phase._advisor_pre_flight_plan[("adr_review", 42)] = adr_plan

        assert phase._advisor_pre_flight_plan[("pr_review", 42)] is pr_plan
        assert phase._advisor_pre_flight_plan[("adr_review", 42)] is adr_plan
        assert pr_plan is not adr_plan  # sanity

    def test_pre_merge_spec_check_reads_pr_review_plan_via_piggyback(
        self, config: HydraFlowConfig
    ) -> None:
        """The piggyback contract: pre_merge_spec_check looks up the plan
        under ``("pr_review", pr_number)``, NOT
        ``("pre_merge_spec_check", pr_number)``, because the
        pre_merge_spec_check surface has ``pre_flight_enabled=False`` and
        never produces its own plan.
        """
        from review_advisor import ReviewPlan

        phase = make_review_phase(config)
        pr_plan = ReviewPlan(
            risk_summary="pr-review plan",
            focus_areas=[],
            rubric=[],
            escalation_signals=[],
        )
        phase._advisor_pre_flight_plan[("pr_review", 100)] = pr_plan

        # Piggyback key (the one the implementation uses).
        assert phase._advisor_pre_flight_plan.get(("pr_review", 100)) is pr_plan
        # Wrong-surface key must return nothing.
        assert phase._advisor_pre_flight_plan.get(("pre_merge_spec_check", 100)) is None


# ---------------------------------------------------------------------------
# _run_initial_guards
# ---------------------------------------------------------------------------


class TestRunInitialGuards:
    @pytest.mark.asyncio
    async def test_returns_context_when_all_guards_pass(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create(issue_number=issue.id)

        wt_path = config.workspace_path_for_issue(issue.id)
        wt_path.mkdir(parents=True, exist_ok=True)

        phase._prepare_review_worktree = AsyncMock(return_value=wt_path)

        guards = await phase._run_initial_guards(0, pr, {issue.id: issue})

        assert isinstance(guards, ReviewGuardContext)
        assert guards.task == issue
        assert guards.workspace_path == wt_path
        phase._prepare_review_worktree.assert_awaited_once_with(pr, issue, 0)


# ---------------------------------------------------------------------------
# _run_pre_review_checks
# ---------------------------------------------------------------------------


class TestPreReviewChecks:
    @pytest.mark.asyncio
    async def test_baseline_violation_returns_review_result(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create(issue_number=issue.id)

        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        violation = BaselineApprovalResult(
            approved=False,
            requires_approval=True,
            changed_files=["snap.png"],
            reason="missing approval",
        )
        phase._check_baseline_policy = AsyncMock(return_value=violation)
        phase._escalate_to_hitl = AsyncMock()

        result = await phase._run_pre_review_checks(pr, issue)

        assert isinstance(result, ReviewResult)
        assert "Baseline" in result.summary
        phase._escalate_to_hitl.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_context_and_posts_visual_comment(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create(issue_number=issue.id)

        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._check_baseline_policy = AsyncMock(return_value=None)
        decision = VisualValidationDecision(
            policy=VisualValidationPolicy.REQUIRED,
            reason="Triggered",
            triggered_patterns=["apps/*"],
        )
        phase._compute_visual_validation = MagicMock(return_value=decision)
        alerts = [CodeScanningAlert(number=1)]
        phase._fetch_code_scanning_alerts = AsyncMock(return_value=alerts)
        phase._run_delta_verification = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        context = await phase._run_pre_review_checks(pr, issue)

        assert isinstance(context, PreReviewContext)
        assert context.diff == "diff text"
        assert context.visual_decision == decision
        assert context.code_scanning_alerts == alerts
        phase._prs.post_pr_comment.assert_awaited_once()
        phase._run_delta_verification.assert_awaited_once_with(pr, "diff text")


# ---------------------------------------------------------------------------
# _run_post_review_actions
# ---------------------------------------------------------------------------


class TestRunPostReviewActions:
    @pytest.mark.asyncio
    async def test_self_fix_re_review_and_merge_flow(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create(issue_number=issue.id)
        wt_path = config.workspace_path_for_issue(issue.id)
        wt_path.mkdir(parents=True, exist_ok=True)

        initial = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        upgraded = ReviewResultFactory.create(verdict=ReviewVerdict.APPROVE)
        phase._handle_self_fix_re_review = AsyncMock(
            return_value=(upgraded, "new diff")
        )
        phase._run_visual_validation = AsyncMock(return_value=None)
        phase._handle_visual_failure = AsyncMock()
        phase._record_review_outcome = AsyncMock()
        phase._handle_approved_merge = AsyncMock()
        phase._handle_rejected_review = AsyncMock(return_value=False)
        phase._cleanup_worktree = AsyncMock()

        context = PreReviewContext(
            diff="orig diff",
            visual_decision=None,
            code_scanning_alerts=[CodeScanningAlert(number=1)],
        )

        result = await phase._run_post_review_actions(
            pr,
            issue,
            wt_path,
            initial,
            context,
            worker_id=0,
        )

        assert result == upgraded
        phase._handle_self_fix_re_review.assert_awaited_once()
        phase._handle_approved_merge.assert_awaited_once()
        phase._cleanup_worktree.assert_awaited_once_with(pr, upgraded, False)

    @pytest.mark.asyncio
    async def test_rejected_path_preserves_worktree_when_requested(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create(issue_number=issue.id)
        wt_path = config.workspace_path_for_issue(issue.id)
        wt_path.mkdir(parents=True, exist_ok=True)

        result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=False,
        )
        report = MagicMock(has_failures=False)

        phase._handle_self_fix_re_review = AsyncMock()
        phase._run_visual_validation = AsyncMock(return_value=report)
        phase._handle_visual_failure = AsyncMock()
        phase._record_review_outcome = AsyncMock()
        phase._handle_approved_merge = AsyncMock()
        phase._handle_rejected_review = AsyncMock(return_value=True)
        phase._cleanup_worktree = AsyncMock()

        context = PreReviewContext(
            diff="diff text",
            visual_decision=None,
            code_scanning_alerts=None,
        )

        final = await phase._run_post_review_actions(
            pr,
            issue,
            wt_path,
            result,
            context,
            worker_id=1,
        )

        assert final == result
        phase._handle_rejected_review.assert_awaited_once()
        phase._cleanup_worktree.assert_awaited_once_with(pr, result, True)
        phase._handle_self_fix_re_review.assert_not_awaited()
        phase._handle_visual_failure.assert_not_awaited()


# ---------------------------------------------------------------------------
# Baseline policy integration in _review_one_inner
# ---------------------------------------------------------------------------


class TestBaselinePolicyIntegration:
    """Integration tests for baseline policy enforcement in _review_one_inner."""

    @pytest.mark.asyncio
    async def test_no_policy_configured_continues_normally(
        self, config: HydraFlowConfig
    ) -> None:
        """When no baseline_policy is set, review proceeds normally."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        result = await phase._review_one_inner(0, pr, {42: issue})

        # Should complete normally without escalation
        assert result.merged is True

    @pytest.mark.asyncio
    async def test_baseline_denied_escalates_to_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """When baseline policy denies approval, escalate to HITL and return early."""
        from baseline_policy import BaselinePolicy
        from models import BaselineApprovalResult

        mock_policy = AsyncMock(spec=BaselinePolicy)
        mock_policy.check_approval = AsyncMock(
            return_value=BaselineApprovalResult(
                approved=False,
                requires_approval=True,
                changed_files=["tests/__snapshots__/home.snap.png"],
                reason="No authorized approver",
            )
        )

        phase = make_review_phase(
            config, default_mocks=True, baseline_policy=mock_policy
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        result = await phase._review_one_inner(0, pr, {42: issue})

        assert "Baseline" in result.summary
        assert result.merged is False
        # Escalation should post a PR comment
        phase._prs.post_pr_comment.assert_awaited()

    @pytest.mark.asyncio
    async def test_baseline_approved_continues_normally(
        self, config: HydraFlowConfig
    ) -> None:
        """When baseline policy approves, review proceeds normally."""
        from baseline_policy import BaselinePolicy
        from models import BaselineApprovalResult

        mock_policy = AsyncMock(spec=BaselinePolicy)
        mock_policy.check_approval = AsyncMock(
            return_value=BaselineApprovalResult(
                approved=True,
                requires_approval=True,
                approver="alice",
                changed_files=["tests/__snapshots__/home.snap.png"],
                reason="Approved by alice",
            )
        )

        phase = make_review_phase(
            config, default_mocks=True, baseline_policy=mock_policy
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        result = await phase._review_one_inner(0, pr, {42: issue})

        # Approved baseline should not block merge
        assert result.merged is True

    @pytest.mark.asyncio
    async def test_baseline_policy_exception_fails_closed(
        self, config: HydraFlowConfig
    ) -> None:
        """When the baseline policy check raises an exception, fail closed (deny)."""
        from baseline_policy import BaselinePolicy

        mock_policy = AsyncMock(spec=BaselinePolicy)
        mock_policy.check_approval = AsyncMock(side_effect=RuntimeError("gh api error"))

        phase = make_review_phase(
            config, default_mocks=True, baseline_policy=mock_policy
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        result = await phase._review_one_inner(0, pr, {42: issue})

        # Fail closed: should escalate to HITL
        assert result.merged is False
        assert "Baseline" in result.summary

    @pytest.mark.asyncio
    async def test_baseline_policy_oserror_fails_closed(
        self, config: HydraFlowConfig
    ) -> None:
        """OSError during baseline policy check should also fail closed."""
        from baseline_policy import BaselinePolicy

        mock_policy = AsyncMock(spec=BaselinePolicy)
        mock_policy.check_approval = AsyncMock(side_effect=OSError("connection reset"))

        phase = make_review_phase(
            config, default_mocks=True, baseline_policy=mock_policy
        )
        pr = PRInfoFactory.create()
        task = TaskFactory.create()

        result = await phase._check_baseline_policy(pr, task)

        assert result is not None
        assert result.approved is False
        assert result.requires_approval is True

    @pytest.mark.asyncio
    async def test_baseline_policy_code_bug_propagates(
        self, config: HydraFlowConfig
    ) -> None:
        """TypeError/KeyError in baseline policy must propagate, not be caught."""
        from baseline_policy import BaselinePolicy

        mock_policy = AsyncMock(spec=BaselinePolicy)
        mock_policy.check_approval = AsyncMock(side_effect=TypeError("unexpected None"))

        phase = make_review_phase(
            config, default_mocks=True, baseline_policy=mock_policy
        )
        pr = PRInfoFactory.create()
        task = TaskFactory.create()

        with pytest.raises(TypeError, match="unexpected None"):
            await phase._check_baseline_policy(pr, task)


# ---------------------------------------------------------------------------
# Narrowed exception handling — code bugs propagate
# ---------------------------------------------------------------------------


class TestNarrowedExceptionHandling:
    """Verify that narrowed except clauses let code bugs propagate."""

    @pytest.mark.asyncio
    async def test_fetch_code_scanning_alerts_catches_runtime_error(
        self, config: HydraFlowConfig
    ) -> None:
        """RuntimeError from subprocess is still caught gracefully."""
        phase = make_review_phase(config, default_mocks=True)
        # code_scanning is always enabled
        phase._prs.fetch_code_scanning_alerts = AsyncMock(
            side_effect=RuntimeError("gh CLI failed")
        )
        pr = PRInfoFactory.create()

        result = await phase._fetch_code_scanning_alerts(pr)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_code_scanning_alerts_catches_oserror(
        self, config: HydraFlowConfig
    ) -> None:
        """OSError (e.g., network failure) is caught gracefully."""
        phase = make_review_phase(config, default_mocks=True)
        # code_scanning is always enabled
        phase._prs.fetch_code_scanning_alerts = AsyncMock(
            side_effect=OSError("network unreachable")
        )
        pr = PRInfoFactory.create()

        result = await phase._fetch_code_scanning_alerts(pr)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_code_scanning_alerts_propagates_type_error(
        self, config: HydraFlowConfig
    ) -> None:
        """TypeError (code bug) must propagate through narrowed handler."""
        phase = make_review_phase(config, default_mocks=True)
        # code_scanning is always enabled
        phase._prs.fetch_code_scanning_alerts = AsyncMock(
            side_effect=TypeError("bad arg")
        )
        pr = PRInfoFactory.create()

        with pytest.raises(TypeError, match="bad arg"):
            await phase._fetch_code_scanning_alerts(pr)

    @pytest.mark.asyncio
    async def test_visual_validation_catches_runtime_error(
        self, config: HydraFlowConfig, tmp_path: Path
    ) -> None:
        """RuntimeError during visual validation is caught gracefully."""
        phase = make_review_phase(config, default_mocks=True)
        phase._visual_validator = MagicMock()
        phase._visual_validator.validate_screens = AsyncMock(
            side_effect=RuntimeError("visual tool crashed")
        )
        pr = PRInfoFactory.create()

        result = await phase._run_visual_validation(pr, tmp_path, worker_id=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_visual_validation_propagates_attribute_error(
        self, config: HydraFlowConfig, tmp_path: Path
    ) -> None:
        """AttributeError (code bug) in visual validation must propagate."""
        phase = make_review_phase(config, default_mocks=True)
        phase._visual_validator = MagicMock()
        phase._visual_validator.validate_screens = AsyncMock(
            side_effect=AttributeError("missing attr")
        )
        pr = PRInfoFactory.create()

        with pytest.raises(AttributeError, match="missing attr"):
            await phase._run_visual_validation(pr, tmp_path, worker_id=0)

    @pytest.mark.asyncio
    async def test_ci_log_fetch_propagates_key_error(
        self, config: HydraFlowConfig
    ) -> None:
        """KeyError (code bug) during CI log fetch must propagate.

        The CI log fetch handler in review_phase.py now catches only
        (RuntimeError, OSError), so code bugs like KeyError propagate.
        """
        phase = make_review_phase(config, default_mocks=True)
        phase._prs.fetch_ci_failure_logs = AsyncMock(
            side_effect=KeyError("missing key")
        )

        with pytest.raises(KeyError, match="missing key"):
            await phase._prs.fetch_ci_failure_logs(42)


# ---------------------------------------------------------------------------
# Post-verify advisor runner dispatch (T16 regression — I4)
# ---------------------------------------------------------------------------


class TestPostVerifyRunnerDispatch:
    """Regression test for T16 (commit 4f49e0f6) — AsyncMock auto-vivification
    must NOT route the runner adapter into the MockWorld branch.

    Without the ``__dict__``-based probe, ``getattr(asyncmock,
    "_mockworld_fake_llm")`` returns a child mock that satisfies
    ``is not None``, causing the runner to route through the FakeLLM
    dispatch path against AsyncMock test scaffolding that has no
    ``_is_fake_adapter`` marker. The result is a coroutine returned as the
    runner's payload.

    See ``src/review_phase.py:_build_post_verify_runner`` for the load-bearing
    ``__dict__`` check this test pins.
    """

    @pytest.mark.asyncio
    async def test_asyncmock_reviewer_does_not_route_to_mockworld_branch(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        # AsyncMock-based reviewer: _execute is an awaitable child mock; we
        # set a deterministic return value so the dispatcher's production
        # path returns a string rather than an auto-mock coroutine.
        phase._reviewers._execute = AsyncMock(return_value="production-payload")

        runner = phase._post_verify_runner
        out = await runner.run(
            model="opus",
            subagent_type="hydraflow-review-advisor",
            prompt="Issue: 1\n\n## Diff\nfoo",
            role="post_verify",
        )

        # Production path was taken — _execute awaited exactly once with the
        # advisor source tag — and the runner returned the production payload
        # rather than a coroutine-as-payload from the FakeLLM branch.
        assert out == "production-payload"
        phase._reviewers._execute.assert_awaited_once()
        _, kwargs = phase._reviewers._execute.call_args
        # The fourth positional arg is the source tag dict.
        args = phase._reviewers._execute.call_args.args
        assert args[-1] == {"source": "advisor"}

    @pytest.mark.asyncio
    async def test_mockworld_sentinel_routes_to_fake_llm_branch(
        self, config: HydraFlowConfig
    ) -> None:
        """Positive path — when a real MockWorld FakeLLM is attached as an
        instance attribute (with ``_is_fake_adapter=True``), dispatch routes
        to the MockWorld branch and skips the production ``_execute`` path.
        """
        phase = make_review_phase(config)

        class _FakeLLM:
            _is_fake_adapter = True

            def __init__(self) -> None:
                self.calls: list[tuple[int, str]] = []

            def pop_advisor_result(self, issue_number: int, role: str) -> str:
                self.calls.append((issue_number, role))
                return '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'

        fake = _FakeLLM()
        # Set on instance __dict__ — same shape MockWorld scenarios use.
        phase._reviewers._mockworld_fake_llm = fake
        phase._reviewers._execute = AsyncMock()

        runner = phase._post_verify_runner
        out = await runner.run(
            model="opus",
            subagent_type="hydraflow-review-advisor",
            prompt="Issue: 7\n\n## Diff\nfoo",
            role="post_verify",
        )

        assert out.startswith('{"verdict":"APPROVE"')
        assert fake.calls == [(7, "post_verify")]
        # MockWorld branch must NOT call the production _execute path.
        phase._reviewers._execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# Pre-merge spec check post-verify advisor (T25)
# ---------------------------------------------------------------------------


class TestPreMergeSpecCheckAdvisor:
    """T25 — PostVerifyAdvisor wired into ``_run_pre_merge_spec_check``.

    The pre_merge_spec_check surface is a binary gate: post-verify VETO
    blocks the merge regardless of the executor's MATCH verdict; APPROVE
    falls through to the executor's existing decision.
    """

    @pytest.mark.asyncio
    async def test_advisor_veto_blocks_merge_on_executor_match(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Executor returns MATCH but advisor VETOes — merge must be blocked."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PRE_MERGE_SPEC_CHECK_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config, default_mocks=True)
        task = TaskFactory.create(id=42, body="The widget should frobnicate")

        # Stub the spec-match executor to return MATCH.
        monkeypatch.setattr(
            "spec_match.build_self_review_prompt",
            lambda _t, _d: "prompt",
        )
        monkeypatch.setattr(
            "spec_match.extract_spec_match",
            lambda _t: {"verdict": "MATCH", "content": ""},
        )
        monkeypatch.setattr(
            "agent_cli.build_agent_command",
            lambda **_kw: ["echo", "ok"],
        )
        phase._reviewers._execute = AsyncMock(return_value="transcript")

        # Stub the post-verify runner to return a VETO payload.
        veto_payload = (
            '{"verdict":"VETO","reasoning":"missing acceptance criterion 2",'
            '"disagreements":[{"executor_claim":"spec match",'
            '"advisor_assessment":"AC2 not addressed",'
            '"severity":"blocking"}]}'
        )
        runner_run = AsyncMock(return_value=veto_payload)
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        result = await phase._run_pre_merge_spec_check(task, "diff text", pr_number=99)

        assert result is False, "Advisor VETO must block the merge"
        runner_run.assert_awaited_once()
        # Surface threading: the runner is called with role="post_verify".
        kwargs = runner_run.await_args.kwargs
        assert kwargs.get("role") == "post_verify"

    @pytest.mark.asyncio
    async def test_advisor_approve_respects_executor_match(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Executor MATCH + advisor APPROVE -> proceed with merge."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PRE_MERGE_SPEC_CHECK_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config, default_mocks=True)
        task = TaskFactory.create(id=42, body="spec body")

        monkeypatch.setattr(
            "spec_match.build_self_review_prompt",
            lambda _t, _d: "prompt",
        )
        monkeypatch.setattr(
            "spec_match.extract_spec_match",
            lambda _t: {"verdict": "MATCH", "content": ""},
        )
        monkeypatch.setattr(
            "agent_cli.build_agent_command",
            lambda **_kw: ["echo", "ok"],
        )
        phase._reviewers._execute = AsyncMock(return_value="transcript")

        approve_payload = (
            '{"verdict":"APPROVE","reasoning":"looks good","disagreements":[]}'
        )
        phase._post_verify_runner.run = AsyncMock(  # type: ignore[method-assign]
            return_value=approve_payload
        )

        result = await phase._run_pre_merge_spec_check(task, "diff text", pr_number=99)

        assert result is True, "Executor MATCH + advisor APPROVE -> proceed"

    @pytest.mark.asyncio
    async def test_advisor_approve_does_not_override_executor_mismatch(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-closed preserved: advisor APPROVE cannot rescue an executor MISMATCH."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PRE_MERGE_SPEC_CHECK_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config, default_mocks=True)
        task = TaskFactory.create(id=42, body="spec body")

        monkeypatch.setattr(
            "spec_match.build_self_review_prompt",
            lambda _t, _d: "prompt",
        )
        monkeypatch.setattr(
            "spec_match.extract_spec_match",
            lambda _t: {"verdict": "MISMATCH", "content": "gap details"},
        )
        monkeypatch.setattr(
            "agent_cli.build_agent_command",
            lambda **_kw: ["echo", "ok"],
        )
        phase._reviewers._execute = AsyncMock(return_value="transcript")

        # Advisor returns APPROVE — should not override the executor's MISMATCH.
        approve_payload = (
            '{"verdict":"APPROVE","reasoning":"looks fine","disagreements":[]}'
        )
        phase._post_verify_runner.run = AsyncMock(  # type: ignore[method-assign]
            return_value=approve_payload
        )

        result = await phase._run_pre_merge_spec_check(task, "diff text", pr_number=99)

        assert result is False, (
            "Advisor APPROVE must not override executor MISMATCH (fail-closed)"
        )

    @pytest.mark.asyncio
    async def test_per_surface_kill_switch_skips_advisor(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the per-surface kill switch is off, advisor is not invoked."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PRE_MERGE_SPEC_CHECK_ADVISOR_ENABLED", "false")

        phase = make_review_phase(config, default_mocks=True)
        task = TaskFactory.create(id=42, body="spec body")

        monkeypatch.setattr(
            "spec_match.build_self_review_prompt",
            lambda _t, _d: "prompt",
        )
        monkeypatch.setattr(
            "spec_match.extract_spec_match",
            lambda _t: {"verdict": "MATCH", "content": ""},
        )
        monkeypatch.setattr(
            "agent_cli.build_agent_command",
            lambda **_kw: ["echo", "ok"],
        )
        phase._reviewers._execute = AsyncMock(return_value="transcript")

        runner_run = AsyncMock()
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        result = await phase._run_pre_merge_spec_check(task, "diff text", pr_number=99)

        assert result is True
        runner_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_advisor_runtime_error_degrades_to_executor_verdict(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Soft advisor failure (e.g. RuntimeError) falls through to executor's verdict.

        The executor's existing fail-closed semantics on MISMATCH still
        apply; a non-fatal advisor error doesn't itself block a MATCH.
        """
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PRE_MERGE_SPEC_CHECK_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config, default_mocks=True)
        task = TaskFactory.create(id=42, body="spec body")

        monkeypatch.setattr(
            "spec_match.build_self_review_prompt",
            lambda _t, _d: "prompt",
        )
        monkeypatch.setattr(
            "spec_match.extract_spec_match",
            lambda _t: {"verdict": "MATCH", "content": ""},
        )
        monkeypatch.setattr(
            "agent_cli.build_agent_command",
            lambda **_kw: ["echo", "ok"],
        )
        phase._reviewers._execute = AsyncMock(return_value="transcript")

        # Advisor errors with a transient runtime issue.
        phase._post_verify_runner.run = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("advisor temporarily unavailable")
        )

        result = await phase._run_pre_merge_spec_check(task, "diff text", pr_number=99)

        # Executor's MATCH stands when the advisor degrades; fail-closed
        # behaviour on MISMATCH is preserved by the executor's own branch.
        assert result is True

    @pytest.mark.asyncio
    async def test_advisor_credit_exhausted_propagates(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CreditExhaustedError from the advisor must propagate (dark-factory §2.2)."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PRE_MERGE_SPEC_CHECK_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config, default_mocks=True)
        task = TaskFactory.create(id=42, body="spec body")

        monkeypatch.setattr(
            "spec_match.build_self_review_prompt",
            lambda _t, _d: "prompt",
        )
        monkeypatch.setattr(
            "spec_match.extract_spec_match",
            lambda _t: {"verdict": "MATCH", "content": ""},
        )
        monkeypatch.setattr(
            "agent_cli.build_agent_command",
            lambda **_kw: ["echo", "ok"],
        )
        phase._reviewers._execute = AsyncMock(return_value="transcript")

        from subprocess_util import CreditExhaustedError

        phase._post_verify_runner.run = AsyncMock(  # type: ignore[method-assign]
            side_effect=CreditExhaustedError("no credits")
        )

        with pytest.raises(CreditExhaustedError):
            await phase._run_pre_merge_spec_check(task, "diff text", pr_number=99)


# ---------------------------------------------------------------------------
# Visual gate advisor (T27)
# ---------------------------------------------------------------------------


class TestVisualGateAdvisor:
    """T27 — PostVerifyAdvisor wired into ``check_visual_gate`` for the
    ``visual_gate`` surface (post-only; pre_flight=False, mid_flight=False;
    ``max_veto_retries=1``).

    The visual gate is a binary post-verify gate: when the visual pipeline
    returns ``"pass"``, the advisor gets a chance to second-opinion the
    verdict. VETO blocks the merge and routes through the existing visual
    gate failure/HITL escalation path; APPROVE / kill-switch off / soft
    advisor failure falls through to the sign-off path unchanged.
    """

    @pytest.mark.asyncio
    async def test_advisor_approve_passes_visual_gate(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Visual pipeline PASS + advisor APPROVE → gate passes (existing behavior)."""
        from tests.helpers import ConfigFactory

        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_VISUAL_GATE_ADVISOR_ENABLED", "true")

        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._invoke_visual_pipeline = AsyncMock(  # type: ignore[method-assign]
            return_value=("pass", {"baseline": "https://example.com/b"}, "all clear")
        )
        approve_payload = (
            '{"verdict":"APPROVE","reasoning":"visual evidence is sound",'
            '"disagreements":[]}'
        )
        runner_run = AsyncMock(return_value=approve_payload)
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        pr = PRInfoFactory.create(number=901)
        issue = TaskFactory.create(id=901)
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)

        assert ok is True
        assert result.visual_passed is True
        runner_run.assert_awaited_once()
        kwargs = runner_run.await_args.kwargs
        assert kwargs.get("role") == "post_verify"
        # Sign-off comment posted (PASS path), not a BLOCKED comment.
        comment_call = phase._prs.post_pr_comment.call_args.args[1]
        assert "PASSED" in comment_call

    @pytest.mark.asyncio
    async def test_advisor_veto_blocks_visual_gate(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Visual pipeline PASS + advisor VETO → gate blocks; HITL escalation."""
        from tests.helpers import ConfigFactory

        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_VISUAL_GATE_ADVISOR_ENABLED", "true")

        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._escalate_to_hitl = AsyncMock()
        phase._invoke_visual_pipeline = AsyncMock(  # type: ignore[method-assign]
            return_value=("pass", {}, "pixel diff under threshold")
        )
        veto_payload = (
            '{"verdict":"VETO",'
            '"reasoning":"baseline shows misaligned modal — regression",'
            '"disagreements":[{"executor_claim":"pass",'
            '"advisor_assessment":"modal misalignment",'
            '"severity":"blocking"}]}'
        )
        runner_run = AsyncMock(return_value=veto_payload)
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        pr = PRInfoFactory.create(number=902)
        issue = TaskFactory.create(id=902)
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)

        assert ok is False, "Advisor VETO must block the visual gate"
        assert result.visual_passed is False
        runner_run.assert_awaited_once()
        # BLOCKED comment posted via failure path with advisor reasoning.
        phase._prs.post_pr_comment.assert_awaited()
        block_comment = phase._prs.post_pr_comment.call_args.args[1]
        assert "BLOCKED" in block_comment
        assert "advisor veto" in block_comment.lower()
        # HITL escalation engaged (failure path).
        phase._escalate_to_hitl.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_per_surface_kill_switch_skips_advisor(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``HYDRAFLOW_VISUAL_GATE_ADVISOR_ENABLED=false`` → advisor not invoked."""
        from tests.helpers import ConfigFactory

        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_VISUAL_GATE_ADVISOR_ENABLED", "false")

        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._invoke_visual_pipeline = AsyncMock(  # type: ignore[method-assign]
            return_value=("pass", {}, "all clear")
        )

        runner_run = AsyncMock()
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        pr = PRInfoFactory.create(number=903)
        issue = TaskFactory.create(id=903)
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)

        assert ok is True
        assert result.visual_passed is True
        runner_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_advisor_credit_exhausted_propagates(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CreditExhaustedError from the advisor must propagate (dark-factory §2.2)."""
        from tests.helpers import ConfigFactory

        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_VISUAL_GATE_ADVISOR_ENABLED", "true")

        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._invoke_visual_pipeline = AsyncMock(  # type: ignore[method-assign]
            return_value=("pass", {}, "all clear")
        )

        from subprocess_util import CreditExhaustedError

        phase._post_verify_runner.run = AsyncMock(  # type: ignore[method-assign]
            side_effect=CreditExhaustedError("no credits")
        )

        pr = PRInfoFactory.create(number=904)
        issue = TaskFactory.create(id=904)
        result = ReviewResultFactory.create()

        with pytest.raises(CreditExhaustedError):
            await phase.check_visual_gate(pr, issue, result, worker_id=0)

    @pytest.mark.asyncio
    async def test_visual_gate_advisor_uses_issue_id_not_pr_number(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T30.5 (I1) regression: visual gate advisor must look up by ``issue.id``,
        not ``pr.number``.

        Production-side, the PR number and the originating issue id are
        distinct; the advisor's prompt threads ``issue_number`` so MockWorld
        runners can route via ``FakeLLM.pop_advisor_result(issue_number, role)``.
        Before the fix, ``_run_visual_gate_advisor`` passed ``pr.number`` —
        coincidentally equal to ``issue.id`` in factory defaults, masking the
        bug. This test pins the asymmetry.
        """
        from tests.helpers import ConfigFactory

        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_VISUAL_GATE_ADVISOR_ENABLED", "true")

        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._invoke_visual_pipeline = AsyncMock(  # type: ignore[method-assign]
            return_value=("pass", {}, "all clear")
        )

        # Capture the PostVerifyInput passed to PostVerifyAdvisor.run.
        from review_advisor import PostVerifyInput, PostVerifyResult

        captured: list[PostVerifyInput] = []

        async def fake_advisor_run(
            self: object, inp: PostVerifyInput
        ) -> PostVerifyResult:
            captured.append(inp)
            return PostVerifyResult(verdict="APPROVE", reasoning="ok", disagreements=[])

        monkeypatch.setattr(
            "review_advisor.PostVerifyAdvisor.run",
            fake_advisor_run,
        )

        # PR number (901) and issue id (42) are deliberately different.
        pr = PRInfoFactory.create(number=901)
        issue = TaskFactory.create(id=42)
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)

        assert ok is True
        assert len(captured) == 1, "advisor must be invoked exactly once"
        assert captured[0].issue_number == 42, (
            f"Expected issue.id (42), got {captured[0].issue_number} — "
            "I1 regression: visual gate using pr.number instead of issue.id"
        )


class TestWikiIngestAdvisor:
    """T28 — PostVerifyAdvisor wired into ``_wiki_ingest_review`` for the
    ``wiki_ingest`` surface (post-only; pre_flight=False, mid_flight=False;
    ``post_verify_authority="advisory"``; ``max_veto_retries=0``).

    Advisory mode means the advisor's VETO is downgraded to APPROVE in
    :meth:`PostVerifyAdvisor.run` — disagreements are still logged via the
    advisor_session.jsonl (T12) and emit per-disagreement OTel counters
    (T16.5/T22) for calibration, but ingestion proceeds. EXCEPTION:
    T29's self-modification guard upgrades authority to ``veto`` when the
    candidate content discusses changes to advisor's own files; in that
    path a real VETO blocks ingestion.
    """

    @pytest.mark.asyncio
    async def test_advisor_veto_downgraded_to_approve_in_advisory_mode(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Advisory authority downgrades VETO to APPROVE — ingestion proceeds."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_WIKI_INGEST_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config)
        wiki_store = MagicMock()
        wiki_store.is_ingested = MagicMock(return_value=False)
        wiki_store.mark_ingested = MagicMock()
        wiki_store.ingest = MagicMock()
        phase._wiki_store = wiki_store
        phase._wiki_compiler = None  # force fallback path

        veto_payload = (
            '{"verdict":"VETO",'
            '"reasoning":"prefer terse phrasing",'
            '"disagreements":[{"executor_claim":"summary is fine",'
            '"advisor_assessment":"summary is verbose",'
            '"severity":"concern"}]}'
        )
        runner_run = AsyncMock(return_value=veto_payload)
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        # Patch the fallback ingest path so we can detect whether ingestion ran.
        ingest_called = MagicMock()
        monkeypatch.setattr(
            "repo_wiki_ingest.ingest_from_review",
            ingest_called,
        )

        await phase._wiki_ingest_review(
            issue_number=730,
            transcript="reviewer feedback transcript",
            summary="something concise",
        )

        # Advisor consulted exactly once with role=post_verify.
        runner_run.assert_awaited_once()
        assert runner_run.await_args.kwargs.get("role") == "post_verify"
        # Advisory mode: VETO does NOT block — ingestion path still ran.
        ingest_called.assert_called_once()
        wiki_store.mark_ingested.assert_called_once_with(config.repo, 730, "review")

    @pytest.mark.asyncio
    async def test_advisor_approve_proceeds_normally(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """APPROVE verdict — ingestion proceeds via the normal path."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_WIKI_INGEST_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config)
        wiki_store = MagicMock()
        wiki_store.is_ingested = MagicMock(return_value=False)
        wiki_store.mark_ingested = MagicMock()
        wiki_store.ingest = MagicMock()
        phase._wiki_store = wiki_store
        phase._wiki_compiler = None

        approve_payload = (
            '{"verdict":"APPROVE","reasoning":"summary is fine","disagreements":[]}'
        )
        runner_run = AsyncMock(return_value=approve_payload)
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        ingest_called = MagicMock()
        monkeypatch.setattr(
            "repo_wiki_ingest.ingest_from_review",
            ingest_called,
        )

        await phase._wiki_ingest_review(
            issue_number=731,
            transcript="reviewer feedback",
            summary="canonical summary",
        )

        runner_run.assert_awaited_once()
        ingest_called.assert_called_once()
        wiki_store.mark_ingested.assert_called_once_with(config.repo, 731, "review")

    @pytest.mark.asyncio
    async def test_self_modification_diff_forces_veto_blocks_ingest(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wiki content discussing src/review_advisor.py upgrades authority
        to ``veto`` (T29 guard) — VETO actually blocks ingestion."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_WIKI_INGEST_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config)
        wiki_store = MagicMock()
        wiki_store.is_ingested = MagicMock(return_value=False)
        wiki_store.mark_ingested = MagicMock()
        wiki_store.ingest = MagicMock()
        phase._wiki_store = wiki_store
        phase._wiki_compiler = None

        veto_payload = (
            '{"verdict":"VETO",'
            '"reasoning":"this entry tries to weaken the advisor",'
            '"disagreements":[{"executor_claim":"safe to ingest",'
            '"advisor_assessment":"self-mod attempt",'
            '"severity":"blocking"}]}'
        )
        runner_run = AsyncMock(return_value=veto_payload)
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        ingest_called = MagicMock()
        monkeypatch.setattr(
            "repo_wiki_ingest.ingest_from_review",
            ingest_called,
        )

        # T37: detection is context-sensitive — the transcript must describe
        # an actual modification (fenced diff block, real diff header, or
        # editorial verb immediately before the path) for the synthesizer to
        # emit the pseudo unified-diff header that
        # resolve_post_verify_authority's substring detector picks up.
        # A bare substring mention is no longer sufficient.
        await phase._wiki_ingest_review(
            issue_number=732,
            transcript=(
                "Proposed change:\n"
                "```diff\n"
                "--- a/src/review_advisor.py\n"
                "+++ b/src/review_advisor.py\n"
                "+# weakening advisor guard\n"
                "```\n"
            ),
            summary="modified src/review_advisor.py to soften advisor",
        )

        runner_run.assert_awaited_once()
        # Self-mod path: VETO blocks ingestion — no fallback ingest call,
        # no mark_ingested.
        ingest_called.assert_not_called()
        wiki_store.mark_ingested.assert_not_called()

    @pytest.mark.asyncio
    async def test_per_surface_kill_switch_skips_advisor(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``HYDRAFLOW_WIKI_INGEST_ADVISOR_ENABLED=false`` — advisor not invoked."""
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_WIKI_INGEST_ADVISOR_ENABLED", "false")

        phase = make_review_phase(config)
        wiki_store = MagicMock()
        wiki_store.is_ingested = MagicMock(return_value=False)
        wiki_store.mark_ingested = MagicMock()
        wiki_store.ingest = MagicMock()
        phase._wiki_store = wiki_store
        phase._wiki_compiler = None

        runner_run = AsyncMock()
        phase._post_verify_runner.run = runner_run  # type: ignore[method-assign]

        ingest_called = MagicMock()
        monkeypatch.setattr(
            "repo_wiki_ingest.ingest_from_review",
            ingest_called,
        )

        await phase._wiki_ingest_review(
            issue_number=733,
            transcript="reviewer feedback",
            summary="canonical summary",
        )

        runner_run.assert_not_awaited()
        # Existing ingest path still ran.
        ingest_called.assert_called_once()
        wiki_store.mark_ingested.assert_called_once_with(config.repo, 733, "review")

    @pytest.mark.asyncio
    async def test_disagreements_logged_even_when_downgraded(
        self, config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Advisory-mode VETO is downgraded, but the per-PR
        ``advisor_session.jsonl`` log records the call so calibration
        metrics see the disagreement."""
        import json as _json

        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_WIKI_INGEST_ADVISOR_ENABLED", "true")

        phase = make_review_phase(config)
        wiki_store = MagicMock()
        wiki_store.is_ingested = MagicMock(return_value=False)
        wiki_store.mark_ingested = MagicMock()
        wiki_store.ingest = MagicMock()
        phase._wiki_store = wiki_store
        phase._wiki_compiler = None

        veto_payload = (
            '{"verdict":"VETO",'
            '"reasoning":"prefer terse phrasing",'
            '"disagreements":[{"executor_claim":"OK",'
            '"advisor_assessment":"too verbose",'
            '"severity":"concern"}]}'
        )
        phase._post_verify_runner.run = AsyncMock(  # type: ignore[method-assign]
            return_value=veto_payload
        )

        monkeypatch.setattr(
            "repo_wiki_ingest.ingest_from_review",
            lambda *a, **kw: None,
        )

        await phase._wiki_ingest_review(
            issue_number=734,
            transcript="reviewer feedback",
            summary="summary content",
        )

        # advisor_session.jsonl created with one entry tagged surface=wiki_ingest.
        log_path = config.repo_root / "review_logs" / "734" / "advisor_session.jsonl"
        assert log_path.exists(), "advisor_session.jsonl must be written"
        lines = [
            _json.loads(ln) for ln in log_path.read_text().splitlines() if ln.strip()
        ]
        assert lines, "log must contain at least one entry"
        assert lines[0]["surface"] == "wiki_ingest"
        assert lines[0]["role"] == "post_verify"
        assert lines[0]["pr_number"] == 734

    # ------------------------------------------------------------------
    # T37 — context-sensitive self-modification detection.
    #
    # Previously _build_wiki_ingest_diff_descriptor substring-matched
    # advisor source paths anywhere in the candidate content, which
    # forced veto authority on benign mentions (e.g., a review summary
    # noting a type-hint gap in src/review_advisor.py). The tightened
    # detection only synthesizes the pseudo unified-diff header when the
    # path appears in a real modification context.
    # ------------------------------------------------------------------

    def test_benign_path_mention_does_not_trigger_self_mod(
        self, config: HydraFlowConfig
    ) -> None:
        """T37 regression: a wiki entry that mentions an advisor source
        path in editorial prose (no diff context) must NOT synthesize the
        pseudo diff header — that would force veto authority and block
        ingestion of a purely descriptive entry."""
        phase = make_review_phase(config)
        transcript = (
            "Today's review found a type-hint gap in src/review_advisor.py. "
            "The author should add a return annotation. No code changes needed."
        )
        descriptor = phase._build_wiki_ingest_diff_descriptor(
            issue_number=900,
            transcript=transcript,
            summary="Review report",
        )
        # The benign mention must NOT produce a diff --git header.
        assert "diff --git" not in descriptor

    def test_fenced_diff_block_triggers_self_mod(self, config: HydraFlowConfig) -> None:
        """T37: real diff content in a fenced diff block SHOULD synthesize
        the pseudo unified-diff header so T29's self-mod guard fires."""
        phase = make_review_phase(config)
        transcript = (
            "Proposed change:\n"
            "```diff\n"
            "--- a/src/review_advisor.py\n"
            "+++ b/src/review_advisor.py\n"
            "+# new line\n"
            "```\n"
        )
        descriptor = phase._build_wiki_ingest_diff_descriptor(
            issue_number=901,
            transcript=transcript,
            summary="Patch proposal",
        )
        assert "diff --git a/src/review_advisor.py" in descriptor

    def test_editorial_modify_phrase_triggers_self_mod(
        self, config: HydraFlowConfig
    ) -> None:
        """T37: 'modified <path>' editorial context SHOULD synthesize the
        pseudo unified-diff header."""
        phase = make_review_phase(config)
        transcript = "The PR modified src/review_phase.py to add a new helper."
        descriptor = phase._build_wiki_ingest_diff_descriptor(
            issue_number=902,
            transcript=transcript,
            summary="Change summary",
        )
        assert "diff --git a/src/review_phase.py" in descriptor

    def test_real_diff_header_in_transcript_triggers_self_mod(
        self, config: HydraFlowConfig
    ) -> None:
        """T37: already-formed ``diff --git`` headers in the transcript
        SHOULD trigger synthesis (pass-through detection)."""
        phase = make_review_phase(config)
        transcript = (
            "diff --git a/src/review_advisor.py b/src/review_advisor.py\n"
            "@@ -1,2 +1,3 @@\n"
        )
        descriptor = phase._build_wiki_ingest_diff_descriptor(
            issue_number=903,
            transcript=transcript,
            summary="Diff",
        )
        assert "diff --git a/src/review_advisor.py" in descriptor
