"""Tests for implement_phase.py - ImplementPhase class."""

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

from models import (
    Task,
    WorkerResult,
)
from tests.conftest import (
    PRInfoFactory,
    TaskFactory,
    WorkerResultFactory,
)
from tests.helpers import make_implement_phase

# ---------------------------------------------------------------------------
# run_batch
# ---------------------------------------------------------------------------


class TestImplementBatch:
    """Tests for the ImplementPhase.run_batch method."""

    @pytest.mark.asyncio
    async def test_returns_worker_results_for_each_issue(
        self, config: HydraFlowConfig
    ) -> None:
        issues = [TaskFactory.create(id=1), TaskFactory.create(id=2)]

        expected = [
            WorkerResultFactory.create(
                issue_number=1,
                worktree_path=str(config.worktree_path_for_issue(1)),
            ),
            WorkerResultFactory.create(
                issue_number=2,
                worktree_path=str(config.worktree_path_for_issue(2)),
            ),
        ]

        async def fake_agent_run(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return next(r for r in expected if r.issue_number == issue.id)

        phase, _, _ = make_implement_phase(config, issues, agent_run=fake_agent_run)

        returned, fetched = await phase.run_batch()
        assert len(returned) == 2
        issue_numbers = {r.issue_number for r in returned}
        assert issue_numbers == {1, 2}
        assert fetched == issues

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self, config: HydraFlowConfig) -> None:
        """max_workers=2 means at most 2 agents run concurrently."""
        concurrency_counter = {"current": 0, "peak": 0}

        async def fake_agent_run(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            concurrency_counter["current"] += 1
            concurrency_counter["peak"] = max(
                concurrency_counter["peak"],
                concurrency_counter["current"],
            )
            await asyncio.sleep(0)  # yield
            concurrency_counter["current"] -= 1
            return WorkerResultFactory.create(
                issue_number=issue.id, worktree_path=str(wt_path)
            )

        issues = [TaskFactory.create(id=i) for i in range(1, 6)]

        phase, _, _ = make_implement_phase(config, issues, agent_run=fake_agent_run)

        await phase.run_batch()

        assert concurrency_counter["peak"] <= config.max_workers

    @pytest.mark.asyncio
    async def test_marks_issue_in_progress_then_done(
        self, config: HydraFlowConfig
    ) -> None:
        issue = TaskFactory.create(id=55)

        phase, _, _ = make_implement_phase(config, [issue])

        await phase.run_batch()

        status = phase._state.to_dict()["processed_issues"].get(str(55))
        assert status == "success"

    @pytest.mark.asyncio
    async def test_marks_issue_failed_when_agent_fails(
        self, config: HydraFlowConfig
    ) -> None:
        issue = TaskFactory.create(id=66)

        phase, _, _ = make_implement_phase(config, [issue], success=False)

        await phase.run_batch()

        status = phase._state.to_dict()["processed_issues"].get(str(66))
        assert status == "failed"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_issues(self, config: HydraFlowConfig) -> None:
        """When fetch_ready_issues returns empty, return ([], [])."""
        phase, _, _ = make_implement_phase(config, [])

        results, issues = await phase.run_batch()

        assert results == []
        assert issues == []

    @pytest.mark.asyncio
    async def test_resumes_existing_worktree(self, config: HydraFlowConfig) -> None:
        """If worktree dir already exists, skip create and reuse it."""
        issue = TaskFactory.create(id=77)

        # Pre-create worktree directory to simulate resume
        wt_path = config.worktree_path_for_issue(77)
        wt_path.mkdir(parents=True, exist_ok=True)

        phase, mock_wt, _ = make_implement_phase(
            config, [issue], create_pr_return=PRInfoFactory.create(issue_number=77)
        )

        await phase.run_batch()

        # create should NOT have been called since worktree already exists
        mock_wt.create.assert_not_awaited()


# ---------------------------------------------------------------------------
# Implement includes push + PR creation
# ---------------------------------------------------------------------------


class TestImplementIncludesPush:
    """Tests that run_batch pushes and creates PRs per worker."""

    @pytest.mark.asyncio
    async def test_worker_result_contains_pr_info(
        self, config: HydraFlowConfig
    ) -> None:
        """After implementation, worker result should contain pr_info."""
        issue = TaskFactory.create()

        phase, _, _ = make_implement_phase(
            config, [issue], create_pr_return=PRInfoFactory.create()
        )

        results, _ = await phase.run_batch()

        assert len(results) == 1
        assert results[0].pr_info is not None
        assert results[0].pr_info.number == 101

    @pytest.mark.asyncio
    async def test_worker_creates_draft_pr_on_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """When agent fails, PR should be created as draft and label kept."""
        issue = TaskFactory.create()

        phase, _, mock_prs = make_implement_phase(
            config,
            [issue],
            success=False,
            create_pr_return=PRInfoFactory.create(draft=True),
        )

        await phase.run_batch()

        call_kwargs = mock_prs.create_pr.call_args
        assert call_kwargs.kwargs.get("draft") is True

        # On failure: should NOT remove hydraflow-ready or add hydraflow-review
        mock_prs.remove_label.assert_not_awaited()
        add_calls = [c.args for c in mock_prs.add_labels.call_args_list]
        assert (42, ["hydraflow-review"]) not in add_calls

    @pytest.mark.asyncio
    async def test_worker_no_pr_when_push_fails(self, config: HydraFlowConfig) -> None:
        """When push fails, pr_info should remain None."""
        issue = TaskFactory.create()

        phase, _, mock_prs = make_implement_phase(config, [issue], push_return=False)

        results, _ = await phase.run_batch()

        assert results[0].pr_info is None
        mock_prs.create_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_branch_pushed_and_commented_before_agent_runs(
        self, config: HydraFlowConfig
    ) -> None:
        """Branch should be pushed and a comment posted before the agent starts."""
        issue = TaskFactory.create()

        call_order: list[str] = []

        async def fake_push(wt_path: Path, branch: str) -> bool:
            call_order.append("push")
            return True

        async def fake_comment(issue_number: int, body: str) -> None:
            call_order.append("comment")

        async def fake_agent_run(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            call_order.append("agent")
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, mock_prs = make_implement_phase(
            config,
            [issue],
            agent_run=fake_agent_run,
            create_pr_return=PRInfoFactory.create(),
        )
        mock_prs.push_branch = fake_push
        mock_prs.post_comment = fake_comment

        await phase.run_batch()

        # push and comment must happen before agent
        assert call_order.index("push") < call_order.index("agent")
        assert call_order.index("comment") < call_order.index("agent")

    @pytest.mark.asyncio
    async def test_releases_active_issues_for_review(
        self, config: HydraFlowConfig
    ) -> None:
        """After implementation, mark_complete should be called on the store."""
        issue = TaskFactory.create()
        completed: list[int] = []

        phase, _, _ = make_implement_phase(config, [issue])
        phase._store.mark_complete = completed.append

        results, _ = await phase.run_batch()

        assert len(results) == 1
        assert results[0].success is True
        assert 42 in completed


# ---------------------------------------------------------------------------
# Worker exception isolation
# ---------------------------------------------------------------------------


class TestWorkerExceptionIsolation:
    """Tests that _worker catches exceptions and returns failed results."""

    @pytest.mark.asyncio
    async def test_worker_exception_returns_failed_result(
        self, config: HydraFlowConfig
    ) -> None:
        """When agent.run raises, worker should return a WorkerResult with error."""
        issue = TaskFactory.create()

        async def crashing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            raise RuntimeError("agent crashed")

        phase, _, _ = make_implement_phase(config, [issue], agent_run=crashing_agent)

        results, _ = await phase.run_batch()

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None
        assert "Worker exception" in results[0].error

    @pytest.mark.asyncio
    async def test_worker_exception_marks_issue_failed(
        self, config: HydraFlowConfig
    ) -> None:
        """When worker crashes, issue should be marked as 'failed' in state."""
        issue = TaskFactory.create()

        async def crashing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            raise RuntimeError("agent crashed")

        phase, _, _ = make_implement_phase(config, [issue], agent_run=crashing_agent)

        await phase.run_batch()

        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "failed"

    @pytest.mark.asyncio
    async def test_worker_exception_releases_active_issues(
        self, config: HydraFlowConfig
    ) -> None:
        """When worker crashes, mark_complete should be called on the store."""
        issue = TaskFactory.create()
        completed: list[int] = []

        async def crashing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            raise RuntimeError("agent crashed")

        phase, _, _ = make_implement_phase(config, [issue], agent_run=crashing_agent)
        phase._store.mark_complete = completed.append

        await phase.run_batch()

        assert 42 in completed

    @pytest.mark.asyncio
    async def test_worker_exception_does_not_crash_batch(
        self, config: HydraFlowConfig
    ) -> None:
        """With 2 issues, first worker crashing should not prevent the second."""
        issues = [TaskFactory.create(id=1), TaskFactory.create(id=2)]

        call_count = 0

        async def sometimes_crashing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            nonlocal call_count
            call_count += 1
            if issue.id == 1:
                raise RuntimeError("agent crashed for issue 1")
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, _ = make_implement_phase(
            config, issues, agent_run=sometimes_crashing_agent
        )

        results, _ = await phase.run_batch()

        # Both results should be returned
        assert len(results) == 2
        issue_numbers = {r.issue_number for r in results}
        assert issue_numbers == {1, 2}
        # Issue 1 failed, issue 2 succeeded
        result_map = {r.issue_number: r for r in results}
        assert result_map[1].success is False
        assert result_map[1].error is not None
        assert result_map[2].success is True


# ---------------------------------------------------------------------------
# Worktree creation failure edge cases
# ---------------------------------------------------------------------------


class TestWorktreeCreationFailure:
    """Tests for worktree creation failure during run_batch."""

    @pytest.mark.asyncio
    async def test_worktree_creation_failure_returns_error_result(
        self, config: HydraFlowConfig
    ) -> None:
        """When worktrees.create raises, worker should return a failed result."""
        issue = TaskFactory.create(id=42)

        phase, mock_wt, _ = make_implement_phase(config, [issue])
        mock_wt.create = AsyncMock(side_effect=RuntimeError("disk full"))

        results, _ = await phase.run_batch()

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None
        assert "Worker exception" in results[0].error

    @pytest.mark.asyncio
    async def test_worktree_creation_failure_does_not_crash_other_workers(
        self, config: HydraFlowConfig
    ) -> None:
        """First worktree.create failure should not prevent second worker from completing."""
        issues = [TaskFactory.create(id=1), TaskFactory.create(id=2)]

        async def create_side_effect(num: int, branch: str) -> Path:
            if num == 1:
                raise RuntimeError("disk full")
            return config.worktree_base / f"issue-{num}"

        phase, mock_wt, _ = make_implement_phase(config, issues)
        mock_wt.create = AsyncMock(side_effect=create_side_effect)

        results, _ = await phase.run_batch()

        assert len(results) == 2
        result_map = {r.issue_number: r for r in results}
        assert result_map[1].success is False
        assert "Worker exception" in result_map[1].error
        assert result_map[2].success is True

    @pytest.mark.asyncio
    async def test_stop_event_cancels_remaining_workers(
        self, config: HydraFlowConfig
    ) -> None:
        """Setting stop_event should cause workers to return early with error."""
        issues = [
            TaskFactory.create(id=1),
            TaskFactory.create(id=2),
            TaskFactory.create(id=3),
        ]

        async def slow_agent_run(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            # Simulate slow execution
            await asyncio.sleep(10)
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, _ = make_implement_phase(config, issues, agent_run=slow_agent_run)

        # Set stop event immediately
        phase._stop_event.set()

        results, _ = await phase.run_batch()

        # All collected results should be stopped (stop event checked before semaphore)
        for r in results:
            assert r.success is False
            assert r.error == "stopped"


# ---------------------------------------------------------------------------
# Lifecycle metric recording
# ---------------------------------------------------------------------------


class TestImplementLifecycleMetrics:
    """Tests that run_batch records new lifecycle metrics in state."""

    @pytest.mark.asyncio
    async def test_records_implementation_duration(
        self, config: HydraFlowConfig
    ) -> None:
        """Successful implementation should record duration in state."""
        issue = TaskFactory.create()

        async def agent_with_duration(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=True,
                worktree_path=str(wt_path),
                duration_seconds=60.5,
            )

        phase, _, _ = make_implement_phase(
            config, [issue], agent_run=agent_with_duration
        )
        await phase.run_batch()

        stats = phase._state.get_lifetime_stats()
        assert stats.total_implementation_seconds == pytest.approx(60.5)

    @pytest.mark.asyncio
    async def test_does_not_record_zero_duration(self, config: HydraFlowConfig) -> None:
        """Zero duration should not be recorded."""
        issue = TaskFactory.create()

        async def agent_zero_duration(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=True,
                worktree_path=str(wt_path),
                duration_seconds=0.0,
            )

        phase, _, _ = make_implement_phase(
            config, [issue], agent_run=agent_zero_duration
        )
        await phase.run_batch()

        stats = phase._state.get_lifetime_stats()
        assert stats.total_implementation_seconds == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_records_quality_fix_rounds(self, config: HydraFlowConfig) -> None:
        """Quality fix attempts should be recorded in state."""
        issue = TaskFactory.create()

        async def agent_with_qf(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=True,
                worktree_path=str(wt_path),
                quality_fix_attempts=2,
            )

        phase, _, _ = make_implement_phase(config, [issue], agent_run=agent_with_qf)
        await phase.run_batch()

        stats = phase._state.get_lifetime_stats()
        assert stats.total_quality_fix_rounds == 2

    @pytest.mark.asyncio
    async def test_does_not_record_zero_quality_fix_rounds(
        self, config: HydraFlowConfig
    ) -> None:
        """Zero quality fix attempts should not be recorded."""
        issue = TaskFactory.create()

        phase, _, _ = make_implement_phase(config, [issue])
        await phase.run_batch()

        stats = phase._state.get_lifetime_stats()
        assert stats.total_quality_fix_rounds == 0

    @pytest.mark.asyncio
    async def test_accumulates_across_multiple_issues(
        self, config: HydraFlowConfig
    ) -> None:
        """Metrics should accumulate across multiple issues in a batch."""
        issues = [TaskFactory.create(id=1), TaskFactory.create(id=2)]

        async def agent_with_metrics(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=True,
                worktree_path=str(wt_path),
                duration_seconds=30.0,
                quality_fix_attempts=1,
            )

        phase, _, _ = make_implement_phase(config, issues, agent_run=agent_with_metrics)
        await phase.run_batch()

        stats = phase._state.get_lifetime_stats()
        assert stats.total_implementation_seconds == pytest.approx(60.0)
        assert stats.total_quality_fix_rounds == 2


# ---------------------------------------------------------------------------
# Review feedback passing
# ---------------------------------------------------------------------------


class TestReviewFeedbackPassing:
    """Tests that review feedback is fetched, passed to agent, and cleared."""

    @pytest.mark.asyncio
    async def test_passes_review_feedback_to_agent(
        self, config: HydraFlowConfig
    ) -> None:
        """When review feedback exists in state, it should be passed to agent.run."""
        issue = TaskFactory.create()
        captured_feedback: list[str] = []

        async def capturing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            captured_feedback.append(review_feedback)
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, _ = make_implement_phase(
            config,
            [issue],
            agent_run=capturing_agent,
            create_pr_return=PRInfoFactory.create(),
        )
        # Set review feedback in state before running
        phase._state.set_review_feedback(42, "Fix the error handling")

        await phase.run_batch()

        assert len(captured_feedback) == 1
        assert captured_feedback[0] == "Fix the error handling"

    @pytest.mark.asyncio
    async def test_clears_review_feedback_after_implementation(
        self, config: HydraFlowConfig
    ) -> None:
        """Review feedback should be cleared from state after agent run."""
        issue = TaskFactory.create()

        async def simple_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, _ = make_implement_phase(
            config,
            [issue],
            agent_run=simple_agent,
            create_pr_return=PRInfoFactory.create(),
        )
        phase._state.set_review_feedback(42, "Fix the tests")

        await phase.run_batch()

        # Feedback should be cleared
        assert phase._state.get_review_feedback(42) is None

    @pytest.mark.asyncio
    async def test_no_feedback_passes_empty_string(
        self, config: HydraFlowConfig
    ) -> None:
        """When no review feedback exists, agent should receive empty string."""
        issue = TaskFactory.create()
        captured_feedback: list[str] = []

        async def capturing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            captured_feedback.append(review_feedback)
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, _ = make_implement_phase(
            config,
            [issue],
            agent_run=capturing_agent,
            create_pr_return=PRInfoFactory.create(),
        )
        # Do NOT set any feedback

        await phase.run_batch()

        assert len(captured_feedback) == 1
        assert captured_feedback[0] == ""

    @pytest.mark.asyncio
    async def test_skips_pr_creation_on_retry(self, config: HydraFlowConfig) -> None:
        """When review_feedback is present (retry), PR creation should be skipped."""
        issue = TaskFactory.create()

        async def simple_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, mock_prs = make_implement_phase(
            config,
            [issue],
            agent_run=simple_agent,
            create_pr_return=PRInfoFactory.create(),
        )
        # Set review feedback to simulate a retry cycle
        phase._state.set_review_feedback(42, "Fix error handling")

        results, _ = await phase.run_batch()

        # PR creation should be skipped on retry
        mock_prs.create_pr.assert_not_awaited()
        # But result should still be successful
        assert results[0].success is True
        # Existing PR should be recovered from branch lookup
        assert results[0].pr_info is not None
        assert results[0].pr_info.number == 101

    @pytest.mark.asyncio
    async def test_creates_pr_on_first_run(self, config: HydraFlowConfig) -> None:
        """Without review feedback (first run), PR should be created normally."""
        issue = TaskFactory.create()

        async def simple_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, mock_prs = make_implement_phase(
            config,
            [issue],
            agent_run=simple_agent,
            create_pr_return=PRInfoFactory.create(),
        )
        # No review feedback — first run

        results, _ = await phase.run_batch()

        # PR creation should happen
        mock_prs.create_pr.assert_awaited_once()
        assert results[0].pr_info is not None
        assert results[0].pr_info.number == 101


# ---------------------------------------------------------------------------
# Worker result metadata persistence
# ---------------------------------------------------------------------------


class TestWorkerResultMetaPersistence:
    """Tests that worker result metadata is persisted to state."""

    @pytest.mark.asyncio
    async def test_worker_result_meta_persisted_after_run(
        self, config: HydraFlowConfig
    ) -> None:
        """Worker result metadata should be saved to state after agent run."""
        issue = TaskFactory.create()

        async def agent_with_metrics(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=True,
                worktree_path=str(wt_path),
                quality_fix_attempts=2,
                duration_seconds=150.5,
                error=None,
            )

        phase, _, _ = make_implement_phase(
            config, [issue], agent_run=agent_with_metrics
        )

        await phase.run_batch()

        meta = phase._state.get_worker_result_meta(42)
        assert meta["quality_fix_attempts"] == 2
        assert meta["duration_seconds"] == 150.5
        assert meta["error"] is None

    @pytest.mark.asyncio
    async def test_worker_result_meta_includes_error(
        self, config: HydraFlowConfig
    ) -> None:
        """When agent fails, error should be captured in metadata."""
        issue = TaskFactory.create()

        async def failing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=False,
                worktree_path=str(wt_path),
                quality_fix_attempts=0,
                duration_seconds=30.0,
                error="make quality failed",
            )

        phase, _, _ = make_implement_phase(config, [issue], agent_run=failing_agent)

        await phase.run_batch()

        meta = phase._state.get_worker_result_meta(42)
        assert meta["error"] == "make quality failed"


# ---------------------------------------------------------------------------
# Zero-commit escalation handling
# ---------------------------------------------------------------------------


class TestZeroCommitEscalation:
    """Tests that zero-commit failures escalate to HITL instead of closing."""

    @pytest.mark.asyncio
    async def test_zero_commit_escalates_to_hitl(self, config: HydraFlowConfig) -> None:
        """When agent returns zero commits, issue should escalate to HITL."""
        issue = TaskFactory.create()

        async def zero_commit_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=False,
                error="No commits found on branch",
                commits=0,
                worktree_path=str(wt_path),
            )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], agent_run=zero_commit_agent
        )

        results, _ = await phase.run_batch()

        # Comment should be posted about zero commits
        comment_calls = [c.args for c in mock_prs.post_comment.call_args_list]
        assert any("Zero Commits" in c[1] for c in comment_calls)

        # Issue should be escalated to HITL with cause
        mock_prs.swap_pipeline_labels.assert_awaited_once_with(42, config.hitl_label[0])
        assert phase._state.get_hitl_cause(42) == "implementation produced zero commits"

    @pytest.mark.asyncio
    async def test_zero_commit_marks_issue_failed(
        self, config: HydraFlowConfig
    ) -> None:
        """When zero-commit detected, issue state should be 'failed'."""
        issue = TaskFactory.create()

        async def zero_commit_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=False,
                error="No commits found on branch",
                commits=0,
                worktree_path=str(wt_path),
            )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], agent_run=zero_commit_agent
        )

        await phase.run_batch()

        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "failed"

    @pytest.mark.asyncio
    async def test_nonzero_commits_not_escalated_as_zero_commit(
        self, config: HydraFlowConfig
    ) -> None:
        """A failed result with commits > 0 should NOT be treated as zero-commit."""
        issue = TaskFactory.create()

        async def failing_with_commits(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=False,
                error="make quality failed",
                commits=2,
                worktree_path=str(wt_path),
            )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], agent_run=failing_with_commits
        )
        mock_prs.close_task = AsyncMock()

        await phase.run_batch()

        # Should NOT close the issue
        mock_prs.close_task.assert_not_awaited()
        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "failed"

    @pytest.mark.asyncio
    async def test_epic_child_zero_commit_cause_includes_epic_context(
        self, config: HydraFlowConfig
    ) -> None:
        """Epic child issues should have cause prefixed with epic context."""
        issue = TaskFactory.create(
            tags=["hydraflow-epic-child"],
            body="## Parent Epic: #1551\n\nSome description",
        )

        async def zero_commit_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=False,
                error="No commits found on branch",
                commits=0,
                worktree_path=str(wt_path),
            )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], agent_run=zero_commit_agent
        )

        await phase.run_batch()

        cause = phase._state.get_hitl_cause(42)
        assert cause == "Epic child (#1551): implementation produced zero commits"


