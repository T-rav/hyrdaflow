"""Stateful Hindsight fake for scenario testing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _MemoryEntry:
    key: str
    content: str


class FakeHindsight:
    """In-memory Hindsight fake with per-bank storage and fail mode."""

    def __init__(self) -> None:
        self._banks: dict[str, list[_MemoryEntry]] = {}
        self._failing = False

    def set_failing(self, failing: bool) -> None:
        self._failing = failing

    def _check_health(self) -> None:
        if self._failing:
            msg = "FakeHindsight is in fail mode"
            raise ConnectionError(msg)

    async def retain(self, bank: str, key: str, content: str) -> dict:
        self._check_health()
        self._banks.setdefault(bank, []).append(_MemoryEntry(key=key, content=content))
        return {}

    async def recall(self, bank: str, _query: str) -> list[dict]:
        self._check_health()
        entries = self._banks.get(bank, [])
        return [{"key": e.key, "content": e.content} for e in entries]

    async def reflect(self, bank: str, _query: str) -> str:
        self._check_health()
        _ = bank
        return ""

    def bank_entries(self, bank: str) -> list[dict]:
        return [{"key": e.key, "content": e.content} for e in self._banks.get(bank, [])]
