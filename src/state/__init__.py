"""Crash-recovery state persistence for HydraFlow.

This package decomposes ``StateTracker`` into domain-based mixins for
maintainability while preserving the single-class public API.

Usage unchanged::

    from state import StateTracker
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError

from file_util import atomic_write, rotate_backups
from models import StateData

from ._epic import EpicStateMixin
from ._hitl import HITLStateMixin
from ._issue import IssueStateMixin
from ._lifetime import LifetimeStatsMixin
from ._report import ReportStateMixin
from ._review import ReviewStateMixin
from ._session import SessionStateMixin
from ._worker import WorkerStateMixin
from ._worktree import WorktreeStateMixin

logger = logging.getLogger("hydraflow.state")

_V = TypeVar("_V")

__all__ = ["StateTracker"]


class StateTracker(
    IssueStateMixin,
    WorktreeStateMixin,
    HITLStateMixin,
    ReviewStateMixin,
    EpicStateMixin,
    LifetimeStatsMixin,
    SessionStateMixin,
    WorkerStateMixin,
    ReportStateMixin,
):
    """JSON-file backed state for crash recovery.

    Writes ``<repo_root>/.hydraflow/state.json`` after every mutation.

    Composed from domain-specific mixins; all methods are available
    directly on this class.
    """

    # --- int↔str key conversion helpers ---

    @staticmethod
    def _key(issue_id: int | str) -> str:
        """Convert an issue/PR/epic number to the string key used in state dicts."""
        return str(issue_id)

    @staticmethod
    def _int_keys(d: dict[str, _V]) -> dict[int, _V]:
        """Return a copy of *d* with all keys converted from ``str`` to ``int``.

        Non-integer keys are skipped with a warning.
        """
        result: dict[int, _V] = {}
        for k, v in d.items():
            try:
                result[int(k)] = v
            except (ValueError, TypeError):
                logger.warning("Skipping non-integer state key: %r", k)
        return result

    def __init__(
        self,
        state_file: Path,
        *,
        backup_interval: int = 300,
        backup_count: int = 3,
    ) -> None:
        self._path = state_file
        self._data: StateData = StateData()
        self._last_backup: float = time.monotonic()
        self._backup_interval: int = backup_interval
        self._backup_count: int = backup_count
        self.load()

    # --- persistence ---

    def load(self) -> None:
        """Load state from disk, or initialise defaults.

        When the primary state file is corrupt, attempts to restore from
        the most recent ``.bak`` file before falling back to an empty
        :class:`StateData`.
        """
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text())
                if not isinstance(loaded, dict):
                    raise ValueError("State file must contain a JSON object")
                self._data = StateData.model_validate(loaded)
                logger.info("State loaded from %s", self._path)
            except (
                json.JSONDecodeError,
                OSError,
                ValueError,
                UnicodeDecodeError,
                ValidationError,
            ) as exc:
                logger.warning("Corrupt state file, resetting: %s", exc, exc_info=True)
                self._data = self._restore_from_backup() or StateData()
        self._maybe_migrate_worker_states()

    def _restore_from_backup(self) -> StateData | None:
        """Try to restore state from the newest available .bak file."""
        candidates = [Path(f"{self._path}.bak")]
        candidates.extend(
            Path(f"{self._path}.bak.{i}") for i in range(1, self._backup_count + 1)
        )
        for bak in candidates:
            if not bak.exists():
                continue
            try:
                loaded = json.loads(bak.read_text())
                if not isinstance(loaded, dict):
                    continue
                data = StateData.model_validate(loaded)
                logger.info("Restored state from backup %s", bak)
                return data
            except (
                json.JSONDecodeError,
                OSError,
                ValueError,
                UnicodeDecodeError,
                ValidationError,
            ):
                logger.debug("Backup %s also corrupt, trying next", bak, exc_info=True)
        return None

    def backup(self) -> None:
        """Create a rotated backup of the state file."""
        rotate_backups(self._path, count=self._backup_count)
        self._last_backup = time.monotonic()

    def save(self) -> None:
        """Flush current state to disk atomically.

        Automatically creates a rotated backup when more than
        ``backup_interval`` seconds have elapsed since the last backup.
        """
        now = time.monotonic()
        if now - self._last_backup >= self._backup_interval:
            self.backup()
        self._data.last_updated = datetime.now(UTC).isoformat()
        data = self._data.model_dump_json(indent=2)
        atomic_write(self._path, data)

    # --- reset ---

    def reset(self) -> None:
        """Clear all state and persist.  Lifetime stats are preserved."""
        saved_lifetime = self._data.lifetime_stats.model_copy()
        self._data = StateData(lifetime_stats=saved_lifetime)
        self.save()

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of the raw state dict."""
        return self._data.model_dump()
