"""Stateful Sentry fake for scenario testing."""

from __future__ import annotations

from typing import Any


class FakeSentry:
    """Captures breadcrumbs and events for assertion."""

    _is_fake_adapter = True

    def __init__(self) -> None:
        self.breadcrumbs: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def add_breadcrumb(self, **kwargs: Any) -> None:
        self.breadcrumbs.append(kwargs)

    def capture_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def capture_exception(self, error: Exception | None = None) -> None:
        self.events.append({"type": "exception", "error": str(error)})

    def capture_message(self, message: str, **kwargs: Any) -> None:
        self.events.append({"type": "message", "message": message, **kwargs})

    def set_tag(self, key: str, value: str) -> None:
        self.breadcrumbs.append({"type": "tag", "key": key, "value": value})
