"""State accessors for WikiRotDetectorLoop (spec §4.9).

Per-cite repair attempt counters. The key format is
``f"{slug}:{cite}"`` so that the same broken cite across two repos counts
independently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class WikiRotDetectorStateMixin:
    """Per-cite repair attempts for WikiRotDetectorLoop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_wiki_rot_attempts(self, key: str) -> int:
        return int(self._data.wiki_rot_attempts.get(key, 0))

    def inc_wiki_rot_attempts(self, key: str) -> int:
        current = int(self._data.wiki_rot_attempts.get(key, 0)) + 1
        attempts = dict(self._data.wiki_rot_attempts)
        attempts[key] = current
        self._data.wiki_rot_attempts = attempts
        self.save()
        return current

    def clear_wiki_rot_attempts(self, key: str) -> None:
        attempts = dict(self._data.wiki_rot_attempts)
        attempts.pop(key, None)
        self._data.wiki_rot_attempts = attempts
        self.save()
