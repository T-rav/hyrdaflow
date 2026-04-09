"""Controllable clock for scenario testing."""

from __future__ import annotations

import asyncio


class FakeClock:
    """Deterministic clock that advances only when told to."""

    def __init__(self, start: float = 0.0) -> None:
        self._time = start

    def now(self) -> float:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += seconds

    async def sleep(self, seconds: float) -> None:
        self._time += seconds
        await asyncio.sleep(0)  # yield to event loop
