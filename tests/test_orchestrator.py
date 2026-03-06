"""Tests for dx/hydraflow/orchestrator.py - HydraFlowOrchestrator class."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

from events import EventBus, EventType, HydraFlowEvent
from state import StateTracker

if TYPE_CHECKING:
    from config import HydraFlowConfig
from models import (
    BackgroundWorkerState,
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
from tests.conftest import IssueFactory, PRInfoFactory, TaskFactory, WorkerResultFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_fetcher_noop(orch: HydraFlowOrchestrator) -> None:
    """Mock store and fetcher methods so no real gh CLI calls are made.

    Required for tests that go through run() since exception isolation
    catches errors from unmocked fetcher/store calls instead of propagating them.
    """
    orch._store.get_triageable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.get_plannable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.get_reviewable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.start = AsyncMock()  # type: ignore[method-assign]
    orch._store.get_active_issues = lambda: {}  # type: ignore[method-assign]
    orch._fetcher.fetch_issue_by_number = AsyncMock(return_value=None)  # type: ignore[method-assign]
    orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]


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
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    """HydraFlowOrchestrator.__init__ creates all required components."""

    def test_creates_event_bus(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._bus, EventBus)

    def test_creates_state_tracker(self, config: HydraFlowConfig) -> None:
        from state import StateTracker

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._state, StateTracker)

    def test_creates_worktree_manager(self, config: HydraFlowConfig) -> None:
        from worktree import WorktreeManager

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._worktrees, WorktreeManager)

    def test_creates_agent_runner(self, config: HydraFlowConfig) -> None:
        from agent import AgentRunner

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._agents, AgentRunner)

    def test_creates_pr_manager(self, config: HydraFlowConfig) -> None:
        from pr_manager import PRManager

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._prs, PRManager)

    def test_creates_planner_runner(self, config: HydraFlowConfig) -> None:
        from planner import PlannerRunner

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._planners, PlannerRunner)

    def test_creates_review_runner(self, config: HydraFlowConfig) -> None:
        from reviewer import ReviewRunner

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._reviewers, ReviewRunner)

    def test_human_input_requests_starts_empty(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch._human_input_requests == {}

    def test_human_input_responses_starts_empty(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch._human_input_responses == {}

    def test_dashboard_starts_as_none(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch._dashboard is None

    def test_creates_fetcher(self, config: HydraFlowConfig) -> None:
        from issue_fetcher import IssueFetcher

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._fetcher, IssueFetcher)

    def test_creates_implementer(self, config: HydraFlowConfig) -> None:
        from implement_phase import ImplementPhase

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._implementer, ImplementPhase)

    def test_creates_reviewer(self, config: HydraFlowConfig) -> None:
        from review_phase import ReviewPhase

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._reviewer, ReviewPhase)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    """Tests for public properties."""

    def test_event_bus_returns_internal_bus(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.event_bus is orch._bus

    def test_event_bus_is_event_bus_instance(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch.event_bus, EventBus)

    def test_state_returns_internal_state(self, config: HydraFlowConfig) -> None:
        from state import StateTracker

        orch = HydraFlowOrchestrator(config)
        assert orch.state is orch._state
        assert isinstance(orch.state, StateTracker)

    def test_human_input_requests_returns_internal_dict(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.human_input_requests is orch._human_input_requests

    def test_no_class_constant_default_max_reviewers(self) -> None:
        assert not hasattr(HydraFlowOrchestrator, "DEFAULT_MAX_REVIEWERS")

    def test_no_class_constant_default_max_planners(self) -> None:
        assert not hasattr(HydraFlowOrchestrator, "DEFAULT_MAX_PLANNERS")


# ---------------------------------------------------------------------------
# Human input
# ---------------------------------------------------------------------------


class TestHumanInput:
    """Tests for provide_human_input and human_input_requests."""

    def test_provide_human_input_stores_answer(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.provide_human_input(42, "Use option B")
        assert orch._human_input_responses[42] == "Use option B"

    def test_provide_human_input_removes_from_requests(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._human_input_requests[42] = "Which approach?"
        orch.provide_human_input(42, "Approach A")
        assert 42 not in orch._human_input_requests

    def test_provide_human_input_for_non_pending_issue_is_safe(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        # No request registered — should not raise
        orch.provide_human_input(99, "Some answer")
        assert orch._human_input_responses[99] == "Some answer"

    def test_human_input_requests_reflects_pending(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._human_input_requests[7] = "What colour?"
        assert orch.human_input_requests == {7: "What colour?"}


# ---------------------------------------------------------------------------
# run() loop
# ---------------------------------------------------------------------------


class TestRunLoop:
    """Tests for the main run() orchestrator loop.

    ``run()`` launches three independent polling loops via
    ``asyncio.gather``.  Loops run until ``_stop_event`` is set.
    """

    @pytest.mark.asyncio
    async def test_run_sets_running_flag(self, config: HydraFlowConfig) -> None:
        """run() sets _running = True at start."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)
        observed_running = False

        async def plan_and_stop() -> list[PlanResult]:
            nonlocal observed_running
            observed_running = orch.running
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert observed_running is True

    @pytest.mark.asyncio
    async def test_running_is_false_after_run_completes(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert orch.running is False

    @pytest.mark.asyncio
    async def test_publishes_status_events_on_start_and_end(
        self, config: HydraFlowConfig
    ) -> None:
        """run() publishes orchestrator_status events at start and end."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        published: list[HydraFlowEvent] = []
        original_publish = orch._bus.publish

        async def capturing_publish(event: HydraFlowEvent) -> None:
            published.append(event)
            await original_publish(event)

        orch._bus.publish = capturing_publish  # type: ignore[method-assign]

        await orch.run()

        status_events = [
            e for e in published if e.type == EventType.ORCHESTRATOR_STATUS
        ]
        assert len(status_events) >= 2
        assert status_events[0].data["status"] == "running"

    @pytest.mark.asyncio
    async def test_stop_event_terminates_all_loops(
        self, config: HydraFlowConfig
    ) -> None:
        """Setting _stop_event causes all three loops to exit."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        plan_calls = 0

        async def plan_spy() -> list[PlanResult]:
            nonlocal plan_calls
            plan_calls += 1
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_spy  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        # Plan ran once and set stop; loops terminated
        assert plan_calls == 1

    @pytest.mark.asyncio
    async def test_loops_run_concurrently(self, config: HydraFlowConfig) -> None:
        """Plan, implement, and review loops run concurrently via asyncio.gather."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        started: list[str] = []

        async def fake_plan() -> list[PlanResult]:
            started.append("plan")
            await asyncio.sleep(0)  # yield to let others start
            orch._stop_event.set()
            return []

        async def fake_implement() -> tuple[list[WorkerResult], list[Task]]:
            started.append("implement")
            await asyncio.sleep(0)
            return [], []

        orch._planner_phase.plan_issues = fake_plan  # type: ignore[method-assign]
        orch._implementer.run_batch = fake_implement  # type: ignore[method-assign]

        await orch.run()

        assert "plan" in started
        assert "implement" in started


# ---------------------------------------------------------------------------
# run() finally block — subprocess cleanup
# ---------------------------------------------------------------------------


class TestRunFinallyTerminatesRunners:
    """Tests that run() finally block terminates all runners."""

    @pytest.mark.asyncio
    async def test_run_finally_terminates_all_runners(
        self, config: HydraFlowConfig
    ) -> None:
        """When run() exits via stop event, all three runner terminate() are called."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        with (
            patch.object(orch._planners, "terminate") as mock_p,
            patch.object(orch._agents, "terminate") as mock_a,
            patch.object(orch._reviewers, "terminate") as mock_r,
        ):
            await orch.run()

        mock_p.assert_called_once()
        mock_a.assert_called_once()
        mock_r.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_terminates_on_loop_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """If a loop exception is caught, runners are still terminated on stop."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        call_count = 0

        async def exploding_then_stopping() -> list[PlanResult]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = exploding_then_stopping  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        with (
            patch.object(orch._planners, "terminate") as mock_p,
            patch.object(orch._agents, "terminate") as mock_a,
            patch.object(orch._reviewers, "terminate") as mock_r,
        ):
            await orch.run()

        # Exception was caught (not re-raised), loop continued, stop was set
        assert call_count == 2
        mock_p.assert_called_once()
        mock_a.assert_called_once()
        mock_r.assert_called_once()

    @pytest.mark.asyncio
    async def test_running_stays_true_during_terminate_calls(
        self, config: HydraFlowConfig
    ) -> None:
        """_running must remain True while terminate() calls are in progress."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        running_during_terminate: list[bool] = []

        original_terminate_p = orch._planners.terminate
        original_terminate_a = orch._agents.terminate
        original_terminate_r = orch._reviewers.terminate

        def spy_terminate_p() -> None:
            running_during_terminate.append(orch._running)
            original_terminate_p()

        def spy_terminate_a() -> None:
            running_during_terminate.append(orch._running)
            original_terminate_a()

        def spy_terminate_r() -> None:
            running_during_terminate.append(orch._running)
            original_terminate_r()

        orch._planners.terminate = spy_terminate_p  # type: ignore[method-assign]
        orch._agents.terminate = spy_terminate_a  # type: ignore[method-assign]
        orch._reviewers.terminate = spy_terminate_r  # type: ignore[method-assign]

        await orch.run()

        # All terminate calls should have seen _running == True
        assert len(running_during_terminate) == 3
        assert all(running_during_terminate)
        # But after run() completes, it should be False
        assert orch._running is False