# ---------------------------------------------------------------------------
# Post-mortem memory filing
# ---------------------------------------------------------------------------


class TestPostMortemMemoryFiling:
    """Failure escalations file memory suggestions from agent transcripts."""

    @pytest.mark.asyncio
    async def test_zero_commit_files_memory_from_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        """Zero-commit failure should attempt to file a memory suggestion."""
        issue = TaskFactory.create()

        async def zero_commit_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=False,
                error="No commits found on branch",
                commits=0,
                worktree_path=str(wt_path),
                transcript="MEMORY_SUGGESTION_START\ntitle: test\nlearning: learned\nMEMORY_SUGGESTION_END",
            )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], agent_run=zero_commit_agent
        )

        await phase.run_batch()

        # Memory suggestion should be filed as an issue
        create_calls = mock_prs.create_issue.call_args_list
        assert any("[Memory]" in str(c) for c in create_calls)

    @pytest.mark.asyncio
    async def test_zero_commit_no_memory_when_no_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        """Zero-commit with empty transcript should not attempt memory filing."""
        issue = TaskFactory.create()

        async def zero_commit_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=False,
                error="No commits found on branch",
                commits=0,
                worktree_path=str(wt_path),
                transcript="",
            )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], agent_run=zero_commit_agent
        )

        await phase.run_batch()

        # No memory issue should be created
        create_calls = mock_prs.create_issue.call_args_list
        assert not any("[Memory]" in str(c) for c in create_calls)

    @pytest.mark.asyncio
    async def test_zero_diff_files_memory_from_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        """Zero-diff failure should attempt to file a memory suggestion."""
        issue = TaskFactory.create()

        async def zero_diff_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=True,
                commits=1,
                worktree_path=str(wt_path),
                transcript="MEMORY_SUGGESTION_START\ntitle: zero diff\nlearning: no changes\nMEMORY_SUGGESTION_END",
            )

        from tests.conftest import PRInfoFactory

        # create_pr returns a PR with number=0 to trigger the zero-diff check
        null_pr = PRInfoFactory.create(number=0)
        phase, _, mock_prs = make_implement_phase(
            config, [issue], agent_run=zero_diff_agent, create_pr_return=null_pr
        )
        # Make branch_has_diff_from_main return False to trigger zero-diff path
        mock_prs.branch_has_diff_from_main = AsyncMock(return_value=False)

        await phase.run_batch()

        create_calls = mock_prs.create_issue.call_args_list
        assert any("[Memory]" in str(c) for c in create_calls)


