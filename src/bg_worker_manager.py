"""Background worker lifecycle management — states, intervals, and triggering."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from models import BackgroundWorkerState

if TYPE_CHECKING:
    from base_background_loop import BaseBackgroundLoop
    from config import HydraFlowConfig
    from state import StateTracker

logger = logging.getLogger("hydraflow.bg_worker_manager")


class BGWorkerManager:
    """Manages background worker states, enabled flags, intervals, and triggering."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        bg_loop_registry: dict[str, BaseBackgroundLoop],
    ) -> None:
        self._config = config
        self._state = state
        self._bg_loop_registry = bg_loop_registry
        self._bg_worker_states: dict[str, BackgroundWorkerState] = {}
        self._bg_worker_enabled: dict[str, bool] = {}
        self._bg_worker_intervals: dict[str, int] = {}

    @property
    def worker_states(self) -> dict[str, BackgroundWorkerState]:
        """Mutable worker states dict."""
        return self._bg_worker_states

    @property
    def worker_enabled(self) -> dict[str, bool]:
        """Mutable enabled flags dict."""
        return self._bg_worker_enabled

    @property
    def worker_intervals(self) -> dict[str, int]:
        """Mutable intervals dict."""
        return self._bg_worker_intervals

    def update_status(
        self, name: str, status: str, details: dict[str, Any] | None = None
    ) -> None:
        """Record the latest heartbeat from a background worker."""
        self._bg_worker_states[name] = BackgroundWorkerState(
            name=name,
            status=status,
            last_run=datetime.now(UTC).isoformat(),
            details=dict(details) if details is not None else {},
        )
        self._state.set_bg_worker_state(name, self._bg_worker_states[name])

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a background worker by name and persist to state."""
        self._bg_worker_enabled[name] = enabled
        disabled = {n for n, e in self._bg_worker_enabled.items() if not e}
        self._state.set_disabled_workers(disabled)

    def is_enabled(self, name: str) -> bool:
        """Return whether a background worker is enabled (defaults to True)."""
        return self._bg_worker_enabled.get(name, True)

    def get_states(self) -> dict[str, BackgroundWorkerState]:
        """Return a copy of all background worker states with enabled flag."""
        result: dict[str, BackgroundWorkerState] = {}
        for name, state_dict in self._bg_worker_states.items():
            result[name] = cast(
                BackgroundWorkerState, {**state_dict, "enabled": self.is_enabled(name)}
            )
        return result

    def trigger(self, name: str) -> bool:
        """Trigger an immediate execution of a background worker.

        Returns ``True`` if the worker was found and triggered, ``False``
        if *name* does not correspond to a registered ``BaseBackgroundLoop``.
        """
        loop = self._bg_loop_registry.get(name)
        if loop is None:
            return False
        loop.trigger()
        return True

    def _restore_intervals(self, intervals: dict[str, int]) -> None:
        """Bulk-restore interval overrides (used during startup recovery)."""
        self._bg_worker_intervals.update(intervals)

    def _restore_enabled_flags(self, disabled_names: set[str]) -> None:
        """Bulk-restore disabled flags (used during startup recovery)."""
        for name in disabled_names:
            self._bg_worker_enabled[name] = False

    def _remove_enabled_entry(self, name: str) -> None:
        """Remove an enabled-flag entry entirely (for stale worker pruning)."""
        self._bg_worker_enabled.pop(name, None)

    def _restore_worker_state(self, name: str, state: BackgroundWorkerState) -> None:
        """Set a single worker state entry (used during startup recovery)."""
        self._bg_worker_states[name] = state

    def _restore_worker_states(self, states: dict[str, BackgroundWorkerState]) -> None:
        """Bulk-restore worker heartbeat states (used during startup recovery)."""
        self._bg_worker_states.update(states)

    def _known_worker_state_names(self) -> set[str]:
        """Return the set of worker names that have heartbeat state."""
        return set(self._bg_worker_states)

    def set_interval(self, name: str, seconds: int) -> None:
        """Set a dynamic interval override for a background worker."""
        self._bg_worker_intervals[name] = seconds
        self._state.set_worker_intervals(dict(self._bg_worker_intervals))

    def get_interval(self, name: str) -> int:
        """Return the effective interval for a background worker.

        Returns the dynamic override if set, otherwise the config default.
        """
        if name in self._bg_worker_intervals:
            return self._bg_worker_intervals[name]
        defaults: dict[str, int] = {
            "memory_sync": self._config.memory_sync_interval,
            "pipeline_poller": 5,
            "pr_unsticker": self._config.pr_unstick_interval,
            "report_issue": self._config.report_issue_interval,
            "epic_monitor": self._config.epic_monitor_interval,
            "workspace_gc": self._config.workspace_gc_interval,
            # Daily caretaker — never falls through to poll_interval.
            "pricing_refresh": 86400,
        }
        return defaults.get(name, self._config.poll_interval)
