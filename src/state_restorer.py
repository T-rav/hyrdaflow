"""Crash-recovery and state restoration for the orchestrator."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from models import BackgroundWorkerState

if TYPE_CHECKING:
    from bg_worker_manager import BGWorkerManager
    from events import EventBus
    from state import StateTracker

logger = logging.getLogger("hydraflow.state_restorer")


class StateRestorer:
    """Restores orchestrator state from persisted storage on startup."""

    def __init__(
        self,
        state: StateTracker,
        bus: EventBus,
        bg_workers: BGWorkerManager,
    ) -> None:
        self._state = state
        self._bus = bus
        self._bg_workers = bg_workers

    def restore_all(
        self,
        recovered_issues: set[int],
        active_impl_issues: set[int],
        active_review_issues: set[int],
        active_hitl_issues: set[int],
    ) -> None:
        """Run all restore steps in the correct order."""
        self._restore_worker_intervals()
        self._restore_crash_recovered_issues(recovered_issues, active_impl_issues)
        self._restore_interrupted_issues(
            recovered_issues,
            active_impl_issues,
            active_review_issues,
            active_hitl_issues,
        )
        self._restore_disabled_workers()
        self._restore_bg_worker_states()

    def _restore_worker_intervals(self) -> None:
        """Restore saved background-worker poll-interval overrides from state."""
        saved_intervals = self._state.get_worker_intervals()
        if saved_intervals:
            self._bg_workers.worker_intervals.update(saved_intervals)
            logger.info(
                "Restored %d worker interval override(s) from state",
                len(saved_intervals),
            )

    def _restore_crash_recovered_issues(
        self,
        recovered_issues: set[int],
        active_impl_issues: set[int],
    ) -> None:
        """Load crash-recovered active issues so they're skipped for one poll cycle."""
        recovered = set(self._state.get_active_issue_numbers())
        if recovered:
            recovered_issues.update(recovered)
            active_impl_issues.update(recovered)
            logger.info(
                "Crash recovery: loaded %d active issue(s) from state: %s",
                len(recovered),
                recovered,
            )

    def _restore_interrupted_issues(
        self,
        recovered_issues: set[int],
        active_impl_issues: set[int],
        active_review_issues: set[int],
        active_hitl_issues: set[int],
    ) -> None:
        """Remove interrupted issues from crash-recovery sets so they re-route normally."""
        interrupted = self._state.get_interrupted_issues()
        if interrupted:
            for issue_number in interrupted:
                recovered_issues.discard(issue_number)
                active_impl_issues.discard(issue_number)
                active_review_issues.discard(issue_number)
                active_hitl_issues.discard(issue_number)
            logger.info(
                "Restored %d interrupted issue(s) for re-processing: %s",
                len(interrupted),
                interrupted,
            )
            self._state.clear_interrupted_issues()

    def _restore_disabled_workers(self) -> None:
        """Restore persisted disabled-worker flags into the in-memory map."""
        disabled = self._state.get_disabled_workers()
        if disabled:
            for name in disabled:
                self._bg_workers.worker_enabled[name] = False
            logger.info(
                "Restored %d disabled worker(s) from state: %s",
                len(disabled),
                sorted(disabled),
            )

    def prune_stale_disabled_workers(self, known_names: set[str]) -> None:
        """Remove disabled-worker entries for workers that no longer exist.

        Called after loop factories are defined so we know the full set of
        valid worker names.  Stale entries accumulate when workers are renamed
        or removed between releases.
        """
        if not known_names:
            return
        disabled = self._state.get_disabled_workers()
        stale = disabled - known_names
        if not stale:
            return
        logger.info(
            "Pruning %d stale disabled-worker name(s) from state: %s",
            len(stale),
            sorted(stale),
        )
        for name in stale:
            self._bg_workers.worker_enabled.pop(name, None)
        self._state.set_disabled_workers(disabled - stale)

    def _restore_bg_worker_states(self) -> None:
        """Hydrate background worker heartbeat cache from persisted state."""
        persisted = self._state.get_bg_worker_states()
        restored = 0
        if persisted:
            self._bg_workers.worker_states.update(persisted)
            restored = len(persisted)
            logger.info(
                "Restored %d background worker heartbeat entr%s from state",
                restored,
                "ies" if restored != 1 else "y",
            )
        backfilled = self._backfill_bg_worker_states_from_events()
        if backfilled:
            logger.info(
                "Backfilled %d background worker heartbeat entr%s from event history",
                backfilled,
                "ies" if backfilled != 1 else "y",
            )

    def _backfill_bg_worker_states_from_events(self) -> int:
        """Populate heartbeat cache from recent BACKGROUND_WORKER_STATUS events."""
        from events import EventType

        history = list(self._bus.get_history())
        if not history:
            return 0
        latest: dict[str, BackgroundWorkerState] = {}
        existing = set(self._bg_workers.worker_states)
        for event in reversed(history):
            if event.type != EventType.BACKGROUND_WORKER_STATUS:
                continue
            worker = event.data.get("worker")
            if not worker or worker in existing or worker in latest:
                continue
            raw_details = event.data.get("details", {}) or {}
            details = (
                dict(raw_details)
                if isinstance(raw_details, dict)
                else {"raw": raw_details}
            )
            latest[worker] = BackgroundWorkerState(
                name=worker,
                status=str(event.data.get("status", "disabled")),
                last_run=event.data.get("last_run"),
                details=details,
            )
        for name, state in latest.items():
            self._bg_workers.worker_states[name] = state
            self._state.set_bg_worker_state(name, state)
        return len(latest)
