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

    def freeze(self, ts: float | str) -> None:
        """Pin ``now()`` at a fixed timestamp.

        Accepts either a unix float or an ISO-8601 string with an explicit
        UTC marker (Z or +00:00). Naive datetime strings are rejected so
        tests fail loud on ambiguity.
        """
        if isinstance(ts, str):
            from datetime import datetime  # noqa: PLC0415

            if "Z" not in ts and "+" not in ts and "-" not in ts[10:]:
                raise ValueError(
                    f"freeze() requires a timezone-aware timestamp, got: {ts!r}"
                )
            normalized = ts.replace("Z", "+00:00")
            self._time = datetime.fromisoformat(normalized).timestamp()
        else:
            self._time = float(ts)

    def install_subprocess_clock(self) -> None:
        from subprocess_util import set_time_source  # noqa: PLC0415

        set_time_source(self.now)

    def uninstall_subprocess_clock(self) -> None:
        from subprocess_util import reset_time_source  # noqa: PLC0415

        reset_time_source()
