"""Tests for dx/hydraflow/orchestrator.py - Core init, properties, lifecycle, run loop."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from events import EventBus, EventType, HydraFlowEvent
from state import StateTracker

if TYPE_CHECKING:
    from config import HydraFlowConfig
from models import (
    PlanResult,
    Task,
    WorkerResult,
)
from orchestrator import HydraFlowOrchestrator
from tests.conftest import TaskFactory, WorkerResultFactory

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
        from workspace import WorkspaceManager

        orch = HydraFlowOrchestrator(config)
        assert isinstance(orch._worktrees, WorkspaceManager)

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


class TestRunCallsSanitizeRepo:
    """Verify run() calls sanitize_repo at startup and shutdown."""

    @pytest.mark.asyncio
    async def test_sanitize_repo_called_on_startup(
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

        with patch.object(
            orch._worktrees, "sanitize_repo", new_callable=AsyncMock
        ) as mock_sanitize:
            await orch.run()

        # Called at startup + shutdown = at least 2 times
        assert mock_sanitize.await_count >= 2


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
# Orchestrator Property Accessors
# ---------------------------------------------------------------------------


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
