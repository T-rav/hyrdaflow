"""Declarative registration for background loops used by scenario tests.

Each loop module imports ``register_loop`` and decorates a builder function
that takes (ports, config, deps) and returns a ``BaseBackgroundLoop`` instance.
Scenario tests call ``LoopCatalog.instantiate("name", ports=..., config=..., deps=...)``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

LoopBuilder = Callable[[dict[str, Any], Any, Any], Any]


class LoopCatalog:
    _registry: dict[str, LoopBuilder] = {}

    @classmethod
    def register(cls, name: str, builder: LoopBuilder) -> None:
        if name in cls._registry:
            msg = f"Loop {name!r} already registered"
            raise ValueError(msg)
        cls._registry[name] = builder

    @classmethod
    def is_registered(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def instantiate(
        cls,
        name: str,
        *,
        ports: dict[str, Any],
        config: Any,
        deps: Any,
    ) -> Any:
        if name not in cls._registry:
            msg = f"Unknown loop: {name!r}; registered: {sorted(cls._registry)}"
            raise KeyError(msg)
        return cls._registry[name](ports, config, deps)

    @classmethod
    def registered_names(cls) -> list[str]:
        return sorted(cls._registry)

    @classmethod
    def reset(cls) -> None:
        """Clear the registry — used by unit tests that register throwaway loops."""
        cls._registry = {}


def register_loop(name: str) -> Callable[[LoopBuilder], LoopBuilder]:
    """Decorator: register a loop builder under ``name``.

    Usage::

        @register_loop("ci_monitor")
        def _build(ports, config, deps):
            return CIMonitorLoop(config=config, pr_manager=ports["github"], deps=deps)
    """

    def _decorator(builder: LoopBuilder) -> LoopBuilder:
        LoopCatalog.register(name, builder)
        return builder

    return _decorator
