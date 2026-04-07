"""Trace run state — allocate and track run_id per (issue, phase)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData

logger = logging.getLogger("hydraflow.state")


class TraceRunsMixin:
    """State methods for in-process tracing run-id allocation.

    The state.json ``trace_runs`` field has two sub-dicts:

    - ``active``: ``{"<issue>:<phase>": {"run_id": int, "started_at": str}}``
      populated by ``begin_trace_run``, removed by ``end_trace_run``.
    - ``next_run_id``: ``{"<issue>:<phase>": int}`` — monotonic counter.
    """

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _trace_run_key(issue_number: int, phase: str) -> str:
        return f"{issue_number}:{phase}"

    def begin_trace_run(self, issue_number: int, phase: str) -> int:
        """Allocate a new run_id and mark the run active. Returns the new run_id."""
        key = self._trace_run_key(issue_number, phase)
        next_ids = self._data.trace_runs.setdefault("next_run_id", {})
        active = self._data.trace_runs.setdefault("active", {})

        current = int(
            next_ids.get(key, 0)  # type: ignore[arg-type]
        )
        new_id = current + 1
        next_ids[key] = new_id  # type: ignore[index]

        active[key] = {  # type: ignore[index]
            "run_id": new_id,
            "started_at": datetime.now(UTC).isoformat(),
        }
        self.save()
        return new_id

    def end_trace_run(self, issue_number: int, phase: str) -> None:
        """Mark the run finalized — removes from active set."""
        key = self._trace_run_key(issue_number, phase)
        active = self._data.trace_runs.setdefault("active", {})
        active.pop(key, None)
        self.save()

    def get_active_trace_run(self, issue_number: int, phase: str) -> int | None:
        """Return the run_id of the active run for *(issue, phase)*, or None."""
        key = self._trace_run_key(issue_number, phase)
        active = self._data.trace_runs.get("active", {})
        entry = active.get(key)
        if entry is None:
            return None
        try:
            return int(entry["run_id"])  # type: ignore[index]
        except (KeyError, TypeError, ValueError):
            return None

    def list_active_trace_runs(self) -> list[tuple[int, str, int]]:
        """Return all active runs as ``(issue_number, phase, run_id)`` tuples."""
        out: list[tuple[int, str, int]] = []
        active = self._data.trace_runs.get("active", {})
        for key, entry in active.items():
            try:
                issue_str, phase = key.split(":", 1)
                issue_number = int(issue_str)
                run_id = int(entry["run_id"])  # type: ignore[index]
                out.append((issue_number, phase, run_id))
            except (ValueError, KeyError, TypeError):
                logger.warning("Skipping malformed trace_runs key: %r", key)
        return out

    def purge_stale_trace_runs(
        self, max_age_seconds: float
    ) -> list[tuple[int, str, int]]:
        """Remove active entries older than *max_age_seconds*.

        Used by the trace mining loop to recover from HydraFlow crashes
        that killed an agent mid-phase: the active entry is never removed
        by ``end_trace_run`` and would otherwise hide the orphaned
        ``run-N/`` directory from the orphan janitor forever. Returns the
        list of evicted ``(issue, phase, run_id)`` tuples.
        """
        active = self._data.trace_runs.setdefault("active", {})
        now = datetime.now(UTC)
        evicted: list[tuple[int, str, int]] = []
        stale_keys: list[str] = []
        for key, entry in active.items():
            if not isinstance(entry, dict):
                stale_keys.append(key)
                continue
            started_raw = entry.get("started_at")
            if not isinstance(started_raw, str):
                stale_keys.append(key)
                continue
            try:
                started = datetime.fromisoformat(started_raw)
            except ValueError:
                stale_keys.append(key)
                continue
            # Tolerate naive datetimes from older state files / hand edits:
            # without this, the aware - naive subtraction below raises
            # TypeError and aborts the loop, leaking remaining keys.
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            age_seconds = (now - started).total_seconds()
            if age_seconds < max_age_seconds:
                continue
            try:
                issue_str, phase = key.split(":", 1)
                issue_number = int(issue_str)
                run_id = int(entry["run_id"])
                evicted.append((issue_number, phase, run_id))
            except (ValueError, KeyError, TypeError):
                pass
            stale_keys.append(key)

        if stale_keys:
            for key in stale_keys:
                active.pop(key, None)
            self.save()
            logger.info(
                "Purged %d stale active trace runs (age >= %.0fs)",
                len(stale_keys),
                max_age_seconds,
            )
        return evicted
