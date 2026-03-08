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
        assert (
            results[0].summary == "Review failed due to unexpected error (RuntimeError)"
        )
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


# ---------------------------------------------------------------------------
# Code scanning alerts in review phase
# ---------------------------------------------------------------------------


class TestCodeScanningAlertsFetch:
    """Tests for _fetch_code_scanning_alerts helper."""

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self, config: HydraFlowConfig) -> None:
        """When code_scanning_enabled is False, returns None."""
        cfg = ConfigFactory.create(
            code_scanning_enabled=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        pr = PRInfoFactory.create()

        result = await phase._fetch_code_scanning_alerts(pr)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_alerts_when_enabled(self, config: HydraFlowConfig) -> None:
        """When code_scanning_enabled is True and alerts exist, returns them."""
        cfg = ConfigFactory.create(
            code_scanning_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        pr = PRInfoFactory.create()

        alerts = [{"number": 1, "path": "foo.py", "severity": "error"}]
        phase._prs.fetch_code_scanning_alerts = AsyncMock(return_value=alerts)

        result = await phase._fetch_code_scanning_alerts(pr)
        assert result == alerts

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_alerts(self, config: HydraFlowConfig) -> None:
        """When API returns empty list, returns None."""
        cfg = ConfigFactory.create(
            code_scanning_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        pr = PRInfoFactory.create()

        phase._prs.fetch_code_scanning_alerts = AsyncMock(return_value=[])

        result = await phase._fetch_code_scanning_alerts(pr)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, config: HydraFlowConfig) -> None:
        """When API raises, returns None gracefully."""
        cfg = ConfigFactory.create(
            code_scanning_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        pr = PRInfoFactory.create()

        phase._prs.fetch_code_scanning_alerts = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        result = await phase._fetch_code_scanning_alerts(pr)
        assert result is None


class TestCodeScanningAlertThreading:
    """Tests that code scanning alerts are threaded through the review flow."""

    @pytest.mark.asyncio
    async def test_alerts_passed_to_reviewer(self, config: HydraFlowConfig) -> None:
        """Alerts are passed through to the reviewer.review call."""
        cfg = ConfigFactory.create(
            code_scanning_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        alerts = [{"number": 1, "path": "foo.py", "severity": "error"}]
        phase._prs.fetch_code_scanning_alerts = AsyncMock(return_value=alerts)

        await phase.review_prs([pr], [issue])

        # Verify review was called with code_scanning_alerts
        call_kwargs = phase._reviewers.review.call_args
        assert call_kwargs.kwargs.get("code_scanning_alerts") == alerts

    @pytest.mark.asyncio
    async def test_alerts_passed_to_ci_fix(self, config: HydraFlowConfig) -> None:
        """Alerts are threaded through to the CI fix agent."""
        cfg = ConfigFactory.create(
            code_scanning_enabled=True,
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        alerts = [{"number": 1, "path": "foo.py", "severity": "error"}]
        phase._prs.fetch_code_scanning_alerts = AsyncMock(return_value=alerts)

        # CI fails first time, fix makes changes, then passes
        phase._prs.wait_for_ci = AsyncMock(
            side_effect=[(False, "Failed"), (True, "Passed")]
        )
        fix_result = ReviewResultFactory.create(fixes_made=True)
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)

        await phase.review_prs([pr], [issue])

        # Verify fix_ci was called with code_scanning_alerts
        call_kwargs = phase._reviewers.fix_ci.call_args
        assert call_kwargs.kwargs.get("code_scanning_alerts") == alerts


# ---------------------------------------------------------------------------
# Visual gate (check_visual_gate)
# ---------------------------------------------------------------------------


class TestVisualGate:
    """Tests for check_visual_gate integration with the review phase."""

    @pytest.mark.asyncio
    async def test_returns_true_when_disabled(self, config: HydraFlowConfig) -> None:
        """When visual_gate_enabled is False, gate returns True immediately."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)
        assert ok is True
        assert result.visual_passed is None  # Not touched when disabled

    @pytest.mark.asyncio
    async def test_bypass_returns_true_with_audit_event(
        self, config: HydraFlowConfig
    ) -> None:
        """When bypass active, gate returns True and publishes audit event."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)
        assert ok is True
        assert result.visual_passed is True
        # Verify audit event was published
        phase._bus.publish.assert_awaited_once()
        event = phase._bus.publish.call_args.args[0]
        assert event.data["verdict"] == "bypass"
        assert "kill-switch" in event.data["reason"]

    @pytest.mark.asyncio
    async def test_enabled_pass_posts_sign_off_comment(
        self, config: HydraFlowConfig
    ) -> None:
        """When gate enabled and passes, posts sign-off comment on PR."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)
        assert ok is True
        assert result.visual_passed is True
        phase._prs.post_pr_comment.assert_awaited_once()
        comment = phase._prs.post_pr_comment.call_args.args[1]
        assert "PASSED" in comment

    @pytest.mark.asyncio
    async def test_emits_gate_telemetry(self, config: HydraFlowConfig) -> None:
        """Gate emits telemetry event with runtime, verdict, and retries."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        await phase.check_visual_gate(pr, issue, result, worker_id=0)

        phase._bus.publish.assert_awaited_once()
        event_data = phase._bus.publish.call_args.args[0].data
        assert "runtime_seconds" in event_data
        assert "verdict" in event_data
        assert "retries" in event_data
        assert event_data["verdict"] == "pass"

    @pytest.mark.asyncio
    async def test_handle_approved_merge_passes_visual_gate_fn(
        self, config: HydraFlowConfig
    ) -> None:
        """_handle_approved_merge wires check_visual_gate into handle_approved."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._post_merge.handle_approved = AsyncMock()
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        await phase._handle_approved_merge(pr, issue, result, "diff", 0)

        phase._post_merge.handle_approved.assert_awaited_once()
        call_kwargs = phase._post_merge.handle_approved.call_args.kwargs
        assert (
            call_kwargs["visual_gate_fn"].__func__ is phase.check_visual_gate.__func__
        )

    @pytest.mark.asyncio
    async def test_fail_verdict_blocks_merge_and_escalates(
        self, config: HydraFlowConfig
    ) -> None:
        """When _invoke_visual_pipeline returns fail, merge is blocked and HITL escalated."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._escalate_to_hitl = AsyncMock()
        phase._invoke_visual_pipeline = AsyncMock(
            return_value=("fail", {}, "diff regression detected")
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)
        assert ok is False
        assert result.visual_passed is False
        phase._prs.post_pr_comment.assert_awaited_once()
        comment = phase._prs.post_pr_comment.call_args.args[1]
        assert "BLOCKED" in comment
        phase._escalate_to_hitl.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_warn_verdict_blocks_merge(self, config: HydraFlowConfig) -> None:
        """When _invoke_visual_pipeline returns warn, merge is blocked."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._escalate_to_hitl = AsyncMock()
        phase._invoke_visual_pipeline = AsyncMock(
            return_value=("warn", {}, "minor visual drift")
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)
        assert ok is False
        assert result.visual_passed is False

    @pytest.mark.asyncio
    async def test_fail_verdict_emits_telemetry(self, config: HydraFlowConfig) -> None:
        """Fail verdict emits telemetry with verdict and reason."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._escalate_to_hitl = AsyncMock()
        phase._invoke_visual_pipeline = AsyncMock(
            return_value=("fail", {"report": "https://example.com/report"}, "mismatch")
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        await phase.check_visual_gate(pr, issue, result, worker_id=0)

        phase._bus.publish.assert_awaited_once()
        event_data = phase._bus.publish.call_args.args[0].data
        assert event_data["verdict"] == "fail"
        assert event_data["reason"] == "mismatch"
        assert "runtime_seconds" in event_data

    @pytest.mark.asyncio
    async def test_pass_verdict_with_artifacts_includes_links(
        self, config: HydraFlowConfig
    ) -> None:
        """Pass verdict with artifacts includes artifact links in sign-off comment."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._invoke_visual_pipeline = AsyncMock(
            return_value=(
                "pass",
                {
                    "baseline": "https://example.com/base",
                    "diff": "https://example.com/diff",
                },
                "all clear",
            )
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)
        assert ok is True
        assert result.visual_passed is True
        comment = phase._prs.post_pr_comment.call_args.args[1]
        assert "baseline" in comment
        assert "diff" in comment
        assert "Artifacts" in comment
