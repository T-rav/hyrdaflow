"""Tests for dx/hydraflow/orchestrator.py - Phase loops, HITL, exceptions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

from events import EventBus, EventType

if TYPE_CHECKING:
    from config import HydraFlowConfig
from models import (
    GitHubIssue,
    PlanResult,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    Task,
    WorkerResult,
)
from orchestrator import HydraFlowOrchestrator
from subprocess_util import AuthenticationError
from tests.conftest import TaskFactory, WorkerResultFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_fetcher_noop(orch: HydraFlowOrchestrator) -> None:
    """Mock store and fetcher methods so no real gh CLI calls are made."""
    orch._store.get_triageable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.get_plannable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.get_reviewable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.start = AsyncMock()  # type: ignore[method-assign]
    orch._store.get_active_issues = lambda: {}  # type: ignore[method-assign]
    orch._fetcher.fetch_issue_by_number = AsyncMock(return_value=None)  # type: ignore[method-assign]
    orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
    orch._enable_rerere = AsyncMock()  # type: ignore[method-assign]
    orch._worktrees.sanitize_repo = AsyncMock()  # type: ignore[method-assign]


def make_worker_result(
    issue_number: int = 42,
    branch: str = "agent/issue-42",
    success: bool = True,
    worktree_path: str = "/tmp/worktrees/issue-42",
    transcript: str = "Implemented the feature.",
) -> WorkerResult:
    return WorkerResultFactory.create(
        issue_number=issue_number,
        branch=branch,
        success=success,
        transcript=transcript,
        commits=1,
        worktree_path=worktree_path,
        use_defaults=True,
    )


def make_review_result(
    pr_number: int = 101,
    issue_number: int = 42,
    verdict: ReviewVerdict = ReviewVerdict.APPROVE,
    transcript: str = "",
) -> ReviewResult:
    return ReviewResult(
        pr_number=pr_number,
        issue_number=issue_number,
        verdict=verdict,
        summary="Looks good.",
        fixes_made=False,
        transcript=transcript,
    )


# ---------------------------------------------------------------------------
# Manifest refresh loop integration
# ---------------------------------------------------------------------------


class TestManifestRefreshIntegration:
    """Tests for manifest refresh loop wired into the orchestrator."""

    def test_manifest_refresh_loop_exists(self, config: HydraFlowConfig) -> None:
        """Orchestrator should have a _manifest_refresh_loop attribute."""
        from manifest_refresh_loop import ManifestRefreshLoop

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._manifest_refresh_loop, ManifestRefreshLoop)

    def test_manifest_refresh_bg_loop_method_exists(
        self, config: HydraFlowConfig
    ) -> None:
        """Orchestrator should have a _manifest_refresh_bg_loop async method."""
        orch = HydraFlowOrchestrator(config)
        assert hasattr(orch, "_manifest_refresh_bg_loop")
        assert asyncio.iscoroutinefunction(orch._manifest_refresh_bg_loop)

    @pytest.mark.asyncio
    async def test_manifest_refresh_loop_runs_in_supervisor(
        self, config: HydraFlowConfig
    ) -> None:
        """The manifest refresh loop should run as part of _supervise_loops."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        manifest_ran = False

        async def tracking_manifest_loop() -> None:
            nonlocal manifest_ran
            manifest_ran = True
            orch._stop_event.set()

        orch._manifest_refresh_bg_loop = tracking_manifest_loop  # type: ignore[method-assign]
        orch._triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert manifest_ran

    def test_get_bg_worker_interval_returns_manifest_interval(
        self, config: HydraFlowConfig
    ) -> None:
        """get_bg_worker_interval should return manifest_refresh_interval."""
        orch = HydraFlowOrchestrator(config)
        assert (
            orch.get_bg_worker_interval("manifest_refresh")
            == config.manifest_refresh_interval
        )


# ---------------------------------------------------------------------------
# HITL correction tracking
# ---------------------------------------------------------------------------


