"""Integration tests covering orchestrator loop interactions."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

import pytest

from events import EventBus, EventType, HydraFlowEvent
from orchestrator import HydraFlowOrchestrator
from state import StateTracker
from subprocess_util import CreditExhaustedError
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory
from tests.orchestrator_integration_utils import (
    FakeWorktreeManager,
    PipelineScript,
    build_scripted_services,
)

pytestmark = pytest.mark.integration


@contextlib.contextmanager
def scripted_orchestrator(
    config, script: PipelineScript
) -> Iterator[HydraFlowOrchestrator]:
    """Patch build_services so HydraFlowOrchestrator uses scripted phases."""

    def _build_services(cfg, bus, state, stop_event, callbacks):
        return build_scripted_services(
            cfg, bus, state, stop_event, callbacks, script=script
        )

    with patch("orchestrator.build_services", side_effect=_build_services):
        orch = HydraFlowOrchestrator(config)
        try:
            yield orch
        finally:
            orch._stop_event.set()


async def _wait_for(condition: Callable[[], bool], timeout: float = 1.0) -> None:
    """Poll *condition* until it returns True or timeout expires."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if condition():
            return
        if loop.time() >= deadline:
            raise AssertionError("Condition timed out")
        await asyncio.sleep(0.01)


async def _drive_loop(
    orch: HydraFlowOrchestrator,
    coro_fn: Callable[[], Coroutine[Any, Any, None]],
    condition: Callable[[], bool],
    timeout: float = 1.0,
) -> None:
    """Run an orchestrator loop until *condition* becomes true."""
    orch._stop_event.clear()
    task = asyncio.create_task(coro_fn())  # type: ignore[arg-type]
    try:
        await _wait_for(condition, timeout)
    finally:
        orch._stop_event.set()
        await task
        orch._stop_event.clear()


def _queue_depth(orch: HydraFlowOrchestrator, stage: str) -> int:
    stats = orch._store.get_queue_stats()
    return stats.queue_depth.get(stage, 0)


def _config(tmp_path):
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
        poll_interval=5,
        data_poll_interval=10,
    )


@pytest.mark.asyncio
async def test_full_pipeline_lifecycle(tmp_path) -> None:
    """Triaged issues should move through all phases to merge."""
    script = PipelineScript()
    config = _config(tmp_path)
    with scripted_orchestrator(config, script) as orch:
        issue = TaskFactory.create(
            id=101,
            title="Pipeline happy path",
            tags=[config.find_label[0]],
        )
        orch._store.enqueue_transition(issue, "find")

        await _drive_loop(
            orch,
            orch._triage_loop,
            lambda: _queue_depth(orch, "find") == 0,
        )
        await _drive_loop(
            orch,
            orch._plan_loop,
            lambda: _queue_depth(orch, "plan") == 0,
        )
        await _drive_loop(
            orch,
            orch._implement_loop,
            lambda: (
                _queue_depth(orch, "ready") == 0 and _queue_depth(orch, "review") >= 1
            ),
        )
        await _drive_loop(
            orch,
            orch._review_loop,
            lambda: _queue_depth(orch, "review") == 0,
        )

        stats = orch._store.get_queue_stats()
        assert stats.queue_depth.get("find", 0) == 0
        assert stats.queue_depth.get("plan", 0) == 0
        assert stats.queue_depth.get("ready", 0) == 0
        assert stats.queue_depth.get("review", 0) == 0


@pytest.mark.asyncio
async def test_crash_recovery_releases_recovered_issue(tmp_path) -> None:
    """Recovered implement issues should be cleared after one run cycle."""
    script = PipelineScript()
    config = _config(tmp_path)
    with scripted_orchestrator(config, script) as orch:
        state: StateTracker = orch._state
        state.set_active_issue_numbers([202])
        orch._restore_state()
        assert 202 in orch._recovered_issues

        issue = TaskFactory.create(
            id=202,
            title="Recovered issue",
            tags=[config.ready_label[0]],
        )
        orch._store.enqueue_transition(issue, "ready")

        await orch._do_implement_work()

        assert not orch._recovered_issues
        assert state.get_active_issue_numbers() == []


@pytest.mark.asyncio
async def test_credit_pause_publishes_alerts_and_restores_loops(tmp_path) -> None:
    """Credit exhaustion should pause loops, emit alerts, and restart loops."""
    script = PipelineScript()
    config = _config(tmp_path)
    with scripted_orchestrator(config, script) as orch:
        active_task = asyncio.create_task(asyncio.sleep(10))
        tasks = {"triage": active_task}

        async def fake_loop() -> None:
            await asyncio.sleep(0)

        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]] = [
            ("triage", fake_loop)
        ]
        resume_at = datetime.now(UTC) + timedelta(seconds=0.02)
        exc = CreditExhaustedError("limit reached", resume_at=resume_at)

        await orch._pause_for_credits(exc, "triage", tasks, loop_factories)

        assert orch._credits_paused_until is None
        assert tasks["triage"].get_name().startswith("hydraflow")
        history_types = [event.type for event in orch.event_bus.get_history()]
        assert history_types.count(EventType.SYSTEM_ALERT) >= 2

        tasks["triage"].cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tasks["triage"]