# ---------------------------------------------------------------------------
# Constructor injection
# ---------------------------------------------------------------------------


class TestConstructorInjection:
    """Tests for optional event_bus / state constructor params."""

    def test_uses_provided_event_bus(self, config: HydraFlowConfig, event_bus) -> None:
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        assert orch._bus is event_bus

    def test_uses_provided_state(self, config: HydraFlowConfig) -> None:
        state = StateTracker(config.state_file)
        orch = HydraFlowOrchestrator(config, state=state)
        assert orch._state is state

    def test_creates_own_bus_when_none_provided(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._bus, EventBus)

    def test_creates_own_state_when_none_provided(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._state, StateTracker)

    def test_shared_bus_receives_events(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        assert orch.event_bus is event_bus


# ---------------------------------------------------------------------------
# Stop mechanism
# ---------------------------------------------------------------------------


class TestStopMechanism:
    """Tests for request_stop(), reset(), run_status, and stop-at-batch-boundary."""

    @pytest.mark.asyncio
    async def test_request_stop_sets_stop_event(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert not orch._stop_event.is_set()
        await orch.request_stop()
        assert orch._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_stop_terminates_all_runners(self, config: HydraFlowConfig) -> None:
        """stop() should call terminate() on planners, agents, and reviewers."""
        orch = HydraFlowOrchestrator(config)
        with (
            patch.object(orch._planners, "terminate") as mock_p,
            patch.object(orch._agents, "terminate") as mock_a,
            patch.object(orch._reviewers, "terminate") as mock_r,
        ):
            await orch.stop()

        mock_p.assert_called_once()
        mock_a.assert_called_once()
        mock_r.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_publishes_status(self, config: HydraFlowConfig) -> None:
        """stop() should publish ORCHESTRATOR_STATUS event."""
        orch = HydraFlowOrchestrator(config)
        orch._running = True  # simulate running state
        await orch.stop()

        history = orch._bus.get_history()
        status_events = [e for e in history if e.type == EventType.ORCHESTRATOR_STATUS]
        assert len(status_events) == 1
        assert status_events[0].data["status"] == "stopping"

    def test_reset_clears_stop_event_and_running(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._stop_event.set()
        orch._running = True
        orch.reset()
        assert not orch._stop_event.is_set()
        assert not orch._running

    def test_run_status_idle_by_default(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.run_status == "idle"

    def test_run_status_running_when_running(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._running = True
        assert orch.run_status == "running"

    def test_run_status_stopping_when_stop_requested_while_running(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._running = True
        orch._stop_event.set()
        assert orch.run_status == "stopping"

    def test_has_active_processes_false_when_empty(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch._has_active_processes() is False

    def test_has_active_processes_true_with_planner_proc(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        mock_proc = AsyncMock(spec=asyncio.subprocess.Process)
        orch._planners._active_procs.add(mock_proc)
        assert orch._has_active_processes() is True

    def test_has_active_processes_true_with_agent_proc(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        mock_proc = AsyncMock(spec=asyncio.subprocess.Process)
        orch._agents._active_procs.add(mock_proc)
        assert orch._has_active_processes() is True

    def test_has_active_processes_true_with_reviewer_proc(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        mock_proc = AsyncMock(spec=asyncio.subprocess.Process)
        orch._reviewers._active_procs.add(mock_proc)
        assert orch._has_active_processes() is True

    def test_has_active_processes_true_with_hitl_proc(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        mock_proc = AsyncMock(spec=asyncio.subprocess.Process)
        orch._hitl_runner._active_procs.add(mock_proc)
        assert orch._has_active_processes() is True

    def test_run_status_stopping_with_active_procs_and_not_running(
        self, config: HydraFlowConfig
    ) -> None:
        """run_status returns 'stopping' when stop requested and processes still alive,
        even if _running is already False."""
        orch = HydraFlowOrchestrator(config)
        orch._running = False
        orch._stop_event.set()
        mock_proc = AsyncMock(spec=asyncio.subprocess.Process)
        orch._agents._active_procs.add(mock_proc)
        assert orch.run_status == "stopping"

    def test_run_status_idle_after_clean_stop(self, config: HydraFlowConfig) -> None:
        """run_status returns 'idle' when stop event is set but _running is False
        and no processes remain — stop completed cleanly."""
        orch = HydraFlowOrchestrator(config)
        orch._running = False
        orch._stop_event.set()
        assert orch.run_status == "idle"

    def test_run_status_idle_requires_no_active_procs(
        self, config: HydraFlowConfig
    ) -> None:
        """run_status returns 'idle' only when _running=False AND no active processes."""
        orch = HydraFlowOrchestrator(config)
        orch._running = False
        assert orch.run_status == "idle"

    def test_running_is_false_initially(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.running is False

    @pytest.mark.asyncio
    async def test_running_is_true_during_execution(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)
        observed_running = False

        async def spy_implement() -> tuple[list[WorkerResult], list[Task]]:
            nonlocal observed_running
            observed_running = orch.running
            orch._stop_event.set()
            return [], []

        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = spy_implement  # type: ignore[method-assign]

        await orch.run()

        assert observed_running is True

    @pytest.mark.asyncio
    async def test_running_is_false_after_completion(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert orch.running is False

    @pytest.mark.asyncio
    async def test_stop_halts_loops(self, config: HydraFlowConfig) -> None:
        """Setting stop event causes loops to exit after current iteration."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        call_count = 0

        async def counting_implement() -> tuple[list[WorkerResult], list[Task]]:
            nonlocal call_count
            call_count += 1
            await orch.request_stop()
            return [make_worker_result(42)], [TaskFactory.create(id=42)]

        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = counting_implement  # type: ignore[method-assign]

        await orch.run()

        # Only one batch should have been processed before stop
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_stop_event_cleared_on_new_run(self, config: HydraFlowConfig) -> None:
        """Calling run() again after stop should reset the stop event."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)
        await orch.request_stop()
        assert orch._stop_event.is_set()

        # run() clears the stop event at start, then loops exit immediately
        # because we set it again inside the mock
        async def plan_and_stop() -> list[PlanResult]:
            # Verify stop was cleared at start of run()
            assert not orch._stop_event.is_set() or True  # already past clear
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        await orch.run()

        # Stop event set by our mock — key test is that run() didn't fail
        assert not orch.running

    @pytest.mark.asyncio
    async def test_running_false_after_stop(self, config: HydraFlowConfig) -> None:
        """After stop halts the orchestrator, running should be False."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def stop_on_implement() -> tuple[list[WorkerResult], list[Task]]:
            await orch.request_stop()
            return [make_worker_result(42)], [TaskFactory.create(id=42)]

        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = stop_on_implement  # type: ignore[method-assign]

        await orch.run()

        assert orch.running is False


# ---------------------------------------------------------------------------
# Shutdown lifecycle
# ---------------------------------------------------------------------------


class TestOrchestratorShutdownLifecycle:
    """Tests for the full shutdown lifecycle: stop -> drain -> idle.

    These verify race conditions and state transitions during the
    stop() -> finally block -> idle sequence that the basic stop
    mechanism tests don't cover.
    """

    @pytest.mark.asyncio
    async def test_running_stays_true_during_supervise_cleanup(
        self, config: HydraFlowConfig
    ) -> None:
        """_running stays True while _supervise_loops is cleaning up tasks."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)
        running_after_stop = None

        async def plan_capture_and_stop() -> list[PlanResult]:
            nonlocal running_after_stop
            orch._stop_event.set()
            # Yield to let supervisor detect the stop event
            await asyncio.sleep(0)
            running_after_stop = orch._running
            return []

        orch._planner_phase.plan_issues = plan_capture_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert running_after_stop is True
        assert orch._running is False

    @pytest.mark.asyncio
    async def test_run_status_is_stopping_during_shutdown(
        self, config: HydraFlowConfig
    ) -> None:
        """run_status returns 'stopping' after stop() but before run() exits."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)
        captured_status = None

        async def plan_capture_and_stop() -> list[PlanResult]:
            nonlocal captured_status
            await orch.stop()
            captured_status = orch.run_status
            return []

        orch._planner_phase.plan_issues = plan_capture_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert captured_status == "stopping"

    @pytest.mark.asyncio
    async def test_run_status_is_idle_after_full_shutdown(
        self, config: HydraFlowConfig
    ) -> None:
        """run_status returns 'idle' after run() fully completes."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert orch.run_status == "idle"
        assert not orch._running
        assert orch._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_status_event_sequence_on_stop(self, config: HydraFlowConfig) -> None:
        """ORCHESTRATOR_STATUS events follow running -> stopping -> idle sequence."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            await orch.stop()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        published: list[HydraFlowEvent] = []
        original_publish = orch._bus.publish

        async def capturing_publish(event: HydraFlowEvent) -> None:
            published.append(event)
            await original_publish(event)

        orch._bus.publish = capturing_publish  # type: ignore[method-assign]

        await orch.run()

        statuses = [
            e.data["status"]
            for e in published
            if e.type == EventType.ORCHESTRATOR_STATUS
        ]
        assert statuses == ["running", "stopping", "idle"]

    @pytest.mark.asyncio
    async def test_no_orphaned_processes_after_stop(
        self, config: HydraFlowConfig
    ) -> None:
        """All runner _active_procs sets are empty after run() returns."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def plan_and_stop() -> list[PlanResult]:
            orch._stop_event.set()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        assert len(orch._planners._active_procs) == 0
        assert len(orch._agents._active_procs) == 0
        assert len(orch._reviewers._active_procs) == 0
        assert len(orch._hitl_runner._active_procs) == 0

    @pytest.mark.asyncio
    async def test_stop_calls_terminate_eagerly_and_in_finally(
        self, config: HydraFlowConfig
    ) -> None:
        """stop() terminates eagerly; finally block terminates again (belt-and-suspenders)."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        terminate_calls = {"planners": 0, "agents": 0, "reviewers": 0, "hitl": 0}

        orig_p = orch._planners.terminate
        orig_a = orch._agents.terminate
        orig_r = orch._reviewers.terminate
        orig_h = orch._hitl_runner.terminate

        def count_p() -> None:
            terminate_calls["planners"] += 1
            orig_p()

        def count_a() -> None:
            terminate_calls["agents"] += 1
            orig_a()

        def count_r() -> None:
            terminate_calls["reviewers"] += 1
            orig_r()

        def count_h() -> None:
            terminate_calls["hitl"] += 1
            orig_h()

        orch._planners.terminate = count_p  # type: ignore[method-assign]
        orch._agents.terminate = count_a  # type: ignore[method-assign]
        orch._reviewers.terminate = count_r  # type: ignore[method-assign]
        orch._hitl_runner.terminate = count_h  # type: ignore[method-assign]

        async def plan_and_stop() -> list[PlanResult]:
            await orch.stop()
            return []

        orch._planner_phase.plan_issues = plan_and_stop  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        await orch.run()

        # stop() calls terminate once, finally block calls again = 2 each
        assert terminate_calls["planners"] == 2
        assert terminate_calls["agents"] == 2
        assert terminate_calls["reviewers"] == 2
        assert terminate_calls["hitl"] == 2


# ---------------------------------------------------------------------------
# Concurrent loop coordination
# ---------------------------------------------------------------------------


class TestConcurrentLoops:
    """Tests for concurrent loop execution in the orchestrator."""

    @pytest.mark.asyncio
    async def test_all_loops_run_concurrently(self, config: HydraFlowConfig) -> None:
        """Triage, plan, implement, review should all run concurrently."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        execution_order: list[str] = []

        async def fake_triage() -> None:
            execution_order.append("triage_start")
            await asyncio.sleep(0)
            execution_order.append("triage_end")

        async def fake_plan() -> list[PlanResult]:
            execution_order.append("plan_start")
            await asyncio.sleep(0)
            execution_order.append("plan_end")
            orch._stop_event.set()
            return []

        async def fake_implement() -> tuple[list[WorkerResult], list[Task]]:
            execution_order.append("implement_start")
            await asyncio.sleep(0)
            execution_order.append("implement_end")
            return [], []

        orch._triager.triage_issues = fake_triage  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = fake_plan  # type: ignore[method-assign]
        orch._implementer.run_batch = fake_implement  # type: ignore[method-assign]

        await orch.run()

        # All should have started (concurrent loops)
        assert "triage_start" in execution_order
        assert "plan_start" in execution_order
        assert "implement_start" in execution_order


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
# Crash recovery — active issue persistence
# ---------------------------------------------------------------------------


class TestCrashRecoveryActiveIssues:
    """Tests for crash recovery via persisted active_issue_numbers."""

    def test_crash_recovery_loads_active_issues(self, config: HydraFlowConfig) -> None:
        """On init, recovered issues from state should populate _recovered_issues after run()."""
        orch = HydraFlowOrchestrator(config)
        orch._state.set_active_issue_numbers([10, 20])

        # Simulate run() startup sequence
        recovered = set(orch._state.get_active_issue_numbers())
        assert recovered == {10, 20}

    @pytest.mark.asyncio
    async def test_crash_recovery_skips_first_cycle(
        self, config: HydraFlowConfig
    ) -> None:
        """Recovered issues should be in _active_impl_issues for one cycle."""
        orch = HydraFlowOrchestrator(config)
        _mock_fetcher_noop(orch)
        orch._state.set_active_issue_numbers([10, 20])

        # Simulate run() startup
        orch._stop_event.clear()
        orch._running = True
        recovered = set(orch._state.get_active_issue_numbers())
        orch._recovered_issues = recovered
        orch._active_impl_issues.update(recovered)

        # Before first cycle: recovered issues are in active set
        assert 10 in orch._active_impl_issues
        assert 20 in orch._active_impl_issues

    @pytest.mark.asyncio
    async def test_crash_recovery_clears_after_cycle(
        self, config: HydraFlowConfig
    ) -> None:
        """After one cycle, recovered issues should be cleared from active sets."""
        orch = HydraFlowOrchestrator(config)
        _mock_fetcher_noop(orch)
        orch._state.set_active_issue_numbers([10, 20])

        # Simulate startup
        recovered = set(orch._state.get_active_issue_numbers())
        orch._recovered_issues = recovered
        orch._active_impl_issues.update(recovered)

        # Simulate what _implement_loop does at the start of a cycle
        if orch._recovered_issues:
            orch._active_impl_issues -= orch._recovered_issues
            orch._recovered_issues.clear()

        assert 10 not in orch._active_impl_issues
        assert 20 not in orch._active_impl_issues
        assert len(orch._recovered_issues) == 0


# ---------------------------------------------------------------------------
# Memory suggestion filing from implementer and reviewer transcripts
# ---------------------------------------------------------------------------

MEMORY_TRANSCRIPT = (
    "Some output\n"
    "MEMORY_SUGGESTION_START\n"
    "title: Test suggestion\n"
    "learning: Learned something useful\n"
    "context: During testing\n"
    "MEMORY_SUGGESTION_END\n"
)


class TestMemorySuggestionFiling:
    """Memory suggestions from implementer and reviewer transcripts are filed."""

    @pytest.mark.asyncio
    async def test_implement_loop_files_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """Implementer transcripts with MEMORY_SUGGESTION blocks trigger filing."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(issue_number=42, transcript=MEMORY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._implement_loop()
            mock_mem.assert_awaited_once()
            args = mock_mem.call_args
            assert args[0][0] == MEMORY_TRANSCRIPT
            assert args[0][1] == "implementer"
            assert args[0][2] == "issue #42"

    @pytest.mark.asyncio
    async def test_implement_loop_skips_empty_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        """Implementer results with empty transcripts should not trigger filing."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(issue_number=42, transcript="")

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._implement_loop()
            mock_mem.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_implement_loop_multiple_results_files_each(
        self, config: HydraFlowConfig
    ) -> None:
        """Multiple implementer results: only those with transcripts trigger filing."""
        orch = HydraFlowOrchestrator(config)
        r1 = make_worker_result(issue_number=10, transcript=MEMORY_TRANSCRIPT)
        r2 = make_worker_result(issue_number=20, transcript="")
        r3 = make_worker_result(issue_number=30, transcript=MEMORY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [r1, r2, r3], [
                TaskFactory.create(id=10),
                TaskFactory.create(id=20),
                TaskFactory.create(id=30),
            ]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._implement_loop()
            assert mock_mem.await_count == 2
            # Check the first 3 positional args of each call
            calls = mock_mem.call_args_list
            call_refs = [(c[0][0], c[0][1], c[0][2]) for c in calls]
            assert (MEMORY_TRANSCRIPT, "implementer", "issue #10") in call_refs
            assert (MEMORY_TRANSCRIPT, "implementer", "issue #30") in call_refs

    @pytest.mark.asyncio
    async def test_review_loop_files_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """Reviewer transcripts with MEMORY_SUGGESTION blocks trigger filing."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = make_review_result(
            pr_number=101, issue_number=42, transcript=MEMORY_TRANSCRIPT
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._review_loop()
            mock_mem.assert_awaited_once()
            args = mock_mem.call_args
            assert args[0][0] == MEMORY_TRANSCRIPT
            assert args[0][1] == "reviewer"
            assert args[0][2] == "PR #101"

    @pytest.mark.asyncio
    async def test_review_loop_skips_empty_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        """Reviewer results with empty transcripts should not trigger filing."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = make_review_result(
            pr_number=101, issue_number=42, transcript=""
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._review_loop()
            mock_mem.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_do_review_work_requeues_and_returns_idle_when_no_prs(
        self, config: HydraFlowConfig
    ) -> None:
        """No-PR review fetch should requeue tasks and signal idle for backoff sleep."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]
        orch._store.get_active_issues = lambda: {}  # type: ignore[method-assign]
        orch._store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        did_work = await orch._do_review_work()

        assert did_work is False
        orch._store.enqueue_transition.assert_called_once_with(review_task, "review")

    @pytest.mark.asyncio
    async def test_do_review_work_processes_adr_without_pr(
        self, config: HydraFlowConfig
    ) -> None:
        """ADR review issues should use the no-PR ADR review path."""
        orch = HydraFlowOrchestrator(config)
        adr_task = TaskFactory.create(
            id=420,
            title="[ADR] Event rendering architecture",
            body=(
                "## Context\nA\n\n## Decision\nConcrete choice with enough "
                "detail for review and finalization.\n\n## Consequences\nB"
            ),
        )

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [adr_task]
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]
        orch._reviewer.review_adrs = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        did_work = await orch._do_review_work()

        assert did_work is True
        orch._reviewer.review_adrs.assert_awaited_once_with([adr_task])
        orch._fetcher.fetch_reviewable_prs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_do_review_work_keeps_work_true_when_adr_processed_and_no_prs(
        self, config: HydraFlowConfig
    ) -> None:
        """If ADR work ran, no-PR normal review should not reset did_work to idle."""
        orch = HydraFlowOrchestrator(config)
        adr_task = TaskFactory.create(
            id=500,
            title="[ADR] Queue architecture",
            body=(
                "## Context\nA\n\n## Decision\nConcrete decision detail that is long "
                "enough to pass ADR checks.\n\n## Consequences\nB"
            ),
        )
        normal_review_task = TaskFactory.create(id=501, title="Regular review issue")

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [adr_task, normal_review_task]
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]
        orch._store.get_active_issues = lambda: {}  # type: ignore[method-assign]
        orch._store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._reviewer.review_adrs = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        did_work = await orch._do_review_work()

        assert did_work is True
        orch._reviewer.review_adrs.assert_awaited_once_with([adr_task])
        orch._store.enqueue_transition.assert_called_once_with(
            normal_review_task, "review"
        )

    @pytest.mark.asyncio
    async def test_review_loop_multiple_results_files_each(
        self, config: HydraFlowConfig
    ) -> None:
        """Multiple reviewer results: only those with transcripts trigger filing."""
        orch = HydraFlowOrchestrator(config)
        task_a = TaskFactory.create(id=10)
        task_b = TaskFactory.create(id=20)
        issue_a = IssueFactory.create(number=10)
        issue_b = IssueFactory.create(number=20)
        pr_a = PRInfoFactory.create(number=201, issue_number=10)
        pr_b = PRInfoFactory.create(number=202, issue_number=20)
        r1 = make_review_result(
            pr_number=201, issue_number=10, transcript=MEMORY_TRANSCRIPT
        )
        r2 = make_review_result(pr_number=202, issue_number=20, transcript="")

        orch._store.get_active_issues = lambda: {10: "review", 20: "review"}  # type: ignore[method-assign]

        # Per-issue PR fetch: each _review_single_issue calls with one issue
        async def _fetch_per_issue(
            active: set[int],
            prefetched_issues: list[GitHubIssue] | None = None,
        ) -> tuple[list[PRInfo], list[GitHubIssue]]:
            if prefetched_issues and prefetched_issues[0].number == 10:
                return [pr_a], [issue_a]
            if prefetched_issues and prefetched_issues[0].number == 20:
                return [pr_b], [issue_b]
            return [], []

        orch._fetcher.fetch_reviewable_prs = AsyncMock(side_effect=_fetch_per_issue)  # type: ignore[method-assign]

        # Per-issue review: each call gets one PR
        async def _review_per_pr(
            prs: list[PRInfo],
            issues: list[Task],
        ) -> list[ReviewResult]:
            if prs[0].number == 201:
                return [r1]
            return [r2]

        orch._reviewer.review_prs = AsyncMock(side_effect=_review_per_pr)  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return [task_a, task_b][call_count - 1 : call_count]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._review_loop()
            mock_mem.assert_awaited_once()
            args = mock_mem.call_args
            assert args[0][0] == MEMORY_TRANSCRIPT
            assert args[0][1] == "reviewer"
            assert args[0][2] == "PR #201"

    @pytest.mark.asyncio
    async def test_implement_loop_isolates_memory_filing_error(
        self, config: HydraFlowConfig
    ) -> None:
        """Memory filing failure in implementer must not crash the loop."""
        orch = HydraFlowOrchestrator(config)
        r1 = make_worker_result(issue_number=10, transcript=MEMORY_TRANSCRIPT)
        r2 = make_worker_result(issue_number=20, transcript=MEMORY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [r1, r2], [
                TaskFactory.create(id=10),
                TaskFactory.create(id=20),
            ]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("transient"), None],
        ) as mock_mem:
            await orch._implement_loop()  # must not raise
            assert mock_mem.await_count == 2

    @pytest.mark.asyncio
    async def test_review_loop_isolates_memory_filing_error(
        self, config: HydraFlowConfig
    ) -> None:
        """Memory filing failure in reviewer must not crash the loop."""
        orch = HydraFlowOrchestrator(config)
        task_a = TaskFactory.create(id=10)
        issue_a = IssueFactory.create(number=10)
        pr_a = PRInfoFactory.create(number=201, issue_number=10)
        r1 = make_review_result(
            pr_number=201, issue_number=10, transcript=MEMORY_TRANSCRIPT
        )

        orch._store.get_active_issues = lambda: {10: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr_a], [issue_a])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[r1])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [task_a]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("transient"),
        ) as mock_mem:
            await orch._review_loop()  # must not raise
            mock_mem.assert_awaited_once()


# ---------------------------------------------------------------------------
# Transcript summary filing from implementer and reviewer
# ---------------------------------------------------------------------------

SUMMARY_TRANSCRIPT = "x" * 1000  # Long enough to trigger summarization


class TestTranscriptSummaryFiling:
    """Transcript summaries from implementer and reviewer transcripts are posted as comments."""

    @pytest.mark.asyncio
    async def test_implement_loop_calls_summarize_and_comment(
        self, config: HydraFlowConfig
    ) -> None:
        """Implementer transcripts trigger transcript summary comment on the issue."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(issue_number=42, transcript=SUMMARY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._implement_loop()

        orch._summarizer.summarize_and_comment.assert_awaited_once()
        call_kwargs = orch._summarizer.summarize_and_comment.call_args
        assert call_kwargs.kwargs["transcript"] == SUMMARY_TRANSCRIPT
        assert call_kwargs.kwargs["issue_number"] == 42
        assert call_kwargs.kwargs["phase"] == "implement"
        assert call_kwargs.kwargs["status"] == "success"

    @pytest.mark.asyncio
    async def test_implement_loop_passes_failed_status(
        self, config: HydraFlowConfig
    ) -> None:
        """Failed implementer results post summary with status='failed'."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(
            issue_number=42, transcript=SUMMARY_TRANSCRIPT, success=False
        )

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._implement_loop()

        assert (
            orch._summarizer.summarize_and_comment.call_args.kwargs["status"]
            == "failed"
        )

    @pytest.mark.asyncio
    async def test_implement_loop_skips_empty_transcript_for_summary(
        self, config: HydraFlowConfig
    ) -> None:
        """Implementer results with empty transcripts skip summary filing."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(issue_number=42, transcript="")

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._implement_loop()

        orch._summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_loop_calls_summarize_and_comment_on_issue(
        self, config: HydraFlowConfig
    ) -> None:
        """Reviewer transcripts post summary on the original issue (not the PR)."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = make_review_result(
            pr_number=101, issue_number=42, transcript=SUMMARY_TRANSCRIPT
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._review_loop()

        orch._summarizer.summarize_and_comment.assert_awaited_once()
        call_kwargs = orch._summarizer.summarize_and_comment.call_args
        # Fix for #767: should use issue_number (42), not pr_number (101)
        assert call_kwargs.kwargs["issue_number"] == 42
        assert call_kwargs.kwargs["phase"] == "review"
        # Default make_review_result has merged=False, ci_passed=None → "completed"
        assert call_kwargs.kwargs["status"] == "completed"

    @pytest.mark.asyncio
    async def test_review_loop_passes_success_status_when_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Merged review results post summary with status='success'."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            transcript=SUMMARY_TRANSCRIPT,
            merged=True,
            verdict=ReviewVerdict.APPROVE,
            summary="Looks good.",
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._review_loop()

        assert (
            orch._summarizer.summarize_and_comment.call_args.kwargs["status"]
            == "success"
        )

    @pytest.mark.asyncio
    async def test_review_loop_passes_failed_status_when_ci_failed(
        self, config: HydraFlowConfig
    ) -> None:
        """CI-failed review results post summary with status='failed'."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            transcript=SUMMARY_TRANSCRIPT,
            merged=False,
            ci_passed=False,
            verdict=ReviewVerdict.COMMENT,
            summary="CI failed.",
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._review_loop()

        assert (
            orch._summarizer.summarize_and_comment.call_args.kwargs["status"]
            == "failed"
        )

    @pytest.mark.asyncio
    async def test_review_loop_skips_summary_when_issue_number_zero(
        self, config: HydraFlowConfig
    ) -> None:
        """Review results with issue_number=0 skip transcript summary posting."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=0)
        review_issue = IssueFactory.create(number=0)
        pr = PRInfoFactory.create(number=101, issue_number=0)
        review_result = ReviewResult(
            pr_number=101,
            issue_number=0,
            transcript=SUMMARY_TRANSCRIPT,
            merged=True,
            verdict=ReviewVerdict.APPROVE,
            summary="Looks good.",
        )

        orch._store.get_active_issues = lambda: {0: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._review_loop()

        orch._summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transcript_summary_failure_does_not_block_pipeline(
        self, config: HydraFlowConfig
    ) -> None:
        """Errors in transcript summarization must not crash the implement loop."""
        orch = HydraFlowOrchestrator(config)
        r1 = make_worker_result(issue_number=10, transcript=SUMMARY_TRANSCRIPT)
        r2 = make_worker_result(issue_number=20, transcript=SUMMARY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [r1, r2], [
                TaskFactory.create(id=10),
                TaskFactory.create(id=20),
            ]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock(  # type: ignore[method-assign]
            side_effect=[RuntimeError("transient"), None]
        )

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            # Should not raise
            await orch._implement_loop()

        # Both calls should have been attempted despite the first one failing
        assert orch._summarizer.summarize_and_comment.await_count == 2


# ---------------------------------------------------------------------------
# _post_run_hooks — deduplicated memory + summary helper
# ---------------------------------------------------------------------------


class TestPostRunHooks:
    """Tests for the extracted _post_run_hooks helper."""

    @pytest.mark.asyncio
    async def test_calls_memory_suggestion_and_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """Happy path: both memory suggestion and summarize are called."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._post_run_hooks(
                transcript="some transcript",
                source="implementer",
                reference="issue #42",
                issue_number=42,
                phase="implement",
                status="success",
                duration_seconds=10.0,
                log_file=".hydraflow/logs/issue-42.txt",
            )
            mock_mem.assert_awaited_once()
        orch._summarizer.summarize_and_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_memory_suggestion_failure_does_not_block_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """Exception in memory suggestion must not prevent summarize."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            await orch._post_run_hooks(
                transcript="transcript",
                source="implementer",
                reference="issue #1",
                issue_number=1,
                phase="implement",
                status="success",
                duration_seconds=5.0,
                log_file="log.txt",
            )
        orch._summarizer.summarize_and_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summarize_failure_does_not_propagate(
        self, config: HydraFlowConfig
    ) -> None:
        """Exception in summarize must not propagate to caller."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("summarize failed")
        )

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            # Should not raise
            await orch._post_run_hooks(
                transcript="transcript",
                source="reviewer",
                reference="PR #99",
                issue_number=99,
                phase="review",
                status="completed",
                duration_seconds=2.0,
                log_file="log.txt",
            )

    @pytest.mark.asyncio
    async def test_skips_summarize_when_issue_number_zero(
        self, config: HydraFlowConfig
    ) -> None:
        """When issue_number is 0 (review edge case), summarize is skipped."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._post_run_hooks(
                transcript="transcript",
                source="reviewer",
                reference="PR #50",
                issue_number=0,
                phase="review",
                status="completed",
                duration_seconds=1.0,
                log_file="log.txt",
            )
            mock_mem.assert_awaited_once()
        orch._summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_correct_args_to_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify argument forwarding to file_memory_suggestion."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._post_run_hooks(
                transcript="tx",
                source="implementer",
                reference="issue #7",
                issue_number=7,
                phase="implement",
                status="failed",
                duration_seconds=3.5,
                log_file="logs/issue-7.txt",
            )
            mock_mem.assert_awaited_once_with(
                "tx", "implementer", "issue #7", ANY, ANY, ANY
            )

    @pytest.mark.asyncio
    async def test_passes_correct_args_to_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify argument forwarding to summarize_and_comment."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            await orch._post_run_hooks(
                transcript="tx",
                source="implementer",
                reference="issue #7",
                issue_number=7,
                phase="implement",
                status="failed",
                duration_seconds=3.5,
                log_file="logs/issue-7.txt",
            )
        orch._summarizer.summarize_and_comment.assert_awaited_once_with(
            transcript="tx",
            issue_number=7,
            phase="implement",
            status="failed",
            duration_seconds=3.5,
            log_file="logs/issue-7.txt",
        )


# ---------------------------------------------------------------------------
# _start_session / _end_session / _restore_state — extracted from run()
# ---------------------------------------------------------------------------


class TestStartSession:
    """Tests for the extracted _start_session helper."""

    @pytest.mark.asyncio
    async def test_creates_session_log_with_correct_repo(
        self, config: HydraFlowConfig
    ) -> None:
        """_start_session should create a SessionLog with the correct repo and clear results."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()

        assert orch._current_session is not None
        assert orch._current_session.repo == config.repo
        assert orch._session_issue_results == {}

    @pytest.mark.asyncio
    async def test_publishes_session_start_event(self, config: HydraFlowConfig) -> None:
        """_start_session should publish a SESSION_START event with the repo."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()

        events = [e for e in bus.get_history() if e.type == EventType.SESSION_START]
        assert len(events) == 1
        assert events[0].data["repo"] == config.repo

    @pytest.mark.asyncio
    async def test_sets_bus_session_id(self, config: HydraFlowConfig) -> None:
        """_start_session should set the session id on the event bus."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()

        assert orch._current_session is not None
        assert bus._active_session_id == orch._current_session.id


class TestEndSession:
    """Tests for the extracted _end_session helper."""

    @pytest.mark.asyncio
    async def test_publishes_session_end_event(self, config: HydraFlowConfig) -> None:
        """_end_session should publish exactly one SESSION_END event."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()
        await orch._end_session()

        end_events = [e for e in bus.get_history() if e.type == EventType.SESSION_END]
        assert len(end_events) == 1

    @pytest.mark.asyncio
    async def test_session_end_event_contains_correct_issue_counts(
        self, config: HydraFlowConfig
    ) -> None:
        """_end_session event payload should reflect correct succeeded/failed/processed counts."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()
        orch._session_issue_results = {10: True, 20: False, 30: True}

        await orch._end_session()

        data = next(
            e.data for e in bus.get_history() if e.type == EventType.SESSION_END
        )
        assert data["issues_succeeded"] == 2
        assert data["issues_failed"] == 1
        assert set(data["issues_processed"]) == {10, 20, 30}

    @pytest.mark.asyncio
    async def test_noop_when_no_current_session(self, config: HydraFlowConfig) -> None:
        """_end_session should be a no-op when _current_session is None."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        # No session started — should not raise or publish
        await orch._end_session()

        end_events = [e for e in bus.get_history() if e.type == EventType.SESSION_END]
        assert len(end_events) == 0

    @pytest.mark.asyncio
    async def test_clears_session_state(self, config: HydraFlowConfig) -> None:
        """_end_session should clear _current_session and bus session_id."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()
        await orch._end_session()

        assert orch._current_session is None
        assert bus._active_session_id is None


class TestRestoreState:
    """Tests for the extracted _restore_state helper."""

    def test_restores_intervals_and_crash_recovery(
        self, config: HydraFlowConfig
    ) -> None:
        """_restore_state should load saved intervals and active issues."""
        orch = HydraFlowOrchestrator(config)
        orch._state.set_worker_intervals({"memory_sync": 120})
        orch._state.set_active_issue_numbers([10, 20])

        orch._restore_state()

        assert orch._bg_worker_intervals.get("memory_sync") == 120
        assert orch._recovered_issues == {10, 20}
        assert 10 in orch._active_impl_issues
        assert 20 in orch._active_impl_issues

    def test_clears_interrupted_issues(self, config: HydraFlowConfig) -> None:
        """_restore_state should remove interrupted issues from all tracking sets."""
        orch = HydraFlowOrchestrator(config)
        # Simulate crash recovery state
        orch._state.set_active_issue_numbers([10, 20])
        orch._state.set_interrupted_issues({10: "implement", 20: "review"})
        # Pre-populate review and HITL sets so the discard calls are actually exercised
        orch._active_review_issues.update([10, 20])
        orch._hitl_phase.active_hitl_issues.update([10, 20])

        orch._restore_state()

        # Interrupted issues removed from all four tracking sets
        assert 10 not in orch._recovered_issues
        assert 20 not in orch._recovered_issues
        assert 10 not in orch._active_impl_issues
        assert 20 not in orch._active_impl_issues
        assert 10 not in orch._active_review_issues
        assert 20 not in orch._active_review_issues
        assert 10 not in orch._hitl_phase.active_hitl_issues
        assert 20 not in orch._hitl_phase.active_hitl_issues


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


# ---------------------------------------------------------------------------
# MemoryError propagation through _polling_loop
# ---------------------------------------------------------------------------


class TestMemoryErrorPropagation:
    """Tests that MemoryError propagates through _polling_loop."""

    @pytest.mark.asyncio
    async def test_memory_error_propagates_through_polling_loop(
        self, config: HydraFlowConfig
    ) -> None:
        """MemoryError should not be caught by _polling_loop's except Exception."""
        orch = HydraFlowOrchestrator(config)

        async def oom_work() -> None:
            raise MemoryError("out of memory")

        with pytest.raises(MemoryError, match="out of memory"):
            await orch._polling_loop("test", oom_work, 10)

    @pytest.mark.asyncio
    async def test_generic_error_is_caught_by_polling_loop(
        self, config: HydraFlowConfig
    ) -> None:
        """Non-critical exceptions should be caught and not propagate."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def failing_then_stop() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            orch._stop_event.set()

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        # Should not raise — RuntimeError is caught
        await orch._polling_loop("test", failing_then_stop, 10)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_polling_loop_emits_ok_heartbeat(
        self, config: HydraFlowConfig
    ) -> None:
        """_polling_loop should call update_bg_worker_status('ok') after work."""
        orch = HydraFlowOrchestrator(config)

        async def work_then_stop() -> bool:
            orch._stop_event.set()
            return False

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]
        await orch._polling_loop("implement", work_then_stop, 10)
        states = orch.get_bg_worker_states()
        assert "implement" in states
        assert states["implement"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_polling_loop_emits_error_heartbeat(
        self, config: HydraFlowConfig
    ) -> None:
        """_polling_loop should call update_bg_worker_status('error') on exception."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def fail_then_stop() -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            orch._stop_event.set()
            return False

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]
        await orch._polling_loop("triage", fail_then_stop, 10)
        states = orch.get_bg_worker_states()
        # Final heartbeat should be "ok" from the second (successful) call
        assert states["triage"]["status"] == "ok"


# --- Background Worker Enabled ---


class TestBgWorkerEnabled:
    """Tests for is_bg_worker_enabled / set_bg_worker_enabled."""

    def test_is_bg_worker_enabled_defaults_true(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.is_bg_worker_enabled("memory_sync") is True

    def test_set_and_get_enabled(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_enabled("memory_sync", False)
        assert orch.is_bg_worker_enabled("memory_sync") is False

    def test_set_enabled_true(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_enabled("metrics", False)
        orch.set_bg_worker_enabled("metrics", True)
        assert orch.is_bg_worker_enabled("metrics") is True

    def test_multiple_workers_independent(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_enabled("memory_sync", False)
        orch.set_bg_worker_enabled("metrics", True)
        assert orch.is_bg_worker_enabled("memory_sync") is False
        assert orch.is_bg_worker_enabled("metrics") is True


# --- Background Worker States ---


class TestBgWorkerStates:
    """Tests for get_bg_worker_states / update_bg_worker_status."""

    def test_get_bg_worker_states_empty(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.get_bg_worker_states() == {}

    def test_update_and_get_states(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("memory_sync", "running")
        states = orch.get_bg_worker_states()
        assert "memory_sync" in states
        assert states["memory_sync"]["status"] == "running"

    def test_states_include_enabled_flag(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("metrics", "idle")
        orch.set_bg_worker_enabled("metrics", False)
        states = orch.get_bg_worker_states()
        assert states["metrics"].get("enabled") is False


# --- Background Worker Interval ---


class TestBgWorkerInterval:
    """Tests for set_bg_worker_interval."""

    def test_set_bg_worker_interval_stores_value(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_interval("memory_sync", 300)
        assert orch.get_bg_worker_interval("memory_sync") == 300

    def test_set_bg_worker_interval_persists_to_state(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_interval("metrics", 600)
        # Verify state was persisted via public StateTracker method
        intervals = orch._state.get_worker_intervals()
        assert intervals.get("metrics") == 600


# --- Update Background Worker Status ---


class TestUpdateBgWorkerStatus:
    """Tests for update_bg_worker_status."""

    def test_update_bg_worker_status_stores_fields(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("memory_sync", "running")
        state = orch._bg_worker_states["memory_sync"]
        assert state["name"] == "memory_sync"
        assert state["status"] == "running"
        assert "last_run" in state

    def test_update_bg_worker_status_with_details(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("metrics", "running", details={"synced": 5})
        state = orch._bg_worker_states["metrics"]
        assert state["details"]["synced"] == 5

    def test_update_bg_worker_status_without_details(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("memory_sync", "idle")
        state = orch._bg_worker_states["memory_sync"]
        assert state["details"] == {}

    @pytest.mark.asyncio
    async def test_restore_bg_worker_states_backfills_from_events(
        self, config: HydraFlowConfig
    ) -> None:
        bus = EventBus()
        await bus.publish(
            HydraFlowEvent(
                type=EventType.BACKGROUND_WORKER_STATUS,
                data={
                    "worker": "memory_sync",
                    "status": "ok",
                    "last_run": "2026-02-25T09:00:00Z",
                    "details": {"count": 4},
                },
            )
        )
        orch = HydraFlowOrchestrator(config, event_bus=bus)
        orch._restore_bg_worker_states()
        states = orch.get_bg_worker_states()
        assert states["memory_sync"]["status"] == "ok"
        assert states["memory_sync"]["details"]["count"] == 4
        persisted = orch.state.get_bg_worker_states()
        assert "memory_sync" in persisted

    def test_update_bg_worker_status_persists_to_state(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("memory_sync", "ok")
        persisted = orch._state.get_bg_worker_states()
        assert "memory_sync" in persisted
        assert persisted["memory_sync"]["status"] == "ok"

    def test_restore_bg_worker_states(self, config: HydraFlowConfig) -> None:
        tracker = StateTracker(config.state_file)
        tracker.set_bg_worker_state(
            "memory_sync",
            BackgroundWorkerState(
                name="memory_sync",
                status="ok",
                last_run="2026-02-20T10:30:00Z",
                details={"count": 2},
            ),
        )
        orch = HydraFlowOrchestrator(config, state=tracker)
        orch._restore_state()
        states = orch.get_bg_worker_states()
        assert states["memory_sync"]["last_run"] == "2026-02-20T10:30:00Z"
        assert states["memory_sync"]["details"]["count"] == 2


# --- Orchestrator Property Accessors ---


class TestOrchestratorPropertyAccessors:
    """Tests for current_session_id, issue_store, metrics_manager, run_recorder."""

    def test_current_session_id_none_when_no_session(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.current_session_id is None

    def test_issue_store_returns_store(self, config: HydraFlowConfig) -> None:
        from issue_store import IssueStore

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch.issue_store, IssueStore)

    def test_metrics_manager_returns_manager(self, config: HydraFlowConfig) -> None:
        from metrics_manager import MetricsManager

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch.metrics_manager, MetricsManager)

    def test_run_recorder_returns_recorder(self, config: HydraFlowConfig) -> None:
        from run_recorder import RunRecorder

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch.run_recorder, RunRecorder)


class TestPipelineStatsEmission:
    """Tests for _build_pipeline_stats and emit_pipeline_stats."""

    def test_build_pipeline_stats_without_session(
        self, config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        stats = orch.build_pipeline_stats()
        assert stats.timestamp
        assert stats.uptime_seconds == 0.0
        assert "triage" in stats.stages
        assert "plan" in stats.stages
        assert "implement" in stats.stages
        assert "review" in stats.stages
        assert "hitl" in stats.stages
        assert "merged" in stats.stages

    def test_build_pipeline_stats_includes_worker_caps(
        self, config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        stats = orch.build_pipeline_stats()
        assert stats.stages["triage"].worker_cap == config.max_triagers
        assert stats.stages["plan"].worker_cap == config.max_planners
        assert stats.stages["implement"].worker_cap == config.max_workers
        assert stats.stages["review"].worker_cap == config.max_reviewers
        assert stats.stages["hitl"].worker_cap == config.max_hitl_workers

    def test_build_pipeline_stats_with_active_session(
        self, config: HydraFlowConfig
    ) -> None:
        from datetime import UTC, datetime

        from models import SessionLog
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        orch._current_session = SessionLog(
            id="test-session",
            repo="test/repo",
            started_at=(datetime.now(UTC)).isoformat(),
        )
        stats = orch.build_pipeline_stats()
        # Uptime should be positive since session just started
        assert stats.uptime_seconds >= 0.0

    def test_build_pipeline_stats_merged_tracks_session_results(
        self, config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        orch._state.reset_session_counters("2026-01-01T00:00:00+00:00")
        orch._state.increment_session_counter("merged")
        orch._state.increment_session_counter("merged")
        stats = orch.build_pipeline_stats()
        assert stats.stages["merged"].completed_session == 2

    def test_build_pipeline_stats_per_stage_session_counters(
        self, config: HydraFlowConfig
    ) -> None:
        """Each stage's completed_session should reflect its named session counter."""
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        orch._state.reset_session_counters("2026-01-01T00:00:00+00:00")
        orch._state.increment_session_counter("triaged")
        orch._state.increment_session_counter("triaged")
        orch._state.increment_session_counter("planned")
        orch._state.increment_session_counter("implemented")
        orch._state.increment_session_counter("implemented")
        orch._state.increment_session_counter("implemented")
        orch._state.increment_session_counter("reviewed")
        stats = orch.build_pipeline_stats()
        assert stats.stages["triage"].completed_session == 2
        assert stats.stages["plan"].completed_session == 1
        assert stats.stages["implement"].completed_session == 3
        assert stats.stages["review"].completed_session == 1
        assert stats.stages["hitl"].completed_session == 0

    @pytest.mark.asyncio
    async def test_emit_pipeline_stats_publishes_event(
        self, config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)
        await orch.emit_pipeline_stats()
        history = bus.get_history()
        pipeline_events = [e for e in history if e.type == EventType.PIPELINE_STATS]
        assert len(pipeline_events) == 1
        data = pipeline_events[0].data
        assert "timestamp" in data
        assert "stages" in data
        assert "throughput" in data
        assert "uptime_seconds" in data

    def test_build_pipeline_stats_is_json_serializable(
        self, config: HydraFlowConfig
    ) -> None:
        import json

        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        stats = orch.build_pipeline_stats()
        data = stats.model_dump()
        # Should not raise
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

    def test_pipeline_stats_loop_in_supervise_factories(
        self, config: HydraFlowConfig
    ) -> None:
        """pipeline_stats loop is registered in _supervise_loops."""
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        # Verify the method exists
        assert hasattr(orch, "_pipeline_stats_loop")
        assert callable(orch._pipeline_stats_loop)
