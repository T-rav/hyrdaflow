"""Crash-recovery state persistence for HydraFlow.

This package decomposes ``StateTracker`` into domain-based mixins for
maintainability while preserving the single-class public API.

Usage unchanged::

    from state import StateTracker
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError

from file_util import atomic_write
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

    def __init__(self, state_file: Path) -> None:
        self._path = state_file
        self._data: StateData = StateData()
        self.load()

    # --- int↔str key conversion helpers ---

    @staticmethod
    def _key(issue_id: int) -> str:
        """Convert an integer issue/PR number to the string key used in state dicts."""
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

    # --- persistence ---

    def load(self) -> None:
        """Load state from disk, or initialise defaults."""
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
                self._data = StateData()
        self._maybe_migrate_worker_states()

    def save(self) -> None:
        """Flush current state to disk atomically."""
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