class TestHITLCorrection:
    """Tests for HITL correction methods on HydraFlowOrchestrator."""

    def test_hitl_corrections_starts_empty(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch._hitl_corrections == {}

    def test_submit_hitl_correction_stores_correction(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.submit_hitl_correction(42, "Mock the database connection")
        assert orch._hitl_corrections[42] == "Mock the database connection"

    def test_submit_hitl_correction_overwrites_previous(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.submit_hitl_correction(42, "First attempt")
        orch.submit_hitl_correction(42, "Second attempt")
        assert orch._hitl_corrections[42] == "Second attempt"

    def test_get_hitl_status_returns_pending_by_default(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.get_hitl_status(42) == "pending"

    def test_get_hitl_status_returns_processing_when_active_in_store(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._store.mark_active(42, "implement")
        assert orch.get_hitl_status(42) == "processing"

    def test_get_hitl_status_returns_processing_when_active_in_review_store(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._store.mark_active(42, "review")
        assert orch.get_hitl_status(42) == "processing"

    def test_get_hitl_status_returns_processing_when_active_in_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._active_hitl_issues.add(42)
        assert orch.get_hitl_status(42) == "processing"

    def test_get_hitl_status_returns_pending_when_not_active(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._store.mark_active(99, "implement")
        assert orch.get_hitl_status(42) == "pending"

    @pytest.mark.parametrize(
        "label, expected",
        [
            ("hydraflow-find", "from triage"),
            ("hydraflow-plan", "from plan"),
            ("hydraflow-ready", "from implement"),
            ("hydraflow-review", "from review"),
        ],
    )
    def test_get_hitl_status_returns_human_readable_origin(
        self, config: HydraFlowConfig, label: str, expected: str
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._state.set_hitl_origin(42, label)
        assert orch.get_hitl_status(42) == expected

    def test_get_hitl_status_returns_approval_for_improve_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """Memory suggestions use config.improve_label, not a hardcoded string."""
        orch = HydraFlowOrchestrator(config)
        orch._state.set_hitl_origin(42, config.improve_label[0])
        assert orch.get_hitl_status(42) == "approval"

    def test_get_hitl_status_falls_back_to_pending_for_unknown_label(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._state.set_hitl_origin(42, "hydraflow-unknown")
        assert orch.get_hitl_status(42) == "pending"

    def test_get_hitl_status_processing_takes_precedence_over_origin(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._state.set_hitl_origin(42, "hydraflow-review")
        orch._store.mark_active(42, "implement")
        assert orch.get_hitl_status(42) == "processing"

    def test_skip_hitl_issue_removes_correction(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._hitl_corrections[42] = "Some correction"
        orch.skip_hitl_issue(42)
        assert 42 not in orch._hitl_corrections

    def test_skip_hitl_issue_safe_when_no_correction(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.skip_hitl_issue(99)  # Should not raise
        assert 99 not in orch._hitl_corrections


# ---------------------------------------------------------------------------
# Exception isolation — polling loops
# ---------------------------------------------------------------------------


class TestLoopExceptionIsolation:
    """Each polling loop catches exceptions per-iteration and continues."""

    @pytest.mark.asyncio
    async def test_triage_loop_continues_after_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """An exception in triage_issues should not crash the triage loop."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def failing_triage() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("triage boom")
            orch._stop_event.set()

        orch._triager.triage_issues = failing_triage  # type: ignore[method-assign]

        # Run just the triage loop directly
        await orch._triage_loop()

        # Loop ran twice: first call raised, second set stop
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_plan_loop_continues_after_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """An exception in plan_issues should not crash the plan loop."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def failing_plan() -> list[PlanResult]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("plan boom")
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = failing_plan  # type: ignore[method-assign]

        await orch._plan_loop()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_plan_loop_does_not_call_triage(
        self, config: HydraFlowConfig
    ) -> None:
        """_plan_loop should not call triage_issues (handled by _triage_loop)."""
        orch = HydraFlowOrchestrator(config)
        triage_mock = AsyncMock()
        orch._triager.triage_issues = triage_mock  # type: ignore[method-assign]

        call_count = 0

        async def plan_and_stop() -> list[PlanResult]:
            nonlocal call_count
            call_count += 1
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        await orch._plan_loop()

        triage_mock.assert_not_called()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_implement_loop_continues_after_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """An exception in run_batch should not crash the implement loop."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def failing_batch() -> tuple[list[WorkerResult], list[Task]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("implement boom")
            orch._stop_event.set()
            return [], []

        orch._implementer.run_batch = failing_batch  # type: ignore[method-assign]

        await orch._implement_loop()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_review_loop_continues_after_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """An exception in get_reviewable should not crash the review loop."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        def failing_get_reviewable(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("review boom")
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = failing_get_reviewable  # type: ignore[method-assign]

        await orch._review_loop()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_review_loop_no_hot_spin_on_requeued_issues(
        self, config: HydraFlowConfig
    ) -> None:
        """When reviewable issues are re-queued (PR not visible), the loop should
        break out of _do_review_work instead of spinning hot."""
        orch = HydraFlowOrchestrator(config)
        fetch_count = 0

        requeued_task = Task(id=99, title="Test issue", body="")

        def fake_get_reviewable(max_count: int) -> list[Task]:
            nonlocal fetch_count
            fetch_count += 1
            if fetch_count == 1:
                return [requeued_task]
            # On second call the re-queued item would appear again,
            # but the loop should have broken out before getting here.
            return [requeued_task]

        async def fake_review_single(issue: Task) -> bool:
            # Simulate PR not visible — returns False (re-queued)
            return False

        orch._store.get_reviewable = fake_get_reviewable  # type: ignore[method-assign]
        orch._review_single_issue = fake_review_single  # type: ignore[method-assign]

        await orch._do_review_work()

        # Should have fetched once, reviewed once, then broken out —
        # NOT looped back to fetch the re-queued item again.
        assert fetch_count == 1

    @pytest.mark.asyncio
    async def test_error_event_published_on_triage_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """Triage loop exception should publish ERROR event with source=triage."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def failing_triage() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("triage error")
            orch._stop_event.set()

        orch._triager.triage_issues = failing_triage  # type: ignore[method-assign]

        await orch._triage_loop()

        error_events = [e for e in orch._bus.get_history() if e.type == EventType.ERROR]
        assert len(error_events) == 1
        assert error_events[0].data["source"] == "triage"
        assert "Triage loop error" in error_events[0].data["message"]

    @pytest.mark.asyncio
    async def test_error_event_published_on_implement_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """Implement loop exception should publish ERROR event with source=implement."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def failing_batch() -> tuple[list[WorkerResult], list[Task]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("implement error")
            orch._stop_event.set()
            return [], []

        orch._implementer.run_batch = failing_batch  # type: ignore[method-assign]

        await orch._implement_loop()

        error_events = [e for e in orch._bus.get_history() if e.type == EventType.ERROR]
        assert len(error_events) == 1
        assert error_events[0].data["source"] == "implement"

    @pytest.mark.asyncio
    async def test_error_event_published_on_review_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """Review loop exception should publish ERROR event with source=review."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        def failing_get_reviewable(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("review error")
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = failing_get_reviewable  # type: ignore[method-assign]

        await orch._review_loop()

        error_events = [e for e in orch._bus.get_history() if e.type == EventType.ERROR]
        assert len(error_events) == 1
        assert error_events[0].data["source"] == "review"

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_through_loop(
        self, config: HydraFlowConfig
    ) -> None:
        """CancelledError should NOT be caught — it propagates for clean shutdown."""
        orch = HydraFlowOrchestrator(config)

        async def cancelling_batch() -> tuple[list[WorkerResult], list[Task]]:
            raise asyncio.CancelledError()

        orch._implementer.run_batch = cancelling_batch  # type: ignore[method-assign]

        with pytest.raises(asyncio.CancelledError):
            await orch._implement_loop()


# ---------------------------------------------------------------------------
# Exception isolation — supervisor
# ---------------------------------------------------------------------------


class TestSupervisorLoops:
    """Tests for the _supervise_loops supervisor that restarts crashed loops."""

    @pytest.mark.asyncio
    async def test_run_completes_normally_with_stop(
        self, config: HydraFlowConfig
    ) -> None:
        """run() should complete normally when stop is set, even with supervisor."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert not orch.running

    @pytest.mark.asyncio
    async def test_exception_in_one_loop_does_not_stop_others(
        self, config: HydraFlowConfig
    ) -> None:
        """If one loop crashes despite try/except, others should keep running."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        orch._enable_rerere = AsyncMock()  # type: ignore[method-assign]
        orch._worktrees.sanitize_repo = AsyncMock()  # type: ignore[method-assign]

        implement_calls = 0

        async def failing_implement() -> tuple[list[WorkerResult], list[Task]]:
            nonlocal implement_calls
            implement_calls += 1
            if implement_calls == 1:
                raise RuntimeError("implement crash")
            orch._stop_event.set()
            return [], []

        orch._triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = failing_implement  # type: ignore[method-assign]
        orch._store.get_reviewable = lambda _max_count: []  # type: ignore[method-assign]
        orch._store.start = AsyncMock()  # type: ignore[method-assign]

        # Use instant sleep to avoid 30s poll_interval delays
        async def instant_sleep(seconds: int) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        await orch.run()

        # The implement loop continued after the error (ran at least twice)
        assert implement_calls >= 2
        assert not orch.running

    @pytest.mark.asyncio
    async def test_supervise_loops_restarts_loop_that_completes_normally(
        self, config: HydraFlowConfig
    ) -> None:
        """A loop that completes normally (no exception) is restarted with a warning."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        implement_calls = 0

        async def completing_then_stopping() -> None:
            nonlocal implement_calls
            implement_calls += 1
            if implement_calls == 1:
                # Complete normally — triggers the else branch in _supervise_loops
                return
            # Second invocation: stop the orchestrator
            orch._stop_event.set()

        # Replace the actual loop method (not the inner work fn) so the
        # supervised task completes normally from _supervise_loops' perspective.
        orch._implement_loop = completing_then_stopping  # type: ignore[method-assign]

        orch._triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._store.get_reviewable = lambda _max_count: []  # type: ignore[method-assign]
        orch._store.start = AsyncMock()  # type: ignore[method-assign]

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        with patch("orchestrator.logger") as mock_logger:
            await orch.run()

        # The implement loop was restarted after normal completion (ran at least twice)
        assert implement_calls >= 2
        mock_logger.warning.assert_any_call(
            "Loop %r completed unexpectedly — restarting", "implement"
        )


# ---------------------------------------------------------------------------
# Phase-specific active issue sets
# ---------------------------------------------------------------------------


class TestStoreBasedActiveIssueTracking:
    """Tests that active issue tracking uses the centralized IssueStore."""

    def test_implementer_receives_store(self, config: HydraFlowConfig) -> None:
        """ImplementPhase receives the shared IssueStore."""
        orch = HydraFlowOrchestrator(config)
        assert orch._implementer._store is orch._store

    def test_reviewer_receives_store(self, config: HydraFlowConfig) -> None:
        """ReviewPhase receives the shared IssueStore."""
        orch = HydraFlowOrchestrator(config)
        assert orch._reviewer._store is orch._store

    def test_implementer_and_reviewer_share_same_store(
        self, config: HydraFlowConfig
    ) -> None:
        """Both phases share the same IssueStore instance."""
        orch = HydraFlowOrchestrator(config)
        assert orch._implementer._store is orch._reviewer._store

    def test_reset_clears_store_active_and_hitl(self, config: HydraFlowConfig) -> None:
        """reset() must clear store active tracking and HITL issues."""
        orch = HydraFlowOrchestrator(config)
        orch._store.mark_active(1, "implement")
        orch._store.mark_active(2, "review")
        orch._active_hitl_issues.add(3)
        orch.reset()
        assert not orch._store.is_active(1)
        assert not orch._store.is_active(2)
        assert len(orch._active_hitl_issues) == 0

    @pytest.mark.asyncio
    async def test_review_loop_passes_store_active_to_fetcher(
        self, config: HydraFlowConfig
    ) -> None:
        """_review_loop should pass store active issues to fetch_reviewable_prs."""
        orch = HydraFlowOrchestrator(config)
        review_issue = TaskFactory.create(id=42)
        captured_active: set[int] | None = None

        orch._store.get_reviewable = lambda _max_count: [review_issue]  # type: ignore[method-assign]
        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]

        async def capturing_fetch(
            active: set[int],
            prefetched_issues: object = None,
        ) -> tuple[list[PRInfo], list[GitHubIssue]]:
            nonlocal captured_active
            captured_active = active
            orch._stop_event.set()
            return [], []

        orch._fetcher.fetch_reviewable_prs = capturing_fetch  # type: ignore[method-assign]
        await orch._review_loop()

        assert captured_active == {42}

    def test_store_active_tracking_is_unified(self, config: HydraFlowConfig) -> None:
        """Marking an issue active in one stage is visible to all phases."""
        orch = HydraFlowOrchestrator(config)
        orch._store.mark_active(100, "implement")

        # The same store is shared, so is_active works from anywhere
        assert orch._store.is_active(100)
        # Marking complete removes it
        orch._store.mark_complete(100)
        assert not orch._store.is_active(100)


# ---------------------------------------------------------------------------
# HITL loop
# ---------------------------------------------------------------------------


class TestHITLLoop:
    """Tests for the HITL correction loop in the orchestrator."""

    def test_hitl_runner_is_created_in_init(self, config: HydraFlowConfig) -> None:
        from hitl_runner import HITLRunner

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._hitl_runner, HITLRunner)

    def test_hitl_loop_in_loop_factories(self, config: HydraFlowConfig) -> None:
        """The hitl loop should be listed in _supervise_loops."""
        orch = HydraFlowOrchestrator(config)
        # Verify the loop method exists
        assert hasattr(orch, "_hitl_loop")
        assert asyncio.iscoroutinefunction(orch._hitl_loop)

    @pytest.mark.asyncio
    async def test_hitl_loop_runs_in_supervise_loops(
        self, config: HydraFlowConfig
    ) -> None:
        """The HITL loop should be started by _supervise_loops alongside others."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        hitl_ran = False

        async def tracking_hitl_loop() -> None:
            nonlocal hitl_ran
            hitl_ran = True
            orch._stop_event.set()

        orch._hitl_loop = tracking_hitl_loop  # type: ignore[method-assign]
        orch._triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert hitl_ran

    @pytest.mark.asyncio
    async def test_hitl_loop_continues_after_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """An exception in process_corrections should not crash the loop."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def failing_process() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("hitl boom")
            orch._stop_event.set()

        orch._hitl_phase.process_corrections = failing_process  # type: ignore[method-assign]

        await orch._hitl_loop()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_error_event_published_on_hitl_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """HITL loop exception should publish ERROR event with source=hitl."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def failing_process() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("hitl error")
            orch._stop_event.set()

        orch._hitl_phase.process_corrections = failing_process  # type: ignore[method-assign]

        await orch._hitl_loop()

        error_events = [e for e in orch._bus.get_history() if e.type == EventType.ERROR]
        assert len(error_events) == 1
        assert error_events[0].data["source"] == "hitl"
        assert "Hitl loop error" in error_events[0].data["message"]

    @pytest.mark.asyncio
    async def test_stop_terminates_hitl_runner(self, config: HydraFlowConfig) -> None:
        """stop() should call terminate() on the HITL runner."""
        orch = HydraFlowOrchestrator(config)
        with patch.object(orch._hitl_runner, "terminate") as mock_term:
            await orch.stop()
        mock_term.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_finally_terminates_hitl_runner(
        self, config: HydraFlowConfig
    ) -> None:
        """When run() exits, the HITL runner should be terminated."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        with patch.object(orch._hitl_runner, "terminate") as mock_term:
            await orch.run()

        mock_term.assert_called_once()


# ---------------------------------------------------------------------------
# Auth failure detection
# ---------------------------------------------------------------------------


class TestAuthFailure:
    """Tests for AuthenticationError handling in the orchestrator."""

    @pytest.mark.asyncio
    async def test_auth_failure_stops_all_loops(self, config: HydraFlowConfig) -> None:
        """An AuthenticationError in any loop should stop the orchestrator."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        orch._enable_rerere = AsyncMock()  # type: ignore[method-assign]
        orch._worktrees.sanitize_repo = AsyncMock()  # type: ignore[method-assign]

        async def auth_failing_triage() -> None:
            raise AuthenticationError("401 Unauthorized")

        orch._triager.triage_issues = auth_failing_triage  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        await orch.run()

        assert not orch.running
        assert orch._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_auth_failure_publishes_system_alert_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Auth failure should publish a SYSTEM_ALERT event."""
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        orch._enable_rerere = AsyncMock()  # type: ignore[method-assign]
        orch._worktrees.sanitize_repo = AsyncMock()  # type: ignore[method-assign]

        async def auth_failing_plan() -> list[PlanResult]:
            raise AuthenticationError("401 Unauthorized")

        orch._triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = auth_failing_plan  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        await orch.run()

        alert_events = [
            e for e in event_bus.get_history() if e.type == EventType.SYSTEM_ALERT
        ]
        assert len(alert_events) == 1
        assert "authentication" in alert_events[0].data["message"].lower()
        assert alert_events[0].data["source"] == "plan"

    @pytest.mark.asyncio
    async def test_auth_failure_sets_auth_failed_flag(
        self, config: HydraFlowConfig
    ) -> None:
        """Auth failure should set the _auth_failed flag."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        orch._enable_rerere = AsyncMock()  # type: ignore[method-assign]
        orch._worktrees.sanitize_repo = AsyncMock()  # type: ignore[method-assign]

        async def auth_failing_implement() -> tuple[list[WorkerResult], list[Task]]:
            raise AuthenticationError("401 Unauthorized")

        orch._triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = auth_failing_implement  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        await orch.run()

        assert orch._auth_failed is True

    def test_run_status_returns_auth_failed(self, config: HydraFlowConfig) -> None:
        """run_status should return 'auth_failed' when the flag is set."""
        orch = HydraFlowOrchestrator(config)
        orch._auth_failed = True
        assert orch.run_status == "auth_failed"

    def test_run_status_auth_failed_takes_precedence(
        self, config: HydraFlowConfig
    ) -> None:
        """auth_failed should take precedence over other statuses."""
        orch = HydraFlowOrchestrator(config)
        orch._auth_failed = True
        orch._running = True
        assert orch.run_status == "auth_failed"

    def test_reset_clears_auth_failed(self, config: HydraFlowConfig) -> None:
        """reset() should clear the _auth_failed flag."""
        orch = HydraFlowOrchestrator(config)
        orch._auth_failed = True
        orch._stop_event.set()
        orch.reset()
        assert orch._auth_failed is False
        assert not orch._stop_event.is_set()


# ---------------------------------------------------------------------------
# _handle_loop_exception — extracted from _supervise_loops
# ---------------------------------------------------------------------------


class TestHandleLoopException:
    """Tests for the extracted _handle_loop_exception helper."""

    @pytest.mark.asyncio
    async def test_auth_error_sets_stop_and_flag(self, config: HydraFlowConfig) -> None:
        """AuthenticationError should set _auth_failed and stop_event."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)
        tasks: dict[str, asyncio.Task[None]] = {}
        factories: list = []

        await orch._handle_loop_exception(
            "plan", AuthenticationError("401"), tasks, factories
        )

        assert orch._auth_failed is True
        assert orch._stop_event.is_set()
        alerts = [e for e in bus.get_history() if e.type == EventType.SYSTEM_ALERT]
        assert len(alerts) == 1
        assert "authentication" in alerts[0].data["message"].lower()

    @pytest.mark.asyncio
    async def test_credit_error_delegates_to_pause(
        self, config: HydraFlowConfig
    ) -> None:
        """CreditExhaustedError should delegate to _pause_for_credits."""
        from subprocess_util import CreditExhaustedError

        orch = HydraFlowOrchestrator(config)
        orch._pause_for_credits = AsyncMock()  # type: ignore[method-assign]
        tasks: dict[str, asyncio.Task[None]] = {}
        factories: list = [("plan", AsyncMock())]
        exc = CreditExhaustedError("limit reached")

        await orch._handle_loop_exception("plan", exc, tasks, factories)

        orch._pause_for_credits.assert_awaited_once_with(exc, "plan", tasks, factories)

    @pytest.mark.asyncio
    async def test_generic_error_restarts_loop(self, config: HydraFlowConfig) -> None:
        """Generic exception should restart the crashed loop task."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)
        tasks: dict[str, asyncio.Task[None]] = {}

        async def dummy_loop() -> None:
            await asyncio.sleep(100)

        factories: list = [("plan", dummy_loop)]

        await orch._handle_loop_exception(
            "plan", RuntimeError("boom"), tasks, factories
        )

        assert "plan" in tasks
        assert not tasks["plan"].done()
        tasks["plan"].cancel()
        error_events = [e for e in bus.get_history() if e.type == EventType.ERROR]
        assert len(error_events) == 1
        assert "plan" in error_events[0].data["source"]
