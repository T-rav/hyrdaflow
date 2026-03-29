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
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import ValidationError

from file_util import atomic_write, rotate_backups
from models import IssueOutcomeType, StateData, ThresholdProposal

if TYPE_CHECKING:
    from dolt_backend import DoltBackend

from ._bot_pr import BotPRStateMixin
from ._epic import EpicStateMixin
from ._hitl import HITLStateMixin
from ._issue import IssueStateMixin
from ._lifetime import LifetimeStatsMixin
from ._report import ReportStateMixin
from ._review import ReviewStateMixin
from ._session import SessionStateMixin
from ._worker import WorkerStateMixin
from ._workspace import WorkspaceStateMixin

logger = logging.getLogger("hydraflow.state")

_V = TypeVar("_V")

__all__ = ["StateTracker", "build_state_tracker"]


class StateTracker(
    IssueStateMixin,
    WorkspaceStateMixin,
    HITLStateMixin,
    ReviewStateMixin,
    EpicStateMixin,
    LifetimeStatsMixin,
    SessionStateMixin,
    WorkerStateMixin,
    ReportStateMixin,
    BotPRStateMixin,
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
        dolt: DoltBackend | None = None,
        backup_interval: int = 300,
        backup_count: int = 3,
    ) -> None:
        self._path = state_file
        self._dolt = dolt
        self._data: StateData = StateData()
        self._last_backup: float = time.monotonic()
        self._backup_interval: int = backup_interval
        self._backup_count: int = backup_count
        self.load()

    # --- persistence ---

    def load(self) -> None:
        """Load state from Dolt (if configured) or disk.

        When the primary state file is corrupt, attempts to restore from
        the most recent ``.bak`` file before falling back to an empty
        :class:`StateData`.
        """
        if self._dolt:
            try:
                loaded = self._dolt.load_state()
                if loaded and isinstance(loaded, dict):
                    self._data = StateData.model_validate(loaded)
                    logger.info("State loaded from Dolt")
                else:
                    # Dolt empty — try file fallback for initial migration
                    self._load_from_file()
            except (ValueError, ValidationError) as exc:
                logger.warning("Corrupt Dolt state, resetting: %s", exc, exc_info=True)
                self._data = StateData()
        else:
            self._load_from_file()
        self._maybe_migrate_worker_states()

    def _load_from_file(self) -> None:
        """Load state from the JSON file."""
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
        """Flush current state to Dolt (if configured) or disk.

        Automatically creates a rotated backup when more than
        ``backup_interval`` seconds have elapsed since the last backup.
        """
        now = time.monotonic()
        if now - self._last_backup >= self._backup_interval:
            self.backup()
        self._data.last_updated = datetime.now(UTC).isoformat()
        data = self._data.model_dump_json(indent=2)
        if self._dolt:
            self._dolt.save_state(data)
        else:
            atomic_write(self._path, data)

    def commit_state(self, message: str = "state update") -> None:
        """Create a Dolt version commit (no-op when using file backend)."""
        if self._dolt:
            self._dolt.commit(message)

    # --- reset ---

    def reset(self) -> None:
        """Clear all state and persist.  Lifetime stats are preserved."""
        saved_lifetime = self._data.lifetime_stats.model_copy()
        self._data = StateData(lifetime_stats=saved_lifetime)
        self.save()

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of the raw state dict."""
        return self._data.model_dump()

    # --- consolidated mutation helpers ---

    def record_successful_merge(
        self,
        issue_number: int,
        pr_number: int,
        *,
        ci_fix_attempts: int = 0,
        merge_duration_seconds: float = 0.0,
        quality_fix_rate_threshold: float = 0.0,
        approval_rate_threshold: float = 0.0,
        hitl_rate_threshold: float = 0.0,
    ) -> list[ThresholdProposal]:
        """Consolidate all state updates for a successful merge.

        Replaces the 13 individual state calls previously scattered in
        ``PostMergeHandler.handle_approved``.  Returns threshold proposals
        that should be published as system alerts.
        """
        self.mark_issue(issue_number, "merged")
        self.record_pr_merged()
        self.record_issue_completed()
        self.increment_session_counter("merged")
        if ci_fix_attempts > 0:
            self.record_ci_fix_rounds(ci_fix_attempts)
            for _ in range(ci_fix_attempts):
                self.record_stage_retry(issue_number, "ci_fix")
        if merge_duration_seconds > 0:
            self.record_merge_duration(merge_duration_seconds)
        proposals = self.check_thresholds(
            quality_fix_rate_threshold,
            approval_rate_threshold,
            hitl_rate_threshold,
        )
        self.record_outcome(
            issue_number,
            IssueOutcomeType.MERGED,
            reason="PR approved and merged",
            pr_number=pr_number,
            phase="review",
        )
        self.reset_review_attempts(issue_number)
        self.reset_issue_attempts(issue_number)
        self.clear_review_feedback(issue_number)
        return proposals


def build_state_tracker(config: Any) -> StateTracker:
    """Construct a ``StateTracker`` with the best available backend.

    Uses embedded Dolt when the ``dolt`` CLI is installed, otherwise
    falls back to JSON-file persistence.
    """
    dolt_backend = None
    try:
        from dolt_backend import DoltBackend

        dolt_dir = Path(str(config.state_file)).parent / "dolt"
        dolt_backend = DoltBackend(dolt_dir)
        logger.info("Dolt state backend enabled at %s", dolt_dir)
    except FileNotFoundError:
        logger.info("dolt CLI not found — using file-based state")
    except Exception:
        logger.warning("Dolt init failed — using file-based state", exc_info=True)
    return StateTracker(config.state_file, dolt=dolt_backend)