# ---------------------------------------------------------------------------
# Retry cap escalation
# ---------------------------------------------------------------------------


class TestRetryCapEscalation:
    """Tests that issues exceeding max_issue_attempts escalate to HITL."""

    @pytest.mark.asyncio
    async def test_issue_under_cap_proceeds_normally(self, tmp_path: Path) -> None:
        """Issues under the cap should proceed to agent run."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])

        # Pre-set 1 attempt (will be incremented to 2, still under cap of 3)
        phase._state.increment_issue_attempts(42)

        results, _ = await phase.run_batch()

        assert len(results) == 1
        assert results[0].success is True
        assert phase._state.get_issue_attempts(42) == 2

    @pytest.mark.asyncio
    async def test_issue_at_cap_escalates_to_hitl(self, tmp_path: Path) -> None:
        """Issues at the cap should escalate to HITL without running the agent."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_issue_attempts=2,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()

        agent_called = False

        async def tracking_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            nonlocal agent_called
            agent_called = True
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], agent_run=tracking_agent
        )

        # Pre-set attempts to match cap (2), so next increment = 3 > 2
        phase._state.increment_issue_attempts(42)
        phase._state.increment_issue_attempts(42)

        results, _ = await phase.run_batch()

        assert len(results) == 1
        assert results[0].success is False
        assert "attempt cap exceeded" in (results[0].error or "")
        assert not agent_called

        # Labels should be swapped to HITL
        mock_prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-hitl")

        # Comment should mention attempt cap
        comment_calls = [c.args for c in mock_prs.post_comment.call_args_list]
        assert any("attempt cap exceeded" in c[1] for c in comment_calls)

        # HITL origin and cause should be set
        assert phase._state.get_hitl_origin(42) is not None
        assert phase._state.get_hitl_cause(42) is not None

    @pytest.mark.asyncio
    async def test_boundary_attempt_proceeds(self, tmp_path: Path) -> None:
        """With max_issue_attempts=3, the 3rd attempt should proceed (not escalate)."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])

        # Pre-set 2 attempts; next increment = 3 == max, should proceed
        phase._state.increment_issue_attempts(42)
        phase._state.increment_issue_attempts(42)

        results, _ = await phase.run_batch()

        assert len(results) == 1
        assert results[0].success is True
        assert phase._state.get_issue_attempts(42) == 3


# ---------------------------------------------------------------------------
# Commits persisted in worker result metadata
# ---------------------------------------------------------------------------


class TestCommitsPersistedInMeta:
    """Tests that commits field is included in worker_result_meta."""

    @pytest.mark.asyncio
    async def test_commits_in_worker_result_meta(self, config: HydraFlowConfig) -> None:
        """After agent run, worker_result_meta should contain 'commits' key."""
        issue = TaskFactory.create()

        async def agent_with_commits(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=True,
                worktree_path=str(wt_path),
                commits=3,
                quality_fix_attempts=1,
                duration_seconds=90.0,
            )

        phase, _, _ = make_implement_phase(
            config, [issue], agent_run=agent_with_commits
        )

        await phase.run_batch()

        meta = phase._state.get_worker_result_meta(42)
        assert meta["commits"] == 3
        assert meta["quality_fix_attempts"] == 1
        assert meta["duration_seconds"] == 90.0


# ---------------------------------------------------------------------------
# Active issue persistence
# ---------------------------------------------------------------------------


class TestActiveIssuePersistence:
    """Tests that active issues are persisted to state."""

    @pytest.mark.asyncio
    async def test_active_issue_persisted_and_removed(
        self, config: HydraFlowConfig
    ) -> None:
        """After run_batch, active_issue_numbers should be cleared."""
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])

        await phase.run_batch()

        # After completion, issue should not be in active list
        active = phase._state.get_active_issue_numbers()
        assert 42 not in active


# ---------------------------------------------------------------------------
# Extracted method unit tests
# ---------------------------------------------------------------------------


class TestCheckAttemptCap:
    """Unit tests for the _check_attempt_cap helper."""

    @pytest.mark.asyncio
    async def test_under_cap_returns_none(self, tmp_path: Path) -> None:
        """Issues under the cap should return None (proceed)."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])

        result = await phase._check_attempt_cap(issue, "agent/issue-42")

        assert result is None

    @pytest.mark.asyncio
    async def test_at_cap_returns_none(self, tmp_path: Path) -> None:
        """Issues at the cap boundary should return None (proceed)."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])

        # Pre-set 2 attempts; increment to 3 == max, should proceed
        phase._state.increment_issue_attempts(42)
        phase._state.increment_issue_attempts(42)

        result = await phase._check_attempt_cap(issue, "agent/issue-42")

        assert result is None

    @pytest.mark.asyncio
    async def test_over_cap_returns_error_result(self, tmp_path: Path) -> None:
        """Issues over the cap should return a WorkerResult with error."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_issue_attempts=2,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])

        # Pre-set 2 attempts; increment to 3 > 2 cap
        phase._state.increment_issue_attempts(42)
        phase._state.increment_issue_attempts(42)

        result = await phase._check_attempt_cap(issue, "agent/issue-42")

        assert result is not None
        assert result.success is False
        assert "attempt cap exceeded" in (result.error or "")

    @pytest.mark.asyncio
    async def test_over_cap_sets_hitl_state(self, tmp_path: Path) -> None:
        """Over-cap should set HITL origin and cause in state."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_issue_attempts=2,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])

        phase._state.increment_issue_attempts(42)
        phase._state.increment_issue_attempts(42)

        await phase._check_attempt_cap(issue, "agent/issue-42")

        assert phase._state.get_hitl_origin(42) is not None
        assert phase._state.get_hitl_cause(42) is not None

    @pytest.mark.asyncio
    async def test_over_cap_swaps_labels(self, tmp_path: Path) -> None:
        """Over-cap should remove ready labels and add HITL label."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_issue_attempts=2,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        phase, _, mock_prs = make_implement_phase(config, [issue])

        phase._state.increment_issue_attempts(42)
        phase._state.increment_issue_attempts(42)

        await phase._check_attempt_cap(issue, "agent/issue-42")

        mock_prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-hitl")


