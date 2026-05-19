"""SentryPort — observability surface for scenario tests.

Extends the core ``ObservabilityPort`` signatures with legacy sentry_sdk
surface (``add_breadcrumb``, ``set_tag``) that scenario fakes still expose
for backwards-compatibility.
"""

from __future__ import annotations

from typing import Any, runtime_checkable

from typing_extensions import Protocol


@runtime_checkable
class SentryPort(Protocol):
    def capture_exception(self, exc: BaseException, **kwargs: Any) -> None: ...
    def capture_message(self, message: str, *, level: str = "info") -> None: ...  # noqa: E501
    def breadcrumb(self, category: str, message: str, **data: object) -> None: ...
    def set_measurement(self, name: str, value: float, unit: str = "") -> None: ...
    def flush(self, timeout_ms: int = 2000) -> bool: ...
    def add_breadcrumb(self, **kwargs: Any) -> None: ...
    def set_tag(self, key: str, value: str) -> None: ...
