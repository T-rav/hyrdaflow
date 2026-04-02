"""State accessors for stale issue cleanup settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import StaleIssueSettings

if TYPE_CHECKING:
    from models import StateData


class StaleIssueStateMixin:
    """Mixed into StateTracker for stale issue settings persistence."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_stale_issue_settings(self) -> StaleIssueSettings:
        """Return current stale issue settings."""
        return StaleIssueSettings.model_validate(
            self._data.stale_issue_settings.model_dump()
        )

    def set_stale_issue_settings(self, settings: StaleIssueSettings) -> None:
        """Persist stale issue settings."""
        self._data.stale_issue_settings = settings
        self.save()

    def get_stale_issue_closed(self) -> set[int]:
        """Return set of issue numbers closed by the stale issue worker."""
        return set(self._data.stale_issue_closed)

    def add_stale_issue_closed(self, issue_number: int) -> None:
        """Mark an issue as closed by the stale issue worker."""
        current = set(self._data.stale_issue_closed)
        current.add(issue_number)
        self._data.stale_issue_closed = sorted(current)
        self.save()
