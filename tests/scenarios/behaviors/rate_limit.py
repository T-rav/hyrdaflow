"""RateLimited — wraps any port and injects RateLimitExceeded after budget exhaustion.

Scoped to methods listed in the ``methods`` kwarg. Other methods pass through
unchanged. Call ``refill()`` to reset the budget in tests.
"""

from __future__ import annotations

from typing import Any


class RateLimitExceeded(Exception):
    """Raised when the wrapped port exhausts its rate-limit budget."""


class RateLimited:
    """Budget-bounded wrapper that passes calls through to a wrapped port.

    ``RateLimited(port, budget=5, methods=["get_pr_diff"])`` decrements the
    budget on each listed method call; raises ``RateLimitExceeded`` when
    budget hits zero. Unlisted methods are not metered.
    """

    def __init__(
        self,
        wrapped: Any,
        *,
        budget: int,
        methods: list[str] | None = None,
    ) -> None:
        self._wrapped = wrapped
        self._initial_budget = budget
        self._remaining = budget
        self._methods = set(methods or [])

    def refill(self) -> None:
        self._remaining = self._initial_budget

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._wrapped, name)
        if name not in self._methods:
            return attr
        # Intercept — decrement budget before delegating.
        if callable(attr):
            remaining = self._remaining
            self_ref = self

            if _is_coroutine_method(attr):

                async def _gated_async(*args: Any, **kwargs: Any) -> Any:
                    if self_ref._remaining <= 0:
                        msg = (
                            f"rate-limit budget exhausted on {name!r} "
                            f"(initial={self_ref._initial_budget})"
                        )
                        raise RateLimitExceeded(msg)
                    self_ref._remaining -= 1
                    return await attr(*args, **kwargs)  # pyright: ignore[reportGeneralTypeIssues]

                return _gated_async

            def _gated_sync(*args: Any, **kwargs: Any) -> Any:
                if self_ref._remaining <= 0:
                    msg = (
                        f"rate-limit budget exhausted on {name!r} "
                        f"(initial={self_ref._initial_budget})"
                    )
                    raise RateLimitExceeded(msg)
                self_ref._remaining -= 1
                return attr(*args, **kwargs)

            _ = remaining  # silence unused
            return _gated_sync
        return attr


def _is_coroutine_method(fn: Any) -> bool:
    import asyncio  # noqa: PLC0415

    return asyncio.iscoroutinefunction(fn)
