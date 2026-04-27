"""Worker interval, disabled worker, and background worker heartbeat state."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from models import BackgroundWorkerState, PersistedWorkerHeartbeat

if TYPE_CHECKING:
    from models import StateData

logger = logging.getLogger("hydraflow.state")


class WorkerStateMixin:
    """Methods for worker intervals, disabled workers, and heartbeat state."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    # --- private helpers ---

    def _normalise_details(self, raw: dict[str, object] | str | None) -> dict[str, Any]:
        """Ensure worker heartbeat details are stored as dicts."""
        if isinstance(raw, dict):
            return dict(raw)
        if raw in (None, ""):
            return {}
        return {"raw": raw}

    def _coerce_last_run(self, value: str | int | float | None) -> str | None:
        """Normalise arbitrary values to ISO8601 strings or None."""
        if value is None or isinstance(value, str):
            return value
        return str(value)

    def _persist_worker_state(
        self,
        name: str,
        status: str,
        last_run: str | None,
        details: dict[str, Any],
    ) -> None:
        heartbeat: PersistedWorkerHeartbeat = {
            "status": status,
            "last_run": last_run,
            "details": dict(details),
        }
        self._data.worker_heartbeats[name] = heartbeat
        self._data.bg_worker_states[name] = BackgroundWorkerState(
            name=name,
            status=status,
            last_run=last_run,
            details=dict(details),
        )

    def _maybe_migrate_worker_states(self) -> None:
        """Copy legacy bg_worker_states entries into worker_heartbeats if needed."""
        if self._data.worker_heartbeats or not self._data.bg_worker_states:
            return
        for name, state in self._data.bg_worker_states.items():
            details = self._normalise_details(state.get("details"))
            status = str(state.get("status", "disabled"))
            last_run = self._coerce_last_run(state.get("last_run"))
            self._persist_worker_state(name, status, last_run, details)
        self.save()

    # --- worker interval overrides ---

    def get_worker_intervals(self) -> dict[str, int]:
        """Return persisted worker interval overrides."""
        return dict(self._data.worker_intervals)

    def set_worker_intervals(self, intervals: dict[str, int]) -> None:
        """Persist worker interval overrides."""
        self._data.worker_intervals = intervals
        self.save()

    # --- disabled workers ---

    def get_disabled_workers(self) -> set[str]:
        """Return the set of worker names that have been disabled."""
        return set(self._data.disabled_workers)

    def set_disabled_workers(self, names: set[str]) -> None:
        """Persist the set of disabled worker names."""
        self._data.disabled_workers = sorted(names)
        self.save()

    def get_cost_budget_killed_workers(self) -> set[str]:
        """Return workers killed by CostBudgetWatcherLoop (distinct from operator-disabled)."""
        return set(self._data.cost_budget_killed_workers)

    def set_cost_budget_killed_workers(self, names: set[str]) -> None:
        """Persist the set of workers the cost-budget watcher has killed."""
        self._data.cost_budget_killed_workers = sorted(names)
        self.save()

    # --- background worker states ---

    def get_worker_heartbeats(self) -> dict[str, PersistedWorkerHeartbeat]:
        """Return the minimal persisted heartbeat snapshots."""
        source: dict[str, Any] = {}
        if self._data.worker_heartbeats:
            source = self._data.worker_heartbeats
        elif self._data.bg_worker_states:
            source = {
                name: {
                    "status": state.get("status", "disabled"),
                    "last_run": state.get("last_run"),
                    "details": state.get("details", {}),
                }
                for name, state in self._data.bg_worker_states.items()
            }
        result: dict[str, PersistedWorkerHeartbeat] = {}
        for name, heartbeat in source.items():
            details = self._normalise_details(heartbeat.get("details"))
            result[name] = {
                "status": str(heartbeat.get("status", "disabled")),
                "last_run": heartbeat.get("last_run"),
                "details": details,
            }
        return result

    def set_worker_heartbeat(
        self, name: str, heartbeat: PersistedWorkerHeartbeat
    ) -> None:
        """Persist a single worker heartbeat snapshot."""
        details = self._normalise_details(heartbeat.get("details"))
        status = str(heartbeat.get("status", "disabled"))
        last_run = self._coerce_last_run(heartbeat.get("last_run"))
        self._persist_worker_state(name, status, last_run, details)
        self.save()

    def get_bg_worker_states(self) -> dict[str, BackgroundWorkerState]:
        """Return persisted background worker heartbeat states."""
        result: dict[str, BackgroundWorkerState] = {}
        for name, heartbeat in self.get_worker_heartbeats().items():
            result[name] = BackgroundWorkerState(
                name=name,
                status=heartbeat.get("status", "disabled"),
                last_run=heartbeat.get("last_run"),
                details=dict(heartbeat.get("details", {})),
            )
        return result

    def set_bg_worker_state(self, name: str, state: BackgroundWorkerState) -> None:
        """Persist a single background worker heartbeat entry."""
        stored = dict(state)
        stored.pop("enabled", None)  # enabled is runtime-only
        raw_details = stored.get("details")
        details = self._normalise_details(
            raw_details if isinstance(raw_details, dict | str) else None
        )
        status = str(stored.get("status", "disabled"))
        raw_last_run = stored.get("last_run")
        last_run = self._coerce_last_run(
            raw_last_run if isinstance(raw_last_run, str | int | float) else None
        )
        self._persist_worker_state(name, status, last_run, details)
        self.save()

    def remove_bg_worker_state(self, name: str) -> None:
        """Remove persisted heartbeat entry for *name*."""
        removed = False
        if name in self._data.bg_worker_states:
            self._data.bg_worker_states.pop(name, None)
            removed = True
        if name in self._data.worker_heartbeats:
            self._data.worker_heartbeats.pop(name, None)
            removed = True
        if removed:
            self.save()
