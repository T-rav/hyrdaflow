"""State accessors for security patch settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import SecurityPatchSettings

if TYPE_CHECKING:
    from models import StateData


class SecurityPatchStateMixin:
    """Mixed into StateTracker for security patch settings persistence."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_security_patch_settings(self) -> SecurityPatchSettings:
        """Return current security patch settings."""
        return SecurityPatchSettings.model_validate(
            self._data.security_patch_settings.model_dump()
        )

    def set_security_patch_settings(self, settings: SecurityPatchSettings) -> None:
        """Persist security patch settings."""
        self._data.security_patch_settings = settings
        self.save()

    def get_security_patch_processed(self) -> set[str]:
        """Return set of alert IDs already processed."""
        return set(self._data.security_patch_processed)

    def add_security_patch_processed(self, alert_id: str) -> None:
        """Mark an alert as processed."""
        current = set(self._data.security_patch_processed)
        current.add(alert_id)
        self._data.security_patch_processed = sorted(current)
        self.save()
