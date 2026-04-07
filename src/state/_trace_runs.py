"""Trace run state — allocate and track run_id per (issue, phase)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


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
