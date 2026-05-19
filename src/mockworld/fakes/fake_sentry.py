"""Stateful Sentry fake for scenario testing.

Implements ``ObservabilityPort`` so it can be used wherever the injected port
is consumed, and scenario tests can assert on what was recorded.

Also keeps legacy ``add_breadcrumb`` / ``set_tag`` methods so that existing
scenario tests and ``SentryPort`` conformance checks continue to pass during
the migration period (ADR-0044 P7.7 rollout).
"""

from __future__ import annotations

from typing import Any


class FakeSentry:
    """Captures observability events for in-process assertion.

    Satisfies the ``ObservabilityPort`` protocol — every public method matches
    the port's signature so ``isinstance(fake, ObservabilityPort)`` returns
    True and signature-conformance tests pass.

    Also satisfies the legacy ``SentryPort`` used in scenario tests via the
    ``add_breadcrumb`` / ``set_tag`` compat shims.
    """

    _is_fake_adapter = True

    def __init__(self) -> None:
        self.breadcrumbs: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.measurements: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # ObservabilityPort methods
    # ------------------------------------------------------------------

    def capture_exception(self, exc: BaseException) -> None:
        self.events.append({"type": "exception", "error": str(exc)})

    def capture_message(self, message: str, *, level: str = "info") -> None:
        self.events.append({"type": "message", "message": message, "level": level})

    def breadcrumb(self, category: str, message: str, **data: object) -> None:
        self.breadcrumbs.append({"category": category, "message": message, **data})

    def set_measurement(self, name: str, value: float, unit: str = "") -> None:
        self.measurements.append({"name": name, "value": value, "unit": unit})

    def flush(self, timeout_ms: int = 2000) -> bool:
        return True

    # ------------------------------------------------------------------
    # Legacy SentryPort shims (kept for scenario-test compatibility)
    # ------------------------------------------------------------------

    def add_breadcrumb(self, **kwargs: Any) -> None:
        """Legacy shim — maps to ``breadcrumb()`` for backwards compat."""
        category = str(kwargs.pop("category", ""))
        message = str(kwargs.pop("message", ""))
        self.breadcrumbs.append({"category": category, "message": message, **kwargs})

    def set_tag(self, key: str, value: str) -> None:
        """Legacy shim — records as a breadcrumb with type='tag'."""
        self.breadcrumbs.append({"type": "tag", "key": key, "value": value})
