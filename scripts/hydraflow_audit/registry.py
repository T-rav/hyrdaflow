"""Check function registry.

Check functions register themselves via `@register("P1.1")`. The runner
looks up each spec's check_id against this registry; a missing entry yields
a `NOT_IMPLEMENTED` finding so the ADR and the code stay in lockstep.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import CheckContext, Finding

CheckFn = Callable[[CheckContext], Finding]

_REGISTRY: dict[str, CheckFn] = {}


def register(check_id: str) -> Callable[[CheckFn], CheckFn]:
    def decorator(fn: CheckFn) -> CheckFn:
        if check_id in _REGISTRY:
            raise ValueError(f"duplicate check registration: {check_id}")
        _REGISTRY[check_id] = fn
        return fn

    return decorator


def get(check_id: str) -> CheckFn | None:
    return _REGISTRY.get(check_id)


def all_registered() -> dict[str, CheckFn]:
    return dict(_REGISTRY)


def _clear_for_tests() -> None:
    """Only for unit tests — never call in production code."""
    _REGISTRY.clear()
