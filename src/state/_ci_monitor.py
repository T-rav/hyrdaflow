"""State accessors for CI monitor settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import CIMonitorSettings

if TYPE_CHECKING:
    from models import StateData


class CIMonitorStateMixin:
    """Mixed into StateTracker for CI monitor settings persistence."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_ci_monitor_settings(self) -> CIMonitorSettings:
        """Return current CI monitor settings."""
        return CIMonitorSettings.model_validate(
            self._data.ci_monitor_settings.model_dump()
        )

    def set_ci_monitor_settings(self, settings: CIMonitorSettings) -> None:
        """Persist CI monitor settings."""
        self._data.ci_monitor_settings = settings
        self.save()

    def get_ci_monitor_tracked_failures(self) -> dict[str, str]:
        """Return dict of tracked CI failures (workflow -> run_id)."""
        return dict(self._data.ci_monitor_tracked_failures)

    def set_ci_monitor_tracked_failures(self, failures: dict[str, str]) -> None:
        """Persist tracked CI failures."""
        self._data.ci_monitor_tracked_failures = failures
        self.save()

    def clear_ci_monitor_failure(self, workflow: str) -> None:
        """Remove a tracked failure for a workflow."""
        failures = dict(self._data.ci_monitor_tracked_failures)
        failures.pop(workflow, None)
        self._data.ci_monitor_tracked_failures = failures
        self.save()
