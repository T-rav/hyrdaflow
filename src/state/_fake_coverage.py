"""State accessors for FakeCoverageAuditorLoop (spec §4.7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class FakeCoverageStateMixin:
    """Last-known covered method list + per-gap repair attempts."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_fake_coverage_last_known(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._data.fake_coverage_last_known.items()}

    def set_fake_coverage_last_known(self, known: dict[str, list[str]]) -> None:
        self._data.fake_coverage_last_known = {k: list(v) for k, v in known.items()}
        self.save()

    def get_fake_coverage_attempts(self, key: str) -> int:
        return int(self._data.fake_coverage_attempts.get(key, 0))

    def inc_fake_coverage_attempts(self, key: str) -> int:
        current = int(self._data.fake_coverage_attempts.get(key, 0)) + 1
        attempts = dict(self._data.fake_coverage_attempts)
        attempts[key] = current
        self._data.fake_coverage_attempts = attempts
        self.save()
        return current

    def clear_fake_coverage_attempts(self, key: str) -> None:
        attempts = dict(self._data.fake_coverage_attempts)
        attempts.pop(key, None)
        self._data.fake_coverage_attempts = attempts
        self.save()
