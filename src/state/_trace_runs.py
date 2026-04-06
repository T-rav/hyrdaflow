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