class TestRunImplementation:
    """Unit tests for the _run_implementation helper."""

    @pytest.mark.asyncio
    async def test_creates_worktree_when_missing(self, config: HydraFlowConfig) -> None:
        """When worktree dir doesn't exist, should create one."""
        issue = TaskFactory.create()
        phase, mock_wt, _ = make_implement_phase(config, [issue])

        await phase._run_implementation(issue, "agent/issue-42", 0, "")

        mock_wt.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reuses_existing_worktree(self, config: HydraFlowConfig) -> None:
        """When worktree dir exists, should reuse it."""
        issue = TaskFactory.create()

        wt_path = config.worktree_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)

        phase, mock_wt, _ = make_implement_phase(config, [issue])

        await phase._run_implementation(issue, "agent/issue-42", 0, "")

        mock_wt.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_review_feedback_to_agent(
        self, config: HydraFlowConfig
    ) -> None:
        """Review feedback should be passed to the agent."""
        issue = TaskFactory.create()
        captured_feedback: list[str] = []

        async def capturing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            captured_feedback.append(review_feedback)
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        phase, _, _ = make_implement_phase(config, [issue], agent_run=capturing_agent)
        phase._state.set_review_feedback(42, "Fix error handling")

        await phase._run_implementation(
            issue, "agent/issue-42", 0, "Fix error handling"
        )

        assert captured_feedback[0] == "Fix error handling"

    @pytest.mark.asyncio
    async def test_clears_review_feedback_after_run(
        self, config: HydraFlowConfig
    ) -> None:
        """Review feedback should be cleared from state after agent run."""
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])
        phase._state.set_review_feedback(42, "Fix it")

        await phase._run_implementation(issue, "agent/issue-42", 0, "Fix it")

        assert phase._state.get_review_feedback(42) is None

    @pytest.mark.asyncio
    async def test_records_metrics(self, config: HydraFlowConfig) -> None:
        """Duration and quality fix rounds should be recorded."""
        issue = TaskFactory.create()

        async def agent_with_metrics(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResult(
                issue_number=issue.id,
                branch=branch,
                success=True,
                worktree_path=str(wt_path),
                duration_seconds=60.0,
                quality_fix_attempts=2,
            )

        phase, _, _ = make_implement_phase(
            config, [issue], agent_run=agent_with_metrics
        )

        await phase._run_implementation(issue, "agent/issue-42", 0, "")

        stats = phase._state.get_lifetime_stats()
        assert stats.total_implementation_seconds == pytest.approx(60.0)
        assert stats.total_quality_fix_rounds == 2


class TestHandleImplementationResult:
    """Unit tests for the _handle_implementation_result helper."""

    @pytest.mark.asyncio
    async def test_zero_commit_escalates_to_hitl(self, config: HydraFlowConfig) -> None:
        """Zero-commit failure should escalate to HITL, not close as satisfied."""
        issue = TaskFactory.create()
        result = WorkerResult(
            issue_number=42,
            branch="agent/issue-42",
            success=False,
            error="No commits found on branch",
            commits=0,
            worktree_path=str(config.worktree_path_for_issue(42)),
        )

        phase, _, mock_prs = make_implement_phase(config, [issue])

        returned = await phase._handle_implementation_result(issue, result, False)

        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "failed"
        mock_prs.swap_pipeline_labels.assert_awaited_once_with(42, config.hitl_label[0])
        assert phase._state.get_hitl_cause(42) == "implementation produced zero commits"
        assert returned is result

    @pytest.mark.asyncio
    async def test_success_creates_pr_and_swaps_labels(
        self, config: HydraFlowConfig
    ) -> None:
        """Successful result should create a PR and swap labels."""
        issue = TaskFactory.create()
        result = WorkerResultFactory.create(
            issue_number=42,
            success=True,
            worktree_path=str(config.worktree_path_for_issue(42)),
        )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], create_pr_return=PRInfoFactory.create()
        )

        returned = await phase._handle_implementation_result(issue, result, False)

        assert returned.pr_info is not None
        assert returned.pr_info.number == 101
        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "success"

        mock_prs.transition.assert_awaited_once_with(42, "review", pr_number=101)

    @pytest.mark.asyncio
    async def test_retry_skips_pr_creation(self, config: HydraFlowConfig) -> None:
        """On retry (is_retry=True), PR creation should be skipped."""
        issue = TaskFactory.create()
        result = WorkerResultFactory.create(
            issue_number=42,
            success=True,
            worktree_path=str(config.worktree_path_for_issue(42)),
        )

        phase, _, mock_prs = make_implement_phase(config, [issue])

        returned = await phase._handle_implementation_result(issue, result, True)

        mock_prs.create_pr.assert_not_awaited()
        assert returned.pr_info is not None
        assert returned.pr_info.number == 101
        mock_prs.transition.assert_awaited_once_with(42, "review", pr_number=101)

    @pytest.mark.asyncio
    async def test_success_without_pr_and_no_branch_diff_escalates_to_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """No PR + no branch diff should escalate to HITL, not close as satisfied."""
        issue = TaskFactory.create()
        result = WorkerResultFactory.create(
            issue_number=42,
            success=True,
            worktree_path=str(config.worktree_path_for_issue(42)),
        )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], create_pr_return=PRInfoFactory.create(number=0)
        )
        mock_prs.find_open_pr_for_branch.return_value = None
        mock_prs.branch_has_diff_from_main.return_value = False

        await phase._handle_implementation_result(issue, result, False)

        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "failed"
        mock_prs.swap_pipeline_labels.assert_awaited()
        assert (
            phase._state.get_hitl_cause(42)
            == "implementation produced no changes (zero diff)"
        )

    @pytest.mark.asyncio
    async def test_success_without_pr_and_with_diff_stays_ready_as_failed(
        self, config: HydraFlowConfig
    ) -> None:
        """No PR + branch diff should avoid review transition and mark failed."""
        issue = TaskFactory.create()
        result = WorkerResultFactory.create(
            issue_number=42,
            success=True,
            worktree_path=str(config.worktree_path_for_issue(42)),
        )

        phase, _, mock_prs = make_implement_phase(
            config, [issue], create_pr_return=PRInfoFactory.create(number=0)
        )
        mock_prs.find_open_pr_for_branch.return_value = None
        mock_prs.branch_has_diff_from_main.return_value = True

        returned = await phase._handle_implementation_result(issue, result, False)

        assert returned.success is False
        assert returned.error == "PR creation failed"
        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "failed"
        mock_prs.transition.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failure_marks_issue_failed(self, config: HydraFlowConfig) -> None:
        """Failed result should mark issue as failed."""
        issue = TaskFactory.create()
        result = WorkerResultFactory.create(issue_number=42, success=False)

        phase, _, _ = make_implement_phase(config, [issue])

        await phase._handle_implementation_result(issue, result, False)

        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "failed"

    @pytest.mark.asyncio
    async def test_empty_worktree_path_skips_push_and_pr(
        self, config: HydraFlowConfig
    ) -> None:
        """When result.worktree_path is empty, push and PR creation should be skipped."""
        issue = TaskFactory.create()
        result = WorkerResult(
            issue_number=42,
            branch="agent/issue-42",
            success=True,
            worktree_path="",
        )

        phase, _, mock_prs = make_implement_phase(config, [issue])

        returned = await phase._handle_implementation_result(issue, result, False)

        mock_prs.push_branch.assert_not_awaited()
        mock_prs.create_pr.assert_not_awaited()
        assert phase._state.to_dict()["processed_issues"].get(str(42)) == "success"
        assert returned is result


