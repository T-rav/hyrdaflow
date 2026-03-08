"""Tests for stop-and-resume behavior (issue #776).

Covers:
- State persistence for interrupted issues
- Orchestrator stop checkpointing and loop task cancellation
- Interrupted issue restoration on restart
- Worktree preservation during stop
- Review phase stop-event handling
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator

from tests.conftest import PRInfoFactory, ReviewResultFactory, TaskFactory
from tests.helpers import ConfigFactory, make_review_phase

# ---------------------------------------------------------------------------
# State persistence tests
# ---------------------------------------------------------------------------


class TestStateInterruptedIssues:
    """Tests for interrupted_issues round-trip via StateTracker."""

    def test_set_and_get_interrupted_issues(self, tmp_path: Path) -> None:
        from state import StateTracker

        tracker = StateTracker(tmp_path / "state.json")
        mapping = {42: "implementing", 99: "reviewing"}
        tracker.set_interrupted_issues(mapping)

        result = tracker.get_interrupted_issues()
        assert result == {42: "implementing", 99: "reviewing"}

    def test_clear_interrupted_issues(self, tmp_path: Path) -> None:
        from state import StateTracker

        tracker = StateTracker(tmp_path / "state.json")
        tracker.set_interrupted_issues({10: "planning"})
        tracker.clear_interrupted_issues()

        assert tracker.get_interrupted_issues() == {}

    def test_interrupted_issues_default_empty(self, tmp_path: Path) -> None:
        from state import StateTracker

        tracker = StateTracker(tmp_path / "state.json")
        assert tracker.get_interrupted_issues() == {}

    def test_interrupted_issues_persist_across_load(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        tracker1 = StateTracker(state_file)
        tracker1.set_interrupted_issues({5: "plan", 10: "implement"})

        # Load from disk in a new instance
        tracker2 = StateTracker(state_file)
        assert tracker2.get_interrupted_issues() == {5: "plan", 10: "implement"}

    def test_interrupted_issues_int_key_conversion(self, tmp_path: Path) -> None:
        """Keys are stored as strings in JSON but returned as ints."""
        from state import StateTracker

        tracker = StateTracker(tmp_path / "state.json")
        tracker.set_interrupted_issues({123: "review"})
        result = tracker.get_interrupted_issues()
        assert all(isinstance(k, int) for k in result)
        assert result[123] == "review"


# ---------------------------------------------------------------------------
# Orchestrator stop tests
# ---------------------------------------------------------------------------


def _make_orchestrator(tmp_path: Path) -> HydraFlowOrchestrator:
    """Build a minimal orchestrator with mocked dependencies for stop tests."""

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    (tmp_path / "worktrees").mkdir(parents=True, exist_ok=True)

    with patch("orchestrator.build_services") as mock_build:
        svc = MagicMock()
        # Runners with _active_procs
        for runner_attr in ("planners", "agents", "reviewers", "hitl_runner"):
            runner = MagicMock()
            runner._active_procs = set()
            runner.terminate = MagicMock()
            setattr(svc, runner_attr, runner)

        # Store (IssueStore mock)
        svc.store = MagicMock()
        svc.store.get_active_issues = MagicMock(return_value={})
        svc.store.clear_active = MagicMock()

        # Other services we need
        svc.worktrees = AsyncMock()
        svc.subprocess_runner = MagicMock()
        svc.prs = AsyncMock()
        svc.prs.ensure_labels_exist = AsyncMock()
        svc.prs.pull_main = AsyncMock()
        svc.triage = MagicMock()
        svc.triager = MagicMock()
        svc.planner_phase = MagicMock()
        svc.hitl_phase = MagicMock()
        svc.hitl_phase.active_hitl_issues = set()
        svc.run_recorder = MagicMock()
        svc.implementer = MagicMock()
        svc.metrics_manager = MagicMock()
        svc.pr_unsticker = MagicMock()
        svc.memory_sync = MagicMock()
        svc.retrospective = MagicMock()
        svc.ac_generator = MagicMock()
        svc.verification_judge = MagicMock()
        svc.epic_checker = MagicMock()
        svc.reviewer = MagicMock()
        svc.memory_sync_bg = MagicMock()
        svc.metrics_sync_bg = MagicMock()
        svc.pr_unsticker_loop = MagicMock()
        svc.manifest_refresh_loop = MagicMock()
        svc.fetcher = MagicMock()
        svc.summarizer = MagicMock()

        mock_build.return_value = svc

        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)

    return orch


class TestOrchestratorStop:
    """Tests for orchestrator stop() behavior."""

    @pytest.mark.asyncio
    async def test_stop_cancels_loop_tasks(self, tmp_path: Path) -> None:
        """stop() cancels _loop_tasks, causing _supervise_loops to exit."""
        orch = _make_orchestrator(tmp_path)

        # Simulate loop tasks
        async def _forever():
            await asyncio.sleep(3600)

        task1 = asyncio.create_task(_forever())
        task2 = asyncio.create_task(_forever())
        orch._loop_tasks = {"plan": task1, "implement": task2}

        await orch.stop()

        # Allow cancellation to propagate
        await asyncio.sleep(0)

        assert task1.cancelled()
        assert task2.cancelled()

    @pytest.mark.asyncio
    async def test_stop_persists_interrupted_issues(self, tmp_path: Path) -> None:
        """After stop(), state file contains the correct interrupted_issues."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {42: "implement", 99: "review"}

        await orch.stop()

        result = orch._state.get_interrupted_issues()
        assert result == {42: "implement", 99: "review"}

    @pytest.mark.asyncio
    async def test_stop_mid_implement_checkpoints_phase(self, tmp_path: Path) -> None:
        """Issue in implement phase gets checkpointed as 'implement'."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {42: "implement"}

        await orch.stop()

        interrupted = orch._state.get_interrupted_issues()
        assert interrupted[42] == "implement"

    @pytest.mark.asyncio
    async def test_stop_mid_plan_checkpoints_phase(self, tmp_path: Path) -> None:
        """Issue in plan phase gets checkpointed as 'plan'."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {42: "plan"}

        await orch.stop()

        interrupted = orch._state.get_interrupted_issues()
        assert interrupted[42] == "plan"

    @pytest.mark.asyncio
    async def test_stop_mid_review_checkpoints_phase(self, tmp_path: Path) -> None:
        """Issue in review phase gets checkpointed as 'review'."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {99: "review"}

        await orch.stop()

        interrupted = orch._state.get_interrupted_issues()
        assert interrupted[99] == "review"

    @pytest.mark.asyncio
    async def test_stop_includes_in_memory_impl_issues(self, tmp_path: Path) -> None:
        """Issues tracked in _active_impl_issues but not in store are included."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {}
        orch._active_impl_issues = {55}

        await orch.stop()

        interrupted = orch._state.get_interrupted_issues()
        assert interrupted[55] == "implement"

    @pytest.mark.asyncio
    async def test_stop_includes_in_memory_review_issues(self, tmp_path: Path) -> None:
        """Issues tracked in _active_review_issues are included."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {}
        orch._active_review_issues = {77}

        await orch.stop()

        interrupted = orch._state.get_interrupted_issues()
        assert interrupted[77] == "review"

    @pytest.mark.asyncio
    async def test_stop_empty_active_issues(self, tmp_path: Path) -> None:
        """When no issues are in-flight, interrupted_issues is empty."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {}

        await orch.stop()

        assert orch._state.get_interrupted_issues() == {}

    @pytest.mark.asyncio
    async def test_stop_publishes_status(self, tmp_path: Path) -> None:
        """stop() publishes a status event."""
        orch = _make_orchestrator(tmp_path)
        published = []
        orch._bus.publish = AsyncMock(side_effect=published.append)

        await orch.stop()

        # Should have published at least one status event
        assert any(e.type.value == "orchestrator_status" for e in published)

    @pytest.mark.asyncio
    async def test_stop_sets_stop_event(self, tmp_path: Path) -> None:
        """stop() sets the _stop_event."""
        orch = _make_orchestrator(tmp_path)
        assert not orch._stop_event.is_set()

        await orch.stop()

        assert orch._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_stop_terminates_all_runners(self, tmp_path: Path) -> None:
        """stop() calls terminate on all runner pools."""
        orch = _make_orchestrator(tmp_path)

        await orch.stop()

        orch._planners.terminate.assert_called()
        orch._agents.terminate.assert_called()
        orch._reviewers.terminate.assert_called()
        orch._hitl_runner.terminate.assert_called()


