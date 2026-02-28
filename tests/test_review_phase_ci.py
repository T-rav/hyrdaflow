"""Tests for review_phase.py — CI wait/fix loop."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from models import (
    ReviewResult,
    ReviewVerdict,
)
from tests.conftest import (
    PRInfoFactory,
    ReviewResultFactory,
    TaskFactory,
)
from tests.helpers import ConfigFactory, make_review_phase

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
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.wait_for_ci = AsyncMock(return_value=(True, "All 3 checks passed"))

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        assert results[0].ci_passed is True
        phase._prs.merge_pr.assert_awaited_once_with(101)

    @pytest.mark.asyncio
    async def test_ci_fails_all_attempts_does_not_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """When CI fails after all fix attempts, PR should not be merged."""
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        assert results[0].ci_passed is False
        phase._prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ci_wait_skipped_when_max_attempts_zero(
        self, config: HydraFlowConfig
    ) -> None:
        """When max_ci_fix_attempts=0, CI wait is skipped entirely."""
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=0,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.wait_for_ci = AsyncMock(return_value=(True, "passed"))

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        # wait_for_ci should NOT have been called
        phase._prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ci_not_checked_for_non_approve_verdicts(
        self, config: HydraFlowConfig
    ) -> None:
        """CI wait only triggers for APPROVE — REQUEST_CHANGES skips it."""
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                verdict=ReviewVerdict.REQUEST_CHANGES
            )
        )
        phase._prs.wait_for_ci = AsyncMock(return_value=(True, "passed"))

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is False
        phase._prs.wait_for_ci.assert_not_awaited()
        phase._prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fix_loop_retries_after_agent_makes_changes(
        self, config: HydraFlowConfig
    ) -> None:
        """When fix agent makes changes, loop should retry CI."""
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
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

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = fake_wait_for_ci

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
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=3,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=False,  # No changes made
        )

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))

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
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))

        await phase.review_prs([pr], [issue])

        # Should have posted a CI failure comment
        comment_calls = [c.args for c in phase._prs.post_pr_comment.call_args_list]
        ci_comments = [c for c in comment_calls if "CI failed" in c[1]]
        assert len(ci_comments) == 1
        assert "Failed checks: ci" in ci_comments[0][1]

        # Should swap label to hydraflow-hitl on both issue and PR
        phase._prs.transition.assert_any_call(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_ci_failure_sets_hitl_cause(self, config: HydraFlowConfig) -> None:
        """CI failure escalation should record cause with attempt count in state."""
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))

        await phase.review_prs([pr], [issue])

        cause = phase._state.get_hitl_cause(42)
        assert cause is not None
        assert cause.startswith("CI failed after 1 fix attempt(s): ")

    @pytest.mark.asyncio
    async def test_ci_failure_escalation_records_hitl_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """CI failure escalation should record review_label as HITL origin."""
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))

        await phase.review_prs([pr], [issue])

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"


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
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create(id=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                pr_number=101, issue_number=42, verdict=ReviewVerdict.APPROVE
            )
        )
        # fix_ci raises an exception
        phase._reviewers.fix_ci = AsyncMock(side_effect=RuntimeError("agent crashed"))
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: tests"))

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
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create(id=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                pr_number=101, issue_number=42, verdict=ReviewVerdict.APPROVE
            )
        )
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Stopped"))

        # Set stop_event before running
        phase._stop_event.set()

        results = await phase.review_prs([pr], [issue])

        assert len(results) == 1
        # PR should NOT have been merged due to CI failure
        assert results[0].merged is False


# ---------------------------------------------------------------------------
# wait_and_fix_ci — CI log injection
# ---------------------------------------------------------------------------


class TestWaitAndFixCIWithLogs:
    """Tests for CI log injection in wait_and_fix_ci."""

    @pytest.mark.asyncio
    async def test_fetches_ci_logs_when_enabled(self, tmp_path: Path) -> None:
        """When inject_runtime_logs is True, fetch_ci_failure_logs is called."""
        config = ConfigFactory.create(
            inject_runtime_logs=True,
            max_ci_fix_attempts=1,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config, default_mocks=True)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        # First call: wait_for_ci fails; second: CI fix; third: wait_for_ci passes
        phase._prs.wait_for_ci = AsyncMock(
            side_effect=[
                (False, "Failed checks: Build"),
                (True, "All 1 checks passed"),
            ]
        )
        phase._prs.fetch_ci_failure_logs = AsyncMock(
            return_value="Error in test.py line 10"
        )
        fix_result = ReviewResultFactory.create(fixes_made=True)
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)

        wt = tmp_path / "wt" / "issue-42"
        passed = await phase.wait_and_fix_ci(pr, issue, wt, result, 0)

        assert passed is True
        phase._prs.fetch_ci_failure_logs.assert_awaited_once_with(pr.number)
        # Verify ci_logs was passed through to fix_ci
        call_kwargs = phase._reviewers.fix_ci.call_args.kwargs
        assert "ci_logs" in call_kwargs
        assert "Error in test.py" in call_kwargs["ci_logs"]

    @pytest.mark.asyncio
    async def test_skips_ci_logs_when_disabled(
        self, config: HydraFlowConfig, tmp_path: Path
    ) -> None:
        """When inject_runtime_logs is False, fetch_ci_failure_logs is NOT called."""
        phase = make_review_phase(config, default_mocks=True)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()
        wt = tmp_path / "wt" / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        phase._prs.wait_for_ci = AsyncMock(
            side_effect=[
                (False, "Failed checks: Build"),
                (True, "All 1 checks passed"),
            ]
        )
        phase._prs.fetch_ci_failure_logs = AsyncMock(return_value="")
        fix_result = ReviewResultFactory.create(fixes_made=True)
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)

        # Need max_ci_fix_attempts > 0
        phase._config = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )

        await phase.wait_and_fix_ci(pr, issue, wt, result, 0)

        phase._prs.fetch_ci_failure_logs.assert_not_awaited()