class TestWorkerInner:
    """Unit tests for the _worker_inner coordinator method."""

    @pytest.mark.asyncio
    async def test_cap_exceeded_returns_early(self, tmp_path: Path) -> None:
        """When attempt cap is exceeded, should return error without running agent."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            max_issue_attempts=1,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()

        agent_called = False

        async def tracking_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            nonlocal agent_called
            agent_called = True
            return WorkerResultFactory.create(
                issue_number=issue.id, worktree_path=str(wt_path)
            )

        phase, _, _ = make_implement_phase(config, [issue], agent_run=tracking_agent)

        # Pre-set attempt to match cap
        phase._state.increment_issue_attempts(42)

        result = await phase._worker_inner(0, issue, "agent/issue-42")

        assert result.success is False
        assert not agent_called

    @pytest.mark.asyncio
    async def test_normal_flow_runs_agent_and_handles_result(
        self, config: HydraFlowConfig
    ) -> None:
        """Normal flow should run agent and handle result."""
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(
            config, [issue], create_pr_return=PRInfoFactory.create()
        )

        result = await phase._worker_inner(0, issue, "agent/issue-42")

        assert result.success is True


# ---------------------------------------------------------------------------
# _read_plan_for_recording
# ---------------------------------------------------------------------------


class TestReadPlanForRecording:
    """Regression tests for _read_plan_for_recording using .hydraflow/plans/."""

    def test_reads_plan_from_hydraflow_plans_dir(self, config: HydraFlowConfig) -> None:
        plan_content = "## Plan\n\n1. Fix the bug\n2. Add tests"
        plans_dir = config.repo_root / ".hydraflow" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / "issue-42.md").write_text(plan_content)

        phase, _, _ = make_implement_phase(config, [])
        result = phase._read_plan_for_recording(42)

        assert result == plan_content

    def test_returns_empty_string_when_plan_missing(
        self, config: HydraFlowConfig
    ) -> None:
        phase, _, _ = make_implement_phase(config, [])
        result = phase._read_plan_for_recording(99)

        assert result == ""


# ---------------------------------------------------------------------------
# Critical exception propagation through _worker
# ---------------------------------------------------------------------------


class TestCriticalExceptionPropagation:
    """Tests that critical exceptions propagate through the worker."""

    @pytest.mark.asyncio
    async def test_auth_error_propagates_through_worker(
        self, config: HydraFlowConfig
    ) -> None:
        """AuthenticationError should propagate, not be caught by except Exception."""
        from subprocess_util import AuthenticationError

        issue = TaskFactory.create()

        async def auth_failing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            raise AuthenticationError("401 Unauthorized")

        phase, _, _ = make_implement_phase(
            config, [issue], agent_run=auth_failing_agent
        )

        with pytest.raises(AuthenticationError, match="401"):
            await phase.run_batch()

    @pytest.mark.asyncio
    async def test_credit_error_propagates_through_worker(
        self, config: HydraFlowConfig
    ) -> None:
        """CreditExhaustedError should propagate, not be caught by except Exception."""
        from subprocess_util import CreditExhaustedError

        issue = TaskFactory.create()

        async def credit_failing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            raise CreditExhaustedError("limit reached")

        phase, _, _ = make_implement_phase(
            config, [issue], agent_run=credit_failing_agent
        )

        with pytest.raises(CreditExhaustedError, match="limit reached"):
            await phase.run_batch()

    @pytest.mark.asyncio
    async def test_memory_error_propagates_through_worker(
        self, config: HydraFlowConfig
    ) -> None:
        """MemoryError should propagate, not be caught by except Exception."""
        issue = TaskFactory.create()

        async def oom_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            raise MemoryError("out of memory")

        phase, _, _ = make_implement_phase(config, [issue], agent_run=oom_agent)

        with pytest.raises(MemoryError, match="out of memory"):
            await phase.run_batch()


class TestADRSequence:
    """Tests for ADR-specific implementation sequencing."""

    def test_prepare_adr_plan_writes_fallback_plan_for_adr_issue(
        self, config: HydraFlowConfig
    ) -> None:
        issue = TaskFactory.create(
            id=500,
            title="[ADR] Event pipeline architecture",
            body="## Context\nA\n\n## Decision\nB\n\n## Consequences\nC",
        )
        phase, _, _ = make_implement_phase(config, [issue])

        phase._prepare_adr_plan(issue)

        plan_path = config.plans_dir / "issue-500.md"
        assert plan_path.exists()
        content = plan_path.read_text()
        assert "## Implementation Plan" in content
        assert "docs/adr/" in content

    def test_prepare_adr_plan_skips_non_adr_issue(
        self, config: HydraFlowConfig
    ) -> None:
        issue = TaskFactory.create(id=501, title="Regular issue", body="body")
        phase, _, _ = make_implement_phase(config, [issue])

        phase._prepare_adr_plan(issue)

        plan_path = config.plans_dir / "issue-501.md"
        assert not plan_path.exists()
