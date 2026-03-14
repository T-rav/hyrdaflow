"""Tests for the background worker trigger (Run Now) mechanism."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import BaseBackgroundLoop, LoopDeps
from events import EventBus
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Stub loop for testing
# ---------------------------------------------------------------------------


class _StubLoop(BaseBackgroundLoop):
    """Minimal concrete subclass for testing trigger mechanics."""

    def __init__(
        self, *, work_fn: Any = None, default_interval: int = 60, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._work_fn = work_fn or (lambda: {"stub": True})
        self._default_interval = default_interval
        self.work_call_count = 0

    async def _do_work(self) -> dict[str, Any] | None:
        self.work_call_count += 1
        result = self._work_fn()
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _get_default_interval(self) -> int:
        return self._default_interval


def _make_stub(
    tmp_path: Path,
    *,
    enabled: bool = True,
    work_fn: Any = None,
    default_interval: int = 60,
    run_on_startup: bool = False,
) -> tuple[_StubLoop, asyncio.Event]:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    bus = EventBus()
    stop_event = asyncio.Event()

    deps = LoopDeps(
        event_bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _name: enabled,
        sleep_fn=AsyncMock(),
    )
    loop = _StubLoop(
        work_fn=work_fn,
        default_interval=default_interval,
        worker_name="test_worker",
        config=config,
        deps=deps,
        run_on_startup=run_on_startup,
    )
    return loop, stop_event


# ---------------------------------------------------------------------------
# BaseBackgroundLoop trigger tests
# ---------------------------------------------------------------------------


class TestTriggerEvent:
    """Tests for the trigger() method on BaseBackgroundLoop."""

    def test_trigger_sets_event(self, tmp_path: Path) -> None:
        """trigger() sets the internal asyncio.Event."""
        loop, _ = _make_stub(tmp_path)
        assert not loop._trigger_event.is_set()
        loop.trigger()
        assert loop._trigger_event.is_set()

    def test_trigger_idempotent(self, tmp_path: Path) -> None:
        """Calling trigger() multiple times is safe."""
        loop, _ = _make_stub(tmp_path)
        loop.trigger()
        loop.trigger()
        assert loop._trigger_event.is_set()

    @pytest.mark.asyncio
    async def test_sleep_or_trigger_returns_early_on_trigger(
        self, tmp_path: Path
    ) -> None:
        """_sleep_or_trigger returns early when trigger is called."""
        loop, _ = _make_stub(tmp_path)

        async def _real_sleep(s: float) -> None:
            await asyncio.sleep(s)

        loop._sleep_fn = _real_sleep

        async def _trigger_soon() -> None:
            await asyncio.sleep(0.01)
            loop.trigger()

        asyncio.create_task(_trigger_soon())
        await asyncio.wait_for(loop._sleep_or_trigger(10), timeout=2.0)
        assert not loop._trigger_event.is_set()

    @pytest.mark.asyncio
    async def test_sleep_or_trigger_completes_normally(self, tmp_path: Path) -> None:
        """_sleep_or_trigger completes normally when not triggered."""

        async def _real_sleep(s: float) -> None:
            await asyncio.sleep(s)

        loop, _ = _make_stub(tmp_path)
        loop._sleep_fn = _real_sleep
        await asyncio.wait_for(loop._sleep_or_trigger(0.01), timeout=2.0)

    @pytest.mark.asyncio
    async def test_trigger_interrupts_run_loop_sleep(self, tmp_path: Path) -> None:
        """trigger() causes the run loop to execute _do_work immediately."""
        loop, stop_event = _make_stub(tmp_path, default_interval=3600)

        cycle_count = 0

        async def _do_work_and_stop() -> dict[str, Any] | None:
            nonlocal cycle_count
            cycle_count += 1
            if cycle_count >= 2:
                stop_event.set()
            return None

        loop._work_fn = _do_work_and_stop

        # Trigger after first sleep to force immediate second cycle
        async def _trigger_after_start() -> None:
            # Wait for first cycle to complete
            while cycle_count < 1:
                await asyncio.sleep(0.01)
            loop.trigger()

        task = asyncio.create_task(loop.run())
        trigger_task = asyncio.create_task(_trigger_after_start())

        # Should complete quickly because trigger interrupts the 3600s sleep
        await asyncio.wait_for(asyncio.gather(task, trigger_task), timeout=5.0)
        assert cycle_count >= 2


# ---------------------------------------------------------------------------
# Orchestrator trigger_bg_worker tests
# ---------------------------------------------------------------------------


class TestOrchestratorTriggerBgWorker:
    """Tests for HydraFlowOrchestrator.trigger_bg_worker()."""

    def test_trigger_known_worker(self) -> None:
        """trigger_bg_worker returns True and calls trigger() for known workers."""
        mock_loop = MagicMock(spec=BaseBackgroundLoop)
        orch = MagicMock()
        orch._bg_loop_registry = {"memory_sync": mock_loop}

        # Inline the method logic to test it without full orchestrator init
        from orchestrator import HydraFlowOrchestrator

        result = HydraFlowOrchestrator.trigger_bg_worker(orch, "memory_sync")
        assert result is True
        mock_loop.trigger.assert_called_once()

    def test_trigger_unknown_worker(self) -> None:
        """trigger_bg_worker returns False for unknown worker names."""
        orch = MagicMock()
        orch._bg_loop_registry = {}

        from orchestrator import HydraFlowOrchestrator

        result = HydraFlowOrchestrator.trigger_bg_worker(orch, "nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# Dashboard route tests
# ---------------------------------------------------------------------------


class TestTriggerBgWorkerRoute:
    """Tests for the POST /api/control/bg-worker/trigger endpoint."""

    def _create_router(self, tmp_path: Path, orch: Any = None) -> Any:
        from dashboard_routes import create_router
        from pr_manager import PRManager

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        state = MagicMock()
        bus = EventBus()
        pr_mgr = PRManager(config, bus)

        return create_router(
            config=config,
            event_bus=bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: orch,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _find_endpoint(self, router: Any, path: str) -> Any:
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        raise LookupError(f"No endpoint found for {path}")

    @pytest.mark.asyncio
    async def test_trigger_missing_name(self, tmp_path: Path) -> None:
        """Returns 400 when name is missing."""
        router = self._create_router(tmp_path)
        handler = self._find_endpoint(router, "/api/control/bg-worker/trigger")
        resp = await handler({})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_trigger_no_orchestrator(self, tmp_path: Path) -> None:
        """Returns 400 when orchestrator is not available."""
        router = self._create_router(tmp_path)
        handler = self._find_endpoint(router, "/api/control/bg-worker/trigger")
        resp = await handler({"name": "memory_sync"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_trigger_unknown_worker(self, tmp_path: Path) -> None:
        """Returns 404 for an unknown worker name."""
        orch = MagicMock()
        orch.trigger_bg_worker.return_value = False
        router = self._create_router(tmp_path, orch=orch)
        handler = self._find_endpoint(router, "/api/control/bg-worker/trigger")
        resp = await handler({"name": "nonexistent"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_trigger_success(self, tmp_path: Path) -> None:
        """Returns 200 with ok status for a valid worker."""
        import json

        orch = MagicMock()
        orch.trigger_bg_worker.return_value = True
        router = self._create_router(tmp_path, orch=orch)
        handler = self._find_endpoint(router, "/api/control/bg-worker/trigger")
        resp = await handler({"name": "memory_sync"})
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["status"] == "ok"
        assert body["name"] == "memory_sync"
        orch.trigger_bg_worker.assert_called_once_with("memory_sync")