# ---------------------------------------------------------------------------
# Resume / restart tests
# ---------------------------------------------------------------------------


class TestOrchestratorResume:
    """Tests for restoring interrupted issues on restart."""

    @pytest.mark.asyncio
    async def test_restart_removes_plan_issue_from_active_tracking(
        self, tmp_path: Path
    ) -> None:
        """Interrupted plan issue is removed from crash-recovery sets."""
        orch = _make_orchestrator(tmp_path)
        # Simulate crash recovery adding issue to _active_impl_issues
        orch._state.set_active_issue_numbers([42])
        orch._state.set_interrupted_issues({42: "plan"})

        orch._stop_event.set()
        with patch.object(orch, "_supervise_loops", new_callable=AsyncMock):
            await orch.run()

        # Issue should be cleared from active tracking so IssueStore can re-route
        assert 42 not in orch._active_impl_issues
        assert 42 not in orch._recovered_issues
        assert orch._state.get_interrupted_issues() == {}

    @pytest.mark.asyncio
    async def test_restart_removes_implement_issue_from_active_tracking(
        self, tmp_path: Path
    ) -> None:
        """Interrupted implement issue is removed from _active_impl_issues."""
        orch = _make_orchestrator(tmp_path)
        orch._state.set_active_issue_numbers([10])
        orch._state.set_interrupted_issues({10: "implement"})

        orch._stop_event.set()
        with patch.object(orch, "_supervise_loops", new_callable=AsyncMock):
            await orch.run()

        assert 10 not in orch._active_impl_issues
        assert 10 not in orch._recovered_issues
        assert orch._state.get_interrupted_issues() == {}

    @pytest.mark.asyncio
    async def test_restart_removes_review_issue_from_active_tracking(
        self, tmp_path: Path
    ) -> None:
        """Interrupted review issue is removed from all active tracking sets."""
        orch = _make_orchestrator(tmp_path)
        orch._state.set_active_issue_numbers([99])
        orch._state.set_interrupted_issues({99: "review"})

        orch._stop_event.set()
        with patch.object(orch, "_supervise_loops", new_callable=AsyncMock):
            await orch.run()

        assert 99 not in orch._active_impl_issues
        assert 99 not in orch._active_review_issues
        assert 99 not in orch._recovered_issues
        assert orch._state.get_interrupted_issues() == {}

    @pytest.mark.asyncio
    async def test_restart_removes_hitl_issue_from_active_tracking(
        self, tmp_path: Path
    ) -> None:
        """Interrupted HITL issue is removed from hitl_phase active set."""
        orch = _make_orchestrator(tmp_path)
        orch._state.set_active_issue_numbers([33])
        orch._state.set_interrupted_issues({33: "hitl"})

        orch._stop_event.set()
        with patch.object(orch, "_supervise_loops", new_callable=AsyncMock):
            await orch.run()

        assert 33 not in orch._active_impl_issues
        assert 33 not in orch._hitl_phase.active_hitl_issues
        assert orch._state.get_interrupted_issues() == {}

    @pytest.mark.asyncio
    async def test_restart_clears_all_interrupted_issues_from_tracking(
        self, tmp_path: Path
    ) -> None:
        """Multiple interrupted issues across phases are all unblocked."""
        orch = _make_orchestrator(tmp_path)
        orch._state.set_active_issue_numbers([1, 2, 3])
        orch._state.set_interrupted_issues({1: "plan", 2: "implement", 3: "review"})

        orch._stop_event.set()
        with patch.object(orch, "_supervise_loops", new_callable=AsyncMock):
            await orch.run()

        # All interrupted issues must be removed from active tracking
        assert not orch._active_impl_issues & {1, 2, 3}
        assert not orch._active_review_issues & {1, 2, 3}
        assert not orch._recovered_issues & {1, 2, 3}
        assert orch._state.get_interrupted_issues() == {}

    @pytest.mark.asyncio
    async def test_restart_non_interrupted_recovered_issues_keep_grace_period(
        self, tmp_path: Path
    ) -> None:
        """Crash-recovered issues NOT in interrupted_issues keep their grace period."""
        orch = _make_orchestrator(tmp_path)
        # Issue 42 was interrupted; issue 77 was just crash-recovered
        orch._state.set_active_issue_numbers([42, 77])
        orch._state.set_interrupted_issues({42: "implement"})

        orch._stop_event.set()
        with patch.object(orch, "_supervise_loops", new_callable=AsyncMock):
            await orch.run()

        # Issue 42 unblocked; issue 77 still in grace period
        assert 42 not in orch._active_impl_issues
        assert 77 in orch._active_impl_issues


