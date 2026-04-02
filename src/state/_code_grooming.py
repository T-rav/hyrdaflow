"""State accessors for code grooming settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import CodeGroomingSettings

if TYPE_CHECKING:
    from models import StateData


class CodeGroomingStateMixin:
    """Mixed into StateTracker for code grooming settings persistence."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_code_grooming_settings(self) -> CodeGroomingSettings:
        """Return current code grooming settings."""
        return CodeGroomingSettings.model_validate(
            self._data.code_grooming_settings.model_dump()
        )

    def set_code_grooming_settings(self, settings: CodeGroomingSettings) -> None:
        """Persist code grooming settings."""
        self._data.code_grooming_settings = settings
        self.save()

    def get_code_grooming_filed(self) -> set[str]:
        """Return set of issue keys already filed by the code grooming worker."""
        return set(self._data.code_grooming_filed)

    def add_code_grooming_filed(self, key: str) -> None:
        """Mark a finding as filed (to avoid duplicates)."""
        current = set(self._data.code_grooming_filed)
        current.add(key)
        self._data.code_grooming_filed = sorted(current)
        self.save()
