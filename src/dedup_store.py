"""File-backed dedup set store."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("hydraflow.dedup_store")


class DedupStore:
    """Dedup tracking set persisted as a sorted JSON list."""

    def __init__(self, set_name: str, file_path: Path) -> None:
        self._set_name = set_name
        self._file_path = file_path

    def get(self) -> set[str]:
        if not self._file_path.exists():
            return set()
        try:
            data = json.loads(self._file_path.read_text())
            return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, TypeError, OSError):
            return set()

    def add(self, value: str) -> None:
        current = self.get()
        current.add(value)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._file_path.write_text(json.dumps(sorted(current)))
        except OSError:
            logger.warning(
                "Could not write dedup set %s", self._set_name, exc_info=True
            )

    def set_all(self, values: set[str]) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._file_path.write_text(json.dumps(sorted(values)))
        except OSError:
            logger.warning(
                "Could not write dedup set %s", self._set_name, exc_info=True
            )
