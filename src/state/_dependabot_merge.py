"""State accessors for bot PR auto-merge settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import DependabotMergeSettings

if TYPE_CHECKING:
    from models import StateData


class DependabotMergeStateMixin:
    """Mixed into StateTracker for bot PR settings persistence."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_dependabot_merge_settings(self) -> DependabotMergeSettings:
        """Return current bot PR settings."""
        return DependabotMergeSettings.model_validate(
            self._data.dependabot_merge_settings.model_dump()
        )

    def set_dependabot_merge_settings(self, settings: DependabotMergeSettings) -> None:
        """Persist bot PR settings."""
        self._data.dependabot_merge_settings = settings
        self.save()

    def get_dependabot_merge_processed(self) -> set[int]:
        """Return set of PR numbers already processed by the bot PR worker."""
        return set(self._data.dependabot_merge_processed)

    def add_dependabot_merge_processed(self, pr_number: int) -> None:
        """Mark a PR as processed (merged, closed, or escalated)."""
        current = set(self._data.dependabot_merge_processed)
        current.add(pr_number)
        self._data.dependabot_merge_processed = sorted(current)
        self.save()
