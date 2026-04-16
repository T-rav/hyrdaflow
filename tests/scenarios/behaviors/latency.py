"""Latency — advances a test clock for each call to a listed method."""

from __future__ import annotations

import asyncio
from typing import Any


class Latency:
    def __init__(
        self,
        wrapped: Any,
        *,
        clock: Any,
        delay_seconds: float,
        methods: list[str] | None = None,
    ) -> None:
        self._wrapped = wrapped
        self._clock = clock
        self._delay = delay_seconds
        self._methods = set(methods or [])

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._wrapped, name)
        if name not in self._methods or not callable(attr):
            return attr

        if asyncio.iscoroutinefunction(attr):

            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                self._clock.advance(self._delay)
                return await attr(*args, **kwargs)  # pyright: ignore[reportGeneralTypeIssues]

            return _async_wrapper

        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            self._clock.advance(self._delay)
            return attr(*args, **kwargs)

        return _sync_wrapper
