"""Base class for background worker loops.

Extracts the shared run-loop, error handling, success reporting,
interval management, and enabled-check logic that was previously
duplicated across memory_sync_loop, metrics_sync_loop,
pr_unsticker_loop, and manifest_refresh_loop.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from models import StatusCallback
from subprocess_util import AuthenticationError, CreditExhaustedError

logger = logging.getLogger("hydraflow.base_background_loop")


class BaseBackgroundLoop(abc.ABC):
    """Abstract base for background worker loops.

    Subclasses implement :meth:`_do_work` (domain-specific logic) and
    :meth:`_get_default_interval` (config-driven default interval).
    The base class handles the run loop, enabled check, error reporting,
    status publishing, and interval management.
    """

    def __init__(
        self,
        *,
        worker_name: str,
        config: HydraFlowConfig,
        bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: StatusCallback,
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
        run_on_startup: bool = False,
    ) -> None:
        self._worker_name = worker_name
        self._config = config
        self._bus = bus
        self._stop_event = stop_event
        self._status_cb = status_cb
        self._enabled_cb = enabled_cb
        self._sleep_fn = sleep_fn
        self._interval_cb = interval_cb
        self._run_on_startup = run_on_startup

    @abc.abstractmethod
    async def _do_work(self) -> dict[str, Any] | None:
        """Execute one cycle of domain-specific work.

        Returns an optional stats/details dict to include in the
        BACKGROUND_WORKER_STATUS event.
        """

    @abc.abstractmethod
    def _get_default_interval(self) -> int:
        """Return the config-driven default interval in seconds."""

    def _get_interval(self) -> int:
        """Return the effective interval, preferring dynamic override."""
        if self._interval_cb is not None:
            return self._interval_cb(self._worker_name)
        return self._get_default_interval()

    def _build_details(self, stats: dict[str, Any] | None) -> dict[str, Any]:
        """Coerce arbitrary worker stats into a details dict."""
        if stats is None:
            return {}
        if isinstance(stats, dict):
            return dict(stats)
        return {"value": stats}

    async def _execute_cycle(self) -> None:
        """Execute one work cycle with error handling and status reporting."""
        try:
            stats = await self._do_work()
            details = self._build_details(stats)
            last_run = datetime.now(UTC).isoformat()
            self._status_cb(self._worker_name, "ok", details)
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BACKGROUND_WORKER_STATUS,
                    data={
                        "worker": self._worker_name,
                        "status": "ok",
                        "last_run": last_run,
                        "details": details,
                    },
                )
            )
        except (AuthenticationError, CreditExhaustedError):
            raise
        except Exception:
            logger.exception(
                "%s loop iteration failed — will retry next cycle",
                self._worker_name.replace("_", " ").capitalize(),
            )
            last_run = datetime.now(UTC).isoformat()
            self._status_cb(self._worker_name, "error", {})
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BACKGROUND_WORKER_STATUS,
                    data={
                        "worker": self._worker_name,
                        "status": "error",
                        "last_run": last_run,
                        "details": {},
                    },
                )
            )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.ERROR,
                    data={
                        "message": f"{self._worker_name.replace('_', ' ').capitalize()} loop error",
                        "source": self._worker_name,
                    },
                )
            )

    async def run(self) -> None:
        """Run the background worker loop until the stop event is set."""
        if self._run_on_startup:
            await self._execute_cycle()

        while not self._stop_event.is_set():
            interval = self._get_interval()
            if self._run_on_startup:
                await self._sleep_fn(interval)
                if self._stop_event.is_set():
                    break
                if not self._enabled_cb(self._worker_name):
                    continue
            elif not self._enabled_cb(self._worker_name):
                await self._sleep_fn(interval)
                continue
            await self._execute_cycle()
            if not self._run_on_startup:
                await self._sleep_fn(interval)
