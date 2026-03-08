"""Tests for the BaseBackgroundLoop ABC."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import BaseBackgroundLoop
from events import EventBus, EventType
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import ConfigFactory


class _StubLoop(BaseBackgroundLoop):
    """Concrete subclass for testing the base class."""

    def __init__(
        self,
        *,
        work_fn: Any = None,
        default_interval: int = 60,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._work_fn = work_fn or (lambda: {"stub": True})
        self._default_interval = default_interval

    async def _do_work(self) -> dict[str, Any] | None:
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
    interval_cb: Any = None,
    run_on_startup: bool = False,
) -> tuple[_StubLoop, asyncio.Event]:
    """Build a _StubLoop with test-friendly defaults."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    bus = EventBus()
    stop_event = asyncio.Event()

    call_count = 0

    async def instant_sleep(_seconds: int | float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        await asyncio.sleep(0)

    loop = _StubLoop(
        work_fn=work_fn,
        default_interval=default_interval,
        worker_name="test_worker",
        config=config,
        bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _name: enabled,
        sleep_fn=instant_sleep,
        interval_cb=interval_cb,
        run_on_startup=run_on_startup,
    )
    return loop, stop_event


class TestBaseBackgroundLoopRun:
    """Tests for the base run loop mechanics."""

    @pytest.mark.asyncio
    async def test_run__calls_do_work_and_reports_success(self, tmp_path: Path) -> None:
        """The loop calls _do_work and reports success via status_cb and bus."""
        loop, _stop = _make_stub(tmp_path, work_fn=lambda: {"count": 5})

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "test_worker"
        assert args[1] == "ok"
        assert args[2] == {"count": 5}

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        assert events[0].data["worker"] == "test_worker"
        assert events[0].data["status"] == "ok"
        assert events[0].data["details"] == {"count": 5}

    @pytest.mark.asyncio
    async def test_run__handles_error_and_publishes_events(
        self, tmp_path: Path
    ) -> None:
        """The loop handles errors, calls status_cb with 'error', and publishes events."""
        loop, _stop = _make_stub(
            tmp_path, work_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "test_worker"
        assert args[1] == "error"

        history = loop._bus.get_history()
        worker_events = [
            e for e in history if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        error_events = [e for e in history if e.type == EventType.ERROR]

        assert len(worker_events) >= 1
        assert worker_events[0].data["status"] == "error"
        assert len(error_events) >= 1
        assert error_events[0].data["source"] == "test_worker"

    @pytest.mark.asyncio
    async def test_run__skips_when_disabled(self, tmp_path: Path) -> None:
        """The loop skips work when the enabled callback returns False."""
        loop, _stop = _make_stub(tmp_path, enabled=False)

        await loop.run()

        loop._status_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_run__continues_after_error(self, tmp_path: Path) -> None:
        """The loop survives exceptions and retries on the next cycle."""
        call_count = 0

        def fail_then_succeed() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient")
            return {"ok": True}

        loop, _stop = _make_stub(tmp_path, work_fn=fail_then_succeed)

        await loop.run()

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run__reraises_authentication_error(self, tmp_path: Path) -> None:
        """AuthenticationError is re-raised and not caught by the generic handler."""

        def raise_auth() -> None:
            raise AuthenticationError("bad token")

        loop, _stop = _make_stub(tmp_path, work_fn=raise_auth)

        with pytest.raises(AuthenticationError, match="bad token"):
            await loop.run()

    @pytest.mark.asyncio
    async def test_run__reraises_credit_exhausted_error(self, tmp_path: Path) -> None:
        """CreditExhaustedError is re-raised and not caught by the generic handler."""

        def raise_credit() -> None:
            raise CreditExhaustedError("no credits")

        loop, _stop = _make_stub(tmp_path, work_fn=raise_credit)

        with pytest.raises(CreditExhaustedError, match="no credits"):
            await loop.run()

    @pytest.mark.asyncio
    async def test_run__do_work_returning_none_uses_empty_details(
        self, tmp_path: Path
    ) -> None:
        """When _do_work returns None, the event details default to {}."""
        loop, _stop = _make_stub(tmp_path, work_fn=lambda: None)

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert events[0].data["details"] == {}


class TestBaseBackgroundLoopInterval:
    """Tests for interval handling."""

    def test_get_interval__uses_default_interval(self, tmp_path: Path) -> None:
        """Without a callback, _get_interval returns _get_default_interval()."""
        loop, _ = _make_stub(tmp_path, default_interval=300)
        assert loop._get_interval() == 300

    def test_get_interval__prefers_callback(self, tmp_path: Path) -> None:
        """With a callback, _get_interval uses the callback result."""
        loop, _ = _make_stub(
            tmp_path, default_interval=300, interval_cb=lambda _name: 42
        )
        assert loop._get_interval() == 42


class TestBaseBackgroundLoopTrigger:
    """Tests for the trigger() method and _sleep_or_trigger() helper."""

    @pytest.mark.asyncio
    async def test_trigger__skips_sleep(self, tmp_path: Path) -> None:
        """trigger() causes _sleep_or_trigger to return True immediately."""
        loop, _ = _make_stub(tmp_path)
        loop.trigger()
        triggered = await loop._sleep_or_trigger(60)
        assert triggered is True

    @pytest.mark.asyncio
    async def test_sleep_or_trigger__returns_false_on_normal_sleep(
        self, tmp_path: Path
    ) -> None:
        """Without a trigger, _sleep_or_trigger returns False after sleeping."""
        loop, _ = _make_stub(tmp_path)
        triggered = await loop._sleep_or_trigger(0)
        assert triggered is False

    @pytest.mark.asyncio
    async def test_trigger__during_work_is_not_dropped(self, tmp_path: Path) -> None:
        """A trigger fired during _execute_cycle skips the following sleep."""
        loop, _ = _make_stub(tmp_path)

        # Simulate trigger fired during the work phase
        loop.trigger()

        # _sleep_or_trigger should notice the pre-set event and return immediately
        triggered = await loop._sleep_or_trigger(9999)
        assert triggered is True

    @pytest.mark.asyncio
    async def test_trigger__wakes_sleeping_loop(self, tmp_path: Path) -> None:
        """trigger() interrupts an in-progress sleep and returns True."""
        loop, _ = _make_stub(tmp_path)

        async def real_sleep(seconds: int | float) -> None:
            await asyncio.sleep(seconds)

        loop._sleep_fn = real_sleep  # use real sleep so we can interrupt it

        async def fire_trigger() -> None:
            await asyncio.sleep(0.01)
            loop.trigger()

        asyncio.create_task(fire_trigger())
        triggered = await loop._sleep_or_trigger(9999)
        assert triggered is True

    @pytest.mark.asyncio
    async def test_trigger__non_startup_disabled_worker_still_runs(
        self, tmp_path: Path
    ) -> None:
        """With run_on_startup=False, trigger bypasses disabled check and runs work."""
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        bus = EventBus()
        stop_event = asyncio.Event()
        call_count = 0

        def counting_work() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"n": call_count}

        async def single_sleep(_seconds: int | float) -> None:
            # Stop after first sleep so the loop exits
            stop_event.set()
            await asyncio.sleep(0)

        loop = _StubLoop(
            work_fn=counting_work,
            worker_name="test_worker",
            config=config,
            bus=bus,
            stop_event=stop_event,
            status_cb=MagicMock(),
            enabled_cb=lambda _: False,  # always disabled
            sleep_fn=single_sleep,
            run_on_startup=False,
        )
        # Trigger before run so _sleep_or_trigger returns True during disabled check
        loop.trigger()
        await loop.run()

        # Trigger bypasses disabled check and work executes once
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_trigger__run_on_startup_disabled_worker_still_runs(
        self, tmp_path: Path
    ) -> None:
        """With run_on_startup=True, trigger bypasses disabled check and runs work."""
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        bus = EventBus()
        stop_event = asyncio.Event()
        call_count = 0

        def counting_work() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"n": call_count}

        async def single_sleep(_seconds: int | float) -> None:
            # Immediately stop after first sleep so the loop exits
            stop_event.set()
            await asyncio.sleep(0)

        loop = _StubLoop(
            work_fn=counting_work,
            worker_name="test_worker",
            config=config,
            bus=bus,
            stop_event=stop_event,
            status_cb=MagicMock(),
            enabled_cb=lambda _: False,  # always disabled
            sleep_fn=single_sleep,
            run_on_startup=True,
        )
        # Trigger before run so it fires immediately in _sleep_or_trigger
        loop.trigger()
        await loop.run()

        # Startup run (call_count=1) + trigger bypasses disabled (call_count=2)
        assert call_count == 2


class TestBaseBackgroundLoopRunOnStartup:
    """Tests for the run_on_startup flag."""

    @pytest.mark.asyncio
    async def test_run__run_on_startup_executes_immediately(
        self, tmp_path: Path
    ) -> None:
        """With run_on_startup=True, _do_work is called before the first sleep."""
        loop, stop = _make_stub(tmp_path, run_on_startup=True)
        # Stop immediately so only the startup execution runs
        stop.set()

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "test_worker"
        assert args[1] == "ok"

    @pytest.mark.asyncio
    async def test_run__run_on_startup_skips_disabled_in_loop_body(
        self, tmp_path: Path
    ) -> None:
        """With run_on_startup=True and disabled, initial run still executes."""
        call_count = 0

        def counting_work() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"n": call_count}

        loop, _stop = _make_stub(
            tmp_path, enabled=False, run_on_startup=True, work_fn=counting_work
        )

        await loop.run()

        # Initial startup execution always runs; loop body skipped when disabled
        assert call_count == 1