# ---------------------------------------------------------------------------
# Reset tests
# ---------------------------------------------------------------------------


class TestOrchestratorReset:
    """Tests for reset() clearing interrupted issues."""

    def test_reset_clears_interrupted_issues(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch._state.set_interrupted_issues({42: "implement"})

        orch.reset()

        assert orch._state.get_interrupted_issues() == {}


# ---------------------------------------------------------------------------
# Worktree preservation tests
# ---------------------------------------------------------------------------


class TestWorktreePreservation:
    """Tests for preserving worktrees when stop is requested."""

    @pytest.mark.asyncio
    async def test_review_phase_skips_worktree_cleanup_on_stop(self, config) -> None:
        """_review_one_inner() skips worktree cleanup for interrupted (not merged) reviews."""
        from models import ReviewVerdict

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # COMMENT verdict: no merge happens (result.merged stays False).
        # Stop event is set DURING the review → the stop-specific guard at the
        # end of _review_one_inner should preserve the worktree.
        result = ReviewResultFactory.create(verdict=ReviewVerdict.COMMENT)

        async def _review_and_stop(*_args, **_kwargs):
            phase._stop_event.set()  # Set stop while review is in-flight
            return result

        phase._reviewers.review = AsyncMock(side_effect=_review_and_stop)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.get_pr_diff_names = AsyncMock(return_value=[])
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()
        phase._prs.swap_pipeline_labels = AsyncMock()
        phase._prs.pull_main = AsyncMock()

        # Create worktree path
        wt = config.worktree_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Worktree cleanup should NOT be called — review was interrupted (not merged)
        phase._worktrees.post_work_cleanup.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_phase_cleans_worktree_for_merged_pr_with_stop(
        self, config
    ) -> None:
        """Worktree IS cleaned up when a PR was already merged, even if stop is set.

        A merged review is not "interrupted" — preserving its worktree would
        create stale artifacts (the branch no longer exists on the remote).
        """
        from models import ReviewVerdict

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = ReviewResultFactory.create(verdict=ReviewVerdict.APPROVE)
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.get_pr_diff_names = AsyncMock(return_value=[])
        phase._prs.push_branch = AsyncMock(return_value=True)

        async def _merge_and_stop(_pr_number: int) -> bool:
            # Stop arrives while merge is in-flight — merged PR should still
            # have its worktree cleaned up (not "preserved" for resume).
            phase._stop_event.set()
            return True

        phase._prs.merge_pr = AsyncMock(side_effect=_merge_and_stop)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()
        phase._prs.swap_pipeline_labels = AsyncMock()
        phase._prs.pull_main = AsyncMock()

        wt = config.worktree_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Worktree SHOULD be cleaned up — merge completed, nothing to resume
        phase._worktrees.post_work_cleanup.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_review_phase_cleans_worktree_when_not_stopped(self, config) -> None:
        """Worktree cleanup happens normally when stop is not requested."""
        from models import ReviewVerdict

        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = ReviewResultFactory.create(verdict=ReviewVerdict.APPROVE)
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.get_pr_diff_names = AsyncMock(return_value=[])
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()
        phase._prs.swap_pipeline_labels = AsyncMock()
        phase._prs.pull_main = AsyncMock()

        wt = config.worktree_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        # Stop event is NOT set
        await phase.review_prs([pr], [issue])

        # Worktree cleanup should be called normally
        phase._worktrees.post_work_cleanup.assert_awaited_once_with(42)


# ---------------------------------------------------------------------------
# Review phase stop tests
# ---------------------------------------------------------------------------


class TestReviewPhaseStop:
    """Tests for review_prs cancellation on stop."""

    @pytest.mark.asyncio
    async def test_review_prs_cancels_remaining_on_stop(self, config) -> None:
        """Setting stop_event mid-review cancels remaining PR reviews."""
        from models import ReviewVerdict

        phase = make_review_phase(config)
        pr1 = PRInfoFactory.create(number=101, issue_number=10)
        pr2 = PRInfoFactory.create(number=102, issue_number=20)
        issue1 = TaskFactory.create(id=10)
        issue2 = TaskFactory.create(id=20)

        call_count = 0

        async def _review_side_effect(
            pr, _issue, _wt_path, _diff, worker_id=0, **_kwargs
        ):
            nonlocal call_count
            call_count += 1
            # Set stop after first review completes
            phase._stop_event.set()
            return ReviewResultFactory.create(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                verdict=ReviewVerdict.APPROVE,
            )

        phase._reviewers.review = AsyncMock(side_effect=_review_side_effect)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.get_pr_diff_names = AsyncMock(return_value=[])
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()
        phase._prs.swap_pipeline_labels = AsyncMock()

        # Create worktree paths
        for num in (10, 20):
            (config.worktree_base / f"issue-{num}").mkdir(parents=True, exist_ok=True)

        results = await phase.review_prs([pr1, pr2], [issue1, issue2])

        # Exactly one review ran; the second was cancelled after stop was set
        assert call_count == 1
        assert len(results) == 1


# ---------------------------------------------------------------------------
# _build_interrupted_issues tests
# ---------------------------------------------------------------------------


class TestBuildInterruptedIssues:
    """Tests for the _build_interrupted_issues helper."""

    @pytest.mark.asyncio
    async def test_combines_store_and_memory_tracking(self, tmp_path: Path) -> None:
        """Merges IssueStore active + in-memory tracking sets."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {42: "implement"}
        orch._active_review_issues = {99}

        result = await orch._build_interrupted_issues()

        assert result == {42: "implement", 99: "review"}

    @pytest.mark.asyncio
    async def test_store_takes_precedence(self, tmp_path: Path) -> None:
        """If an issue is in both store and memory, store value is used."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {42: "review"}
        orch._active_impl_issues = {42}  # Also tracked here

        result = await orch._build_interrupted_issues()

        # Store value takes precedence
        assert result[42] == "review"

    @pytest.mark.asyncio
    async def test_includes_hitl_issues(self, tmp_path: Path) -> None:
        """HITL issues are captured."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {}
        orch._hitl_phase.active_hitl_issues = {33}

        result = await orch._build_interrupted_issues()

        assert result[33] == "hitl"

    @pytest.mark.asyncio
    async def test_empty_when_no_active(self, tmp_path: Path) -> None:
        """Returns empty dict when nothing is active."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_active_issues.return_value = {}

        assert await orch._build_interrupted_issues() == {}


# ---------------------------------------------------------------------------
# supervise_loops stores tasks on self
# ---------------------------------------------------------------------------


class TestSuperviseLoopsTaskStorage:
    """Tests that _supervise_loops stores tasks on self._loop_tasks."""

    @pytest.mark.asyncio
    async def test_loop_tasks_populated_via_stop(self, tmp_path: Path) -> None:
        """stop() can cancel loop tasks that were stored by _supervise_loops."""
        orch = _make_orchestrator(tmp_path)

        # Verify _loop_tasks starts empty
        assert orch._loop_tasks == {}

        # After stop(), _loop_tasks should still be empty since no run() was called
        await orch.stop()

        # But if we set them manually, stop cancels them
        async def _forever():
            await asyncio.sleep(3600)

        task = asyncio.create_task(_forever())
        orch._loop_tasks = {"test": task}
        orch._stop_event.clear()

        await orch.stop()
        await asyncio.sleep(0)

        assert task.cancelled()


# ---------------------------------------------------------------------------
# External cancellation propagation tests (try/finally fix — memory #819)
# ---------------------------------------------------------------------------


class TestExternalCancellationPattern:
    """Verify the try/finally pattern cancels inner tasks on external CancelledError.

    Memory note #819: inner tasks created by asyncio.create_task inside an
    as_completed loop are NOT automatically cancelled when the outer coroutine
    receives CancelledError. The try/finally block in plan/implement/review phases
    is the fix — this class tests that the fix works.
    """

    @pytest.mark.asyncio
    async def test_finally_cancels_inner_tasks_on_external_cancel(self) -> None:
        """Outer coroutine cancellation propagates to inner tasks via finally block."""
        inner_cancelled = asyncio.Event()

        async def inner_task() -> None:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                inner_cancelled.set()
                raise

        async def outer_with_finally() -> list[None]:
            """Mirrors the try/finally pattern used in plan/implement/review phases."""
            tasks = [asyncio.create_task(inner_task())]
            results: list[None] = []
            try:
                for task in asyncio.as_completed(tasks):
                    results.append(await task)
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()
            return results

        outer = asyncio.create_task(outer_with_finally())
        await asyncio.sleep(0)  # Let inner_task start

        # Cancel the outer coroutine — mimicking stop() cancelling a loop task
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer

        await asyncio.sleep(0)  # Allow cancellation to propagate to inner_task
        assert inner_cancelled.is_set(), (
            "Inner task was not cancelled — the try/finally block in "
            "plan/implement/review phases is required to propagate CancelledError "
            "to tasks created inside as_completed loops (see memory note #819)"
        )

    @pytest.mark.asyncio
    async def test_without_finally_inner_tasks_are_orphaned(self) -> None:
        """Without try/finally, cancelled outer leaves inner tasks running (the bug)."""
        inner_cancelled = asyncio.Event()
        inner_started = asyncio.Event()

        async def inner_task() -> None:
            inner_started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                inner_cancelled.set()
                raise

        async def outer_without_finally() -> list[None]:
            """Original broken pattern WITHOUT try/finally — for documentation."""
            tasks = [asyncio.create_task(inner_task())]
            results: list[None] = []
            for task in asyncio.as_completed(tasks):
                results.append(await task)  # CancelledError propagates here
            return results

        outer = asyncio.create_task(outer_without_finally())
        await asyncio.wait_for(inner_started.wait(), timeout=1.0)

        # Cancel the outer coroutine
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer

        await asyncio.sleep(0)
        # Without try/finally, the inner task is orphaned (not cancelled)
        assert not inner_cancelled.is_set(), (
            "Expected inner task to be orphaned without try/finally — "
            "this confirms why the fix (try/finally) is necessary"
        )
