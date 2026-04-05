"""Sentry ingestion state — creation attempt tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class SentryStateMixin:
    """State methods for the Sentry ingestion loop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def fail_sentry_creation(self, sentry_id: str) -> int:
        """Increment creation attempt count for a Sentry issue. Returns new count."""
        current = self._data.sentry_creation_attempts.get(sentry_id, 0)
        current += 1
        self._data.sentry_creation_attempts[sentry_id] = current
        self.save()
        return current

    def get_sentry_creation_attempts(self, sentry_id: str) -> int:
        """Return the number of creation attempts for a Sentry issue."""
        return self._data.sentry_creation_attempts.get(sentry_id, 0)

    def clear_sentry_creation_attempts(self, sentry_id: str) -> None:
        """Clear creation attempt tracking for a Sentry issue."""
        self._data.sentry_creation_attempts.pop(sentry_id, None)
        self.save()
