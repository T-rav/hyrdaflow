"""Stateful Hindsight fake for scenario testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class _MemoryEntry:
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeHindsight:
    """In-memory Hindsight fake with per-bank storage and fail mode.

    Implements ``HindsightPort`` exactly — signatures match the port contract
    so ``isinstance(..., HindsightPort)`` is meaningful at call-time too.
    """

    def __init__(self) -> None:
        self._banks: dict[str, list[_MemoryEntry]] = {}
        self._failing = False

    def set_failing(self, failing: bool) -> None:
        self._failing = failing

    @property
    def is_failing(self) -> bool:
        return self._failing

    def _check_health(self) -> None:
        if self._failing:
            msg = "FakeHindsight is in fail mode"
            raise ConnectionError(msg)

    async def retain(
        self,
        bank: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._check_health()
        self._banks.setdefault(bank, []).append(
            _MemoryEntry(content=content, metadata=dict(metadata) if metadata else {})
        )

    async def recall(
        self, bank: str, query: str, *, top_k: int = 5
    ) -> list[dict[str, Any]]:
        _ = query
        self._check_health()
        entries = self._banks.get(bank, [])[:top_k]
        return [{"content": e.content, "metadata": e.metadata} for e in entries]

    async def reflect(self, bank: str, prompt: str) -> str:
        _ = (bank, prompt)
        self._check_health()
        return ""

    def bank_entries(self, bank: str) -> list[dict[str, Any]]:
        return [
            {"content": e.content, "metadata": e.metadata}
            for e in self._banks.get(bank, [])
        ]
