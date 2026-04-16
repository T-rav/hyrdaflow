"""Quota — simulates Anthropic credit exhaustion.

Decrements a budget per listed method call. On exhaustion, raises
``QuotaExceeded`` with a ``resume_at`` attribute (future timestamp string).
"""

from __future__ import annotations

import asyncio
from typing import Any


class QuotaExceeded(Exception):
    def __init__(self, message: str, *, resume_at: str) -> None:
        super().__init__(message)
        self.resume_at = resume_at


class Quota:
    def __init__(
        self,
        wrapped: Any,
        *,
        budget: int,
        methods: list[str] | None = None,
        resume_at: str = "2099-01-01T00:00:00Z",
    ) -> None:
        self._wrapped = wrapped
        self._initial_budget = budget
        self._remaining = budget
        self._methods = set(methods or [])
        self._resume_at = resume_at

    @property
    def remaining(self) -> int:
        return self._remaining

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._wrapped, name)
        if name not in self._methods or not callable(attr):
            return attr

        if asyncio.iscoroutinefunction(attr):

            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if self._remaining <= 0:
                    msg = f"quota exhausted on {name!r} (resume_at={self._resume_at})"
                    raise QuotaExceeded(msg, resume_at=self._resume_at)
                self._remaining -= 1
                return await attr(*args, **kwargs)  # pyright: ignore[reportGeneralTypeIssues]

            return _async_wrapper

        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if self._remaining <= 0:
                msg = f"quota exhausted on {name!r} (resume_at={self._resume_at})"
                raise QuotaExceeded(msg, resume_at=self._resume_at)
            self._remaining -= 1
            return attr(*args, **kwargs)

        return _sync_wrapper
