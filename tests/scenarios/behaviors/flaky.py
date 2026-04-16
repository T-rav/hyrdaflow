"""Flaky — deterministic failure injection for the first N calls of listed methods."""

from __future__ import annotations

import asyncio
from typing import Any


class FlakyError(Exception):
    """Raised by Flaky decorator on scripted failure calls."""


class Flaky:
    def __init__(
        self,
        wrapped: Any,
        *,
        fail_first: int,
        methods: list[str] | None = None,
    ) -> None:
        self._wrapped = wrapped
        self._fail_first = fail_first
        self._failed_so_far = 0
        self._methods = set(methods or [])

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._wrapped, name)
        if name not in self._methods or not callable(attr):
            return attr

        if asyncio.iscoroutinefunction(attr):

            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if self._failed_so_far < self._fail_first:
                    self._failed_so_far += 1
                    msg = f"flaky failure #{self._failed_so_far} on {name!r}"
                    raise FlakyError(msg)
                return await attr(*args, **kwargs)  # pyright: ignore[reportGeneralTypeIssues]

            return _async_wrapper

        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if self._failed_so_far < self._fail_first:
                self._failed_so_far += 1
                msg = f"flaky failure #{self._failed_so_far} on {name!r}"
                raise FlakyError(msg)
            return attr(*args, **kwargs)

        return _sync_wrapper