@pytest.mark.asyncio
async def test_hitl_round_trip_moves_issue_back_to_plan(tmp_path) -> None:
    """HITL correction should route an issue back to the requested stage."""
    issue_id = 404
    script = PipelineScript(
        triage_routes={issue_id: "hitl"},
        hitl_resolutions={issue_id: "plan"},
    )
    config = _config(tmp_path)
    with scripted_orchestrator(config, script) as orch:
        issue = TaskFactory.create(
            id=issue_id,
            title="Needs HITL",
            tags=[config.find_label[0]],
        )
        orch._store.enqueue_transition(issue, "find")

        await _drive_loop(
            orch,
            orch._triage_loop,
            lambda: _queue_depth(orch, "find") == 0,
        )
        assert _queue_depth(orch, "hitl") == 1

        orch._hitl_phase.submit_correction(issue_id, "retry with guidance")

        await _drive_loop(
            orch,
            orch._hitl_loop,
            lambda: _queue_depth(orch, "hitl") == 0 and _queue_depth(orch, "plan") == 1,
        )


@pytest.mark.asyncio
async def test_failed_implementation_discards_worktree(tmp_path) -> None:
    """Implementation failures should trigger worktree cleanup."""
    issue_id = 303
    script = PipelineScript(implement_behaviors={issue_id: "fail"})
    config = _config(tmp_path)
    with scripted_orchestrator(config, script) as orch:
        issue = TaskFactory.create(
            id=issue_id,
            title="Implementation failure",
            tags=[config.ready_label[0]],
        )
        orch._store.enqueue_transition(issue, "ready")

        await _drive_loop(
            orch,
            orch._implement_loop,
            lambda: _queue_depth(orch, "ready") == 0,
        )

        worktrees = cast(FakeWorktreeManager, orch._worktrees)
        assert issue_id in worktrees.cleaned


@pytest.mark.asyncio
async def test_concurrent_loops_do_not_double_process_same_issue(tmp_path) -> None:
    """Two concurrent implement workers must not process the same issue twice."""
    issue_id = 505
    script = PipelineScript()
    config = _config(tmp_path)
    with scripted_orchestrator(config, script) as orch:
        issue = TaskFactory.create(
            id=issue_id,
            title="Concurrent isolation check",
            tags=[config.ready_label[0]],
        )
        orch._store.enqueue_transition(issue, "ready")

        # Run two implement work calls concurrently in the same event loop.
        # ScriptedImplementPhase.run_batch has no await points, so the first
        # coroutine dequeues atomically before the second starts — verifying
        # that the IssueStore dequeue is not vulnerable to same-loop races.
        results = await asyncio.gather(
            orch._do_implement_work(),
            orch._do_implement_work(),
        )

        # Exactly one worker should have done real work.
        assert sum(results) == 1
        # The issue appears in the review queue exactly once.
        assert _queue_depth(orch, "review") == 1


@pytest.mark.asyncio
async def test_label_transition_atomicity(tmp_path) -> None:
    """An issue must reside in exactly one stage at every point during transitions."""
    script = PipelineScript()
    config = _config(tmp_path)
    with scripted_orchestrator(config, script) as orch:
        issue = TaskFactory.create(
            id=606,
            title="Atomicity check",
            tags=[config.find_label[0]],
        )

        def _total_queue_depth() -> int:
            stats = orch._store.get_queue_stats()
            return sum(stats.queue_depth.values())

        orch._store.enqueue_transition(issue, "find")
        assert _total_queue_depth() == 1

        orch._store.enqueue_transition(issue, "plan")
        assert _total_queue_depth() == 1

        orch._store.enqueue_transition(issue, "ready")
        assert _total_queue_depth() == 1

        orch._store.enqueue_transition(issue, "review")
        assert _total_queue_depth() == 1

        orch._store.enqueue_transition(issue, "hitl")
        assert _total_queue_depth() == 1


@pytest.mark.asyncio
async def test_event_bus_delivery_under_concurrent_load() -> None:
    """All events published concurrently must appear in the bus history."""
    bus = EventBus()
    n_publishers = 20

    async def _publish(i: int) -> None:
        await bus.publish(
            HydraFlowEvent(type=EventType.PHASE_CHANGE, data={"index": i})
        )

    await asyncio.gather(*[_publish(i) for i in range(n_publishers)])

    history = bus.get_history()
    indices = {e.data["index"] for e in history if "index" in e.data}
    assert indices == set(range(n_publishers))
