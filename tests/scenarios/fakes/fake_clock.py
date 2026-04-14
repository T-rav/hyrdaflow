"""Controllable clock for scenario testing."""

from __future__ import annotations

import asyncio


class FakeClock:
    """Deterministic clock that advances only when told to."""

    def __init__(self, start: float = 0.0) -> None:
        self._time = start

    def now(self) -> float:
        return self._time

    def monotonic(self) -> float:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += seconds

    async def sleep(self, seconds: float) -> None:
        self._time += seconds
        await asyncio.sleep(0)  # yield to event loop

    def install_subprocess_clock(self) -> None:
        from subprocess_util import set_time_source  # noqa: PLC0415

        set_time_source(self.now)

    def uninstall_subprocess_clock(self) -> None:
        from subprocess_util import reset_time_source  # noqa: PLC0415

        reset_time_source()
