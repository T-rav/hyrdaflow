"""Dual-backend dedup set store (Dolt or file-backed JSON)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dolt_backend import DoltBackend

logger = logging.getLogger("hydraflow.dedup_store")


class DedupStore:
    """Dedup tracking set backed by Dolt or a local JSON file."""

    def __init__(
        self,
        set_name: str,
        file_path: Path,
        *,
        dolt: DoltBackend | None = None,
    ) -> None:
        self._set_name = set_name
        self._file_path = file_path
        self._dolt = dolt

    def get(self) -> set[str]:
        if self._dolt:
            return self._dolt.get_dedup_set(self._set_name)
        if not self._file_path.exists():
            return set()
        try:
            data = json.loads(self._file_path.read_text())
            return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, TypeError, OSError):
            return set()

    def add(self, value: str) -> None:
        if self._dolt:
            self._dolt.add_to_dedup_set(self._set_name, value)
            return
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
        if self._dolt:
            self._dolt.set_dedup_set(self._set_name, values)
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._file_path.write_text(json.dumps(sorted(values)))
        except OSError:
            logger.warning(
                "Could not write dedup set %s", self._set_name, exc_info=True
            )
