"""Main orchestrator loop — plan, implement, review, cleanup, repeat."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from models import (
    BackgroundWorkerState,
    GitHubIssue,
    Phase,
    PipelineStats,
    SessionLog,
    SessionStatus,
    StageStats,
    ThroughputStats,
    WorkFn,
)
from phase_utils import (
    is_adr_issue_title,
    release_batch_in_flight,
    safe_file_memory_suggestion,
)
from service_registry import OrchestratorCallbacks, build_services
from state import StateTracker
from subprocess_util import AuthenticationError, CreditExhaustedError

if TYPE_CHECKING:
    from issue_store import IssueStore
    from metrics_manager import MetricsManager
    from run_recorder import RunRecorder

logger = logging.getLogger("hydraflow.orchestrator")

# Delay after a merge to allow GitHub to propagate the merge state.
_POST_MERGE_DELAY: int = 5


class HydraFlowOrchestrator:
    """Coordinates the full HydraFlow pipeline.

    Each phase runs as an independent polling loop so new work is picked
    up continuously — planner, implementer, and reviewer all run
    concurrently without waiting on each other.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus | None = None,
        state: StateTracker | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus or EventBus()
        self._state = state or StateTracker(config.state_file)
        self._dashboard: object | None = None
        # Pending human-input requests: {issue_number: question}
        self._human_input_requests: dict[int, str] = {}
        # Fulfilled human-input responses: {issue_number: answer}
        self._human_input_responses: dict[int, str] = {}
        # In-memory tracking of active issues (avoids double-processing)
        self._active_impl_issues: set[int] = set()
        self._active_review_issues: set[int] = set()
        self._active_issues_lock = asyncio.Lock()
        # Issues recovered from persisted state on startup (one-cycle grace period)
        self._recovered_issues: set[int] = set()
        # Stop mechanism for dashboard control
        self._stop_event = asyncio.Event()
        self._running = False
        # Background worker last-known status: {worker_name: status dict}
        self._bg_worker_states: dict[str, BackgroundWorkerState] = {}
        # Background worker enabled flags: {worker_name: bool}
        self._bg_worker_enabled: dict[str, bool] = {}
        # Auth failure flag — set when a loop crashes due to AuthenticationError
        self._auth_failed = False
        # Dynamic interval overrides: {worker_name: seconds}
        self._bg_worker_intervals: dict[str, int] = {}
        # Credit pause — set when API credits are exhausted
        self._credits_paused_until: datetime | None = None
        self._credit_pause_lock = asyncio.Lock()
        # Session tracking
        self._current_session: SessionLog | None = None
        self._session_issue_results: dict[int, bool] = {}
        # Loop tasks (set by _supervise_loops for stop() to cancel)
        self._loop_tasks: dict[str, asyncio.Task[None]] = {}

        # Build all services via the factory
        svc = build_services(
            config,
            self._bus,
            self._state,
            self._stop_event,
            OrchestratorCallbacks(
                sync_active_issue_numbers=self._sync_active_issue_numbers,
                update_bg_worker_status=self.update_bg_worker_status,
                is_bg_worker_enabled=self.is_bg_worker_enabled,
                sleep_or_stop=self._sleep_or_stop,
                get_bg_worker_interval=self.get_bg_worker_interval,
            ),
        )

        # Expose services as instance attributes for backward compatibility
        self._worktrees = svc.worktrees
        self._subprocess_runner = svc.subprocess_runner
        self._agents = svc.agents
        self._planners = svc.planners
        self._prs = svc.prs
        self._reviewers = svc.reviewers
        self._hitl_runner = svc.hitl_runner
        self._triage = svc.triage
        self._summarizer = svc.summarizer
        self._fetcher = svc.fetcher
        self._store = svc.store
        self._triager = svc.triager
        self._planner_phase = svc.planner_phase
        self._hitl_phase = svc.hitl_phase
        self._run_recorder = svc.run_recorder
        self._implementer = svc.implementer
        self._metrics_manager = svc.metrics_manager
        self._pr_unsticker = svc.pr_unsticker
        self._memory_sync = svc.memory_sync
        self._retrospective = svc.retrospective
        self._ac_generator = svc.ac_generator
        self._verification_judge = svc.verification_judge
        self._epic_checker = svc.epic_checker
        self._reviewer = svc.reviewer
        self._memory_sync_bg = svc.memory_sync_bg
        self._metrics_sync_bg = svc.metrics_sync_bg
        self._pr_unsticker_loop = svc.pr_unsticker_loop
        self._manifest_refresh_loop = svc.manifest_refresh_loop
        self._report_issue_loop = svc.report_issue_loop
        self._epic_manager = svc.epic_manager
        self._epic_monitor_loop = svc.epic_monitor_loop
        self._worktree_gc_loop = svc.worktree_gc_loop
        self._runs_gc_loop = svc.runs_gc_loop

    @property
    def event_bus(self) -> EventBus:
        """Expose event bus for dashboard integration."""
        return self._bus

    @property
    def issue_store(self) -> IssueStore:
        """Expose the centralized issue store for dashboard integration."""
        return self._store

    @property
    def state(self) -> StateTracker:
        """Expose state for dashboard integration."""
        return self._state

    @property
    def run_recorder(self) -> RunRecorder:
        """Expose run recorder for dashboard API."""
        return self._run_recorder

    @property
    def metrics_manager(self) -> MetricsManager:
        """Expose metrics manager for dashboard API."""
        return self._metrics_manager

    @property
    def running(self) -> bool:
        """Whether the orchestrator is currently executing."""
        return self._running

    @property
    def current_session_id(self) -> str | None:
        """Return the active session ID, or None."""
        return self._current_session.id if self._current_session else None

    def _has_active_processes(self) -> bool:
        """Return True if any runner pool still has live subprocesses."""
        return bool(
            self._planners._active_procs
            or self._agents._active_procs
            or self._reviewers._active_procs
            or self._hitl_runner._active_procs
        )

    @property
    def credits_paused_until(self) -> datetime | None:
        """The UTC datetime when credit pause ends, or ``None``."""
        if (
            self._credits_paused_until is not None
            and self._credits_paused_until > datetime.now(UTC)
        ):
            return self._credits_paused_until
        return None

    @property
    def run_status(self) -> str:
        """Return the current lifecycle status: idle, running, stopping, auth_failed, credits_paused, or done."""
        if self._auth_failed:
            return "auth_failed"
        if (
            self._credits_paused_until is not None
            and self._credits_paused_until > datetime.now(UTC)
        ):
            return "credits_paused"
        if self._stop_event.is_set() and (
            self._running or self._has_active_processes()
        ):
            return "stopping"
        if self._running:
            return "running"
        # Check if we finished naturally (DONE phase in history)
        for event in reversed(self._bus.get_history()):
            if (
                event.type == EventType.PHASE_CHANGE
                and event.data.get("phase") == Phase.DONE.value
            ):
                return "done"
        return "idle"

    @property
    def human_input_requests(self) -> dict[int, str]:
        """Pending questions for the human operator."""
        return self._human_input_requests

    def provide_human_input(self, issue_number: int, answer: str) -> None:
        """Provide an answer to a paused agent's question."""
        self._human_input_responses[issue_number] = answer
        self._human_input_requests.pop(issue_number, None)

    def submit_hitl_correction(self, issue_number: int, correction: str) -> None:
        """Store a correction for a HITL issue to guide retry."""
        self._hitl_phase.submit_correction(issue_number, correction)

    def get_hitl_status(self, issue_number: int) -> str:
        """Return the HITL status for an issue."""
        return self._hitl_phase.get_status(issue_number)

    def skip_hitl_issue(self, issue_number: int) -> None:
        """Remove an issue from HITL tracking."""
        self._hitl_phase.skip_issue(issue_number)

    async def stop(self) -> None:
        """Signal the orchestrator to stop and kill active subprocesses.

        Checkpoints interrupted issues before cancelling loop tasks so
        that on restart each issue can be routed back to the correct phase.
        """
        self._stop_event.set()
        logger.info("Stop requested — terminating active processes")
        self._planners.terminate()
        self._agents.terminate()
        self._reviewers.terminate()
        self._hitl_runner.terminate()

        # Checkpoint interrupted issues before cancelling tasks
        interrupted = await self._build_interrupted_issues()
        if interrupted:
            self._state.set_interrupted_issues(interrupted)
            logger.info(
                "Checkpointed %d interrupted issue(s): %s",
                len(interrupted),
                interrupted,
            )

        # Cancel loop tasks so _supervise_loops exits immediately
        for name, task in self._loop_tasks.items():
            if not task.done():
                task.cancel()
                logger.debug("Cancelled loop task %r", name)

        await self._publish_status()

    async def _build_interrupted_issues(self) -> dict[int, str]:
        """Build a mapping of issue_number → phase for all in-flight issues.

        Acquires ``_active_issues_lock`` to ensure a consistent snapshot of the
        in-memory tracking sets, preventing races with concurrent workers that
        add/remove issues across ``await`` points.
        """
        async with self._active_issues_lock:
            interrupted: dict[int, str] = {}
            # Use IssueStore active tracking as the primary source
            for issue_num, stage in self._store.get_active_issues().items():
                interrupted[issue_num] = stage
            # Also check in-memory tracking sets for issues not yet in the store
            for issue_num in self._active_impl_issues:
                if issue_num not in interrupted:
                    interrupted[issue_num] = "implement"
            for issue_num in self._active_review_issues:
                if issue_num not in interrupted:
                    interrupted[issue_num] = "review"
            for issue_num in self._hitl_phase.active_hitl_issues:
                if issue_num not in interrupted:
                    interrupted[issue_num] = "hitl"
            return interrupted

    # Alias for backward compatibility
    request_stop = stop

    def reset(self) -> None:
        """Reset the stop event so the orchestrator can be started again."""
        self._stop_event.clear()
        self._running = False
        self._auth_failed = False
        self._credits_paused_until = None
        self._store.clear_active()
        self._active_impl_issues.clear()
        self._active_review_issues.clear()
        self._hitl_phase.active_hitl_issues.clear()
        self._state.clear_interrupted_issues()

    @property
    def _active_hitl_issues(self) -> set[int]:
        """Backward-compatible access to HITL active issues."""
        return self._hitl_phase.active_hitl_issues

    @property
    def _hitl_corrections(self) -> dict[int, str]:
        """Backward-compatible access to HITL corrections dict."""
        return self._hitl_phase.hitl_corrections

    def _sync_active_issue_numbers(self) -> None:
        """Persist the combined active issue set to state."""
        self._state.set_active_issue_numbers(
            list(
                self._active_impl_issues
                | self._active_review_issues
                | self._hitl_phase.active_hitl_issues
            )
        )

    def update_bg_worker_status(
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

    def set_bg_worker_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a background worker by name and persist to state."""
        self._bg_worker_enabled[name] = enabled
        disabled = {n for n, e in self._bg_worker_enabled.items() if not e}
        self._state.set_disabled_workers(disabled)

    def is_bg_worker_enabled(self, name: str) -> bool:
        """Return whether a background worker is enabled (defaults to True)."""
        return self._bg_worker_enabled.get(name, True)

    def get_bg_worker_states(self) -> dict[str, BackgroundWorkerState]:
        """Return a copy of all background worker states with enabled flag."""
        result: dict[str, BackgroundWorkerState] = {}
        for name, state_dict in self._bg_worker_states.items():
            result[name] = {**state_dict, "enabled": self.is_bg_worker_enabled(name)}
        return result

    def set_bg_worker_interval(self, name: str, seconds: int) -> None:
        """Set a dynamic interval override for a background worker."""
        self._bg_worker_intervals[name] = seconds
        self._state.set_worker_intervals(dict(self._bg_worker_intervals))

    def get_bg_worker_interval(self, name: str) -> int:
        """Return the effective interval for a background worker.

        Returns the dynamic override if set, otherwise the config default.
        """
        if name in self._bg_worker_intervals:
            return self._bg_worker_intervals[name]
        defaults: dict[str, int] = {
            "memory_sync": self._config.memory_sync_interval,
            "metrics": self._config.metrics_sync_interval,
            "pipeline_poller": 5,
            "pr_unsticker": self._config.pr_unstick_interval,
            "manifest_refresh": self._config.manifest_refresh_interval,
            "report_issue": self._config.report_issue_interval,
            "epic_monitor": self._config.epic_monitor_interval,
            "worktree_gc": self._config.worktree_gc_interval,
        }
        return defaults.get(name, self._config.poll_interval)

    async def _publish_status(self) -> None:
        """Broadcast the current orchestrator status to all subscribers."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.ORCHESTRATOR_STATUS,
                data={
                    "status": self.run_status,
                    **(
                        {"credits_paused_until": self.credits_paused_until.isoformat()}
                        if self.credits_paused_until
                        else {}
                    ),
                },
            )
        )

    def build_pipeline_stats(self) -> PipelineStats:
        """Build a unified snapshot of the pipeline state."""
        queue_stats = self._store.get_queue_stats()
        lifetime = self._state.get_lifetime_stats()

        # Compute uptime from session start
        uptime = 0.0
        if self._current_session and self._current_session.started_at:
            try:
                started = datetime.fromisoformat(self._current_session.started_at)
                uptime = (datetime.now(UTC) - started).total_seconds()
            except (ValueError, TypeError):
                pass

        # Map stage keys to config worker caps
        stage_caps: dict[str, int] = {
            "triage": self._config.max_triagers,
            "plan": self._config.max_planners,
            "implement": self._config.max_workers,
            "review": self._config.max_reviewers,
            "hitl": self._config.max_hitl_workers,
        }

        # Map stage keys to runner pools for active worker counts
        stage_runners: dict[str, int] = {
            "triage": len(self._triage._active_procs),
            "plan": len(self._planners._active_procs),
            "implement": len(self._agents._active_procs),
            "review": len(self._reviewers._active_procs),
            "hitl": len(self._hitl_runner._active_procs),
        }

        # Map IssueStore stage names to our stage keys
        store_stage_map: dict[str, str] = {
            "find": "triage",
            "plan": "plan",
            "ready": "implement",
            "review": "review",
            "hitl": "hitl",
        }

        # Session counters from persisted state
        session_counters = self._state.get_session_counters()
        session_counter_map: dict[str, str] = {
            "triage": "triaged",
            "plan": "planned",
            "implement": "implemented",
            "review": "reviewed",
            "hitl": "",  # HITL has no dedicated counter; shows 0
        }

        stages: dict[str, StageStats] = {}
        for stage_key in ("triage", "plan", "implement", "review", "hitl"):
            # Find the IssueStore stage name for queue/active lookups
            store_key = next(
                (k for k, v in store_stage_map.items() if v == stage_key), stage_key
            )
            queued = queue_stats.queue_depth.get(store_key, 0)
            active = queue_stats.active_count.get(store_key, 0)
            counter_field = session_counter_map.get(stage_key, "")
            session_processed = (
                getattr(session_counters, counter_field, 0) if counter_field else 0
            )
            completed_lt = queue_stats.total_processed.get(store_key, 0)

            stages[stage_key] = StageStats(
                queued=queued,
                active=active,
                completed_session=session_processed,
                completed_lifetime=completed_lt,
                worker_count=stage_runners.get(stage_key, 0),
                worker_cap=stage_caps.get(stage_key),
            )

        # Add a merged pseudo-stage from session counters and lifetime stats
        stages["merged"] = StageStats(
            completed_session=session_counters.merged,
            completed_lifetime=lifetime.prs_merged,
        )

        # Compute throughput (issues/hour) from session counters / uptime
        session_throughput = self._state.compute_session_throughput()
        throughput = ThroughputStats(
            triage=session_throughput.get("triaged", 0.0),
            plan=session_throughput.get("planned", 0.0),
            implement=session_throughput.get("implemented", 0.0),
            review=session_throughput.get("reviewed", 0.0),
            hitl=0.0,
        )

        return PipelineStats(
            timestamp=datetime.now(UTC).isoformat(),
            stages=stages,
            queue=queue_stats,
            throughput=throughput,
            uptime_seconds=round(uptime, 1),
        )

    async def emit_pipeline_stats(self) -> None:
        """Build and publish a PIPELINE_STATS event."""
        stats = self.build_pipeline_stats()
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.PIPELINE_STATS,
                data=stats.model_dump(),
            )
        )

    async def _pipeline_stats_loop(self) -> None:
        """Emit pipeline stats every ~10 seconds."""
        interval = self.get_bg_worker_interval("pipeline_poller")
        while not self._stop_event.is_set():
            try:
                await self.emit_pipeline_stats()
            except Exception:
                logger.exception("Pipeline stats emission failed")
            await self._sleep_or_stop(interval)

    def _restore_worker_intervals(self) -> None:
        """Restore saved background-worker poll-interval overrides from state."""
        saved_intervals = self._state.get_worker_intervals()
        if saved_intervals:
            self._bg_worker_intervals.update(saved_intervals)
            logger.info(
                "Restored %d worker interval override(s) from state",
                len(saved_intervals),
            )

    def _restore_crash_recovered_issues(self) -> None:
        """Load crash-recovered active issues so they're skipped for one poll cycle."""
        recovered = set(self._state.get_active_issue_numbers())
        if recovered:
            self._recovered_issues = recovered
            self._active_impl_issues.update(recovered)
            logger.info(
                "Crash recovery: loaded %d active issue(s) from state: %s",
                len(recovered),
                recovered,
            )

    def _restore_interrupted_issues(self) -> None:
        """Remove interrupted issues from crash-recovery sets so they re-route normally."""
        interrupted = self._state.get_interrupted_issues()
        if interrupted:
            for issue_num in interrupted:
                self._recovered_issues.discard(issue_num)
                self._active_impl_issues.discard(issue_num)
                self._active_review_issues.discard(issue_num)
                self._hitl_phase.active_hitl_issues.discard(issue_num)
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
                self._bg_worker_enabled[name] = False
            logger.info(
                "Restored %d disabled worker(s) from state: %s",
                len(disabled),
                sorted(disabled),
            )

    def _prune_stale_disabled_workers(self, known_names: set[str]) -> None:
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
            self._bg_worker_enabled.pop(name, None)
        self._state.set_disabled_workers(disabled - stale)

    def _restore_state(self) -> None:
        """Restore worker intervals, crash-recovered issues, interrupted issues, disabled workers, and background worker heartbeats."""
        self._restore_worker_intervals()
        self._restore_crash_recovered_issues()
        self._restore_interrupted_issues()
        self._restore_disabled_workers()
        self._restore_bg_worker_states()

    def _restore_bg_worker_states(self) -> None:
        """Hydrate background worker heartbeat cache from persisted state."""
        persisted = self._state.get_bg_worker_states()
        restored = 0
        if persisted:
            self._bg_worker_states.update(persisted)
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
        history = list(self._bus.get_history())
        if not history:
            return 0
        latest: dict[str, BackgroundWorkerState] = {}
        existing = set(self._bg_worker_states)
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
            self._bg_worker_states[name] = state
            self._state.set_bg_worker_state(name, state)
        return len(latest)

    async def _start_session(self) -> None:
        """Create a new session log and publish SESSION_START."""
        repo_slug = self._config.repo.replace("/", "-")
        session_start_time = datetime.now(UTC)
        session_id = f"{repo_slug}-{session_start_time.strftime('%Y%m%dT%H%M%S')}"
        self._current_session = SessionLog(
            id=session_id,
            repo=self._config.repo,
            started_at=session_start_time.isoformat(),
        )
        self._session_issue_results = {}
        self._state.reset_session_counters(session_start_time.isoformat())
        self._state.save_session(self._current_session)
        self._bus.set_session_id(session_id)
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SESSION_START,
                session_id=session_id,
                data={"session_id": session_id, "repo": self._config.repo},
            )
        )

    async def _end_session(self) -> None:
        """Close the current session log and publish SESSION_END."""
        if not self._current_session:
            return
        self._current_session.ended_at = datetime.now(UTC).isoformat()
        self._current_session.issues_processed = list(
            self._session_issue_results.keys()
        )
        self._current_session.issues_succeeded = sum(
            1 for s in self._session_issue_results.values() if s
        )
        self._current_session.issues_failed = sum(
            1 for s in self._session_issue_results.values() if not s
        )
        self._current_session.status = SessionStatus.COMPLETED
        self._state.save_session(self._current_session)
        self._state.prune_sessions(
            self._config.repo, self._config.max_sessions_per_repo
        )
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SESSION_END,
                session_id=self._current_session.id,
                data={
                    "session_id": self._current_session.id,
                    "status": "completed",
                    "issues_processed": self._current_session.issues_processed,
                    "issues_succeeded": self._current_session.issues_succeeded,
                    "issues_failed": self._current_session.issues_failed,
                },
            )
        )
        self._current_session = None
        self._bus.set_session_id(None)

    async def run(self) -> None:
        """Run three independent, continuous loops — plan, implement, review.

        Each loop polls for its own work on ``poll_interval`` and processes
        whatever it finds.  No phase blocks another; new issues are picked
        up as soon as they arrive.  Loops run until explicitly stopped.
        """
        self._stop_event.clear()
        self._running = True
        self._restore_state()

        await self._publish_status()
        logger.info(
            "HydraFlow starting — repo=%s label=%s workers=%d poll=%ds",
            self._config.repo,
            ",".join(self._config.ready_label),
            self._config.max_workers,
            self._config.poll_interval,
        )

        await self._prs.ensure_labels_exist()
        self._warn_if_agents_md_missing()
        await self._start_session()

        try:
            await self._supervise_loops()
        finally:
            await self._end_session()
            self._planners.terminate()
            self._agents.terminate()
            self._reviewers.terminate()
            self._hitl_runner.terminate()
            await asyncio.sleep(0)
            self._running = False
            await self._publish_status()
            logger.info("HydraFlow stopped")

    def _warn_if_agents_md_missing(self) -> None:
        """Log a warning if AGENTS.md is absent from the repo root.

        AGENTS.md documents the prompt contracts for all agent roles.  Its
        absence means agent behaviour is undocumented and harder to audit or
        adapt.  Run ``hf init`` or copy AGENTS.md from the HydraFlow repo to
        resolve this.
        """
        agents_md = self._config.repo_root / "AGENTS.md"
        if not agents_md.is_file():
            logger.warning(
                "AGENTS.md not found in %s — agent prompt contracts are "
                "undocumented. Run `hf init` to scaffold it.",
                self._config.repo_root,
            )

    async def _handle_auth_error(self, loop_name: str) -> None:
        """Set auth_failed, publish SYSTEM_ALERT, stop all loops."""
        logger.error(
            "GitHub authentication failed in %r — pausing all loops",
            loop_name,
        )
        self._auth_failed = True
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data={
                    "message": (
                        "GitHub authentication failed. Check your gh token and restart."
                    ),
                    "source": loop_name,
                },
            )
        )
        self._stop_event.set()

    async def _handle_credit_exhaustion(
        self,
        exc: CreditExhaustedError,
        loop_name: str,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> None:
        """Delegate to _pause_for_credits."""
        await self._pause_for_credits(exc, loop_name, tasks, loop_factories)

    async def _restart_loop(
        self,
        loop_name: str,
        exc: BaseException,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> None:
        """Log, publish ERROR event, create a new loop task."""
        logger.error("Loop %r crashed — restarting: %s", loop_name, exc)
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.ERROR,
                data={
                    "message": f"Loop {loop_name} crashed and was restarted",
                    "source": loop_name,
                },
            )
        )
        factory_fn = dict(loop_factories)[loop_name]
        tasks[loop_name] = asyncio.create_task(
            factory_fn(), name=f"hydraflow-{loop_name}"
        )

    async def _handle_loop_exception(
        self,
        name: str,
        exc: BaseException,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> None:
        """Handle a crashed loop task — auth failure, credit exhaustion, or generic restart."""
        if isinstance(exc, AuthenticationError):
            await self._handle_auth_error(name)
            return

        if isinstance(exc, CreditExhaustedError):
            await self._handle_credit_exhaustion(exc, name, tasks, loop_factories)
            return

        await self._restart_loop(name, exc, tasks, loop_factories)

    async def _supervise_loops(self) -> None:
        """Run all loops plus the IssueStore poller, restarting any that crash."""

        async def _store_loop() -> None:
            await self._store.start(self._stop_event)

        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]] = [
            ("store", _store_loop),
            ("triage", self._triage_loop),
            ("plan", self._plan_loop),
            ("implement", self._implement_loop),
            ("review", self._review_loop),
            ("hitl", self._hitl_loop),
            ("memory_sync", self._memory_sync_loop),
            ("metrics", self._metrics_sync_loop),
            ("pr_unsticker", self._pr_unsticker_loop.run),
            ("manifest_refresh", self._manifest_refresh_bg_loop),
            ("report_issue", self._report_issue_loop.run),
            ("epic_monitor", self._epic_monitor_loop.run),
            ("worktree_gc", self._worktree_gc_loop.run),
            ("runs_gc", self._runs_gc_loop.run),
            ("pipeline_stats", self._pipeline_stats_loop),
        ]
        self._prune_stale_disabled_workers({n for n, _ in loop_factories})
        tasks: dict[str, asyncio.Task[None]] = {}
        for name, factory in loop_factories:
            tasks[name] = asyncio.create_task(factory(), name=f"hydraflow-{name}")
        self._loop_tasks = tasks

        try:
            while not self._stop_event.is_set():
                done, _ = await asyncio.wait(
                    tasks.values(), return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    name = task.get_name().removeprefix("hydraflow-")
                    if self._stop_event.is_set():
                        break
                    exc = task.exception()
                    if exc is not None:
                        await self._handle_loop_exception(
                            name, exc, tasks, loop_factories
                        )
                        break
                    else:
                        # Loop completed without error — should never happen;
                        # restart to maintain supervision.
                        logger.warning(
                            "Loop %r completed unexpectedly — restarting", name
                        )
                        factory_fn = dict(loop_factories)[name]
                        tasks[name] = asyncio.create_task(
                            factory_fn(), name=f"hydraflow-{name}"
                        )
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def _polling_loop(
        self,
        name: str,
        work_fn: WorkFn,
        interval: int,
        enabled_name: str | None = None,
    ) -> None:
        """Generic polling loop: check enabled -> try work -> except -> sleep."""
        while not self._stop_event.is_set():
            if enabled_name is not None and not self.is_bg_worker_enabled(enabled_name):
                await self._sleep_or_stop(interval)
                continue
            try:
                did_work = bool(await work_fn())
            except (AuthenticationError, CreditExhaustedError, MemoryError):
                raise
            except Exception:
                display = name.replace("_", " ").capitalize()
                logger.exception(
                    "%s loop iteration failed — will retry next cycle",
                    display,
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.ERROR,
                        data={
                            "message": f"{display} loop error",
                            "source": name,
                        },
                    )
                )
                await self._sleep_or_stop(interval)
                continue
            if did_work:
                continue
            await self._sleep_or_stop(interval)

    async def _triage_loop(self) -> None:
        """Continuously poll for find-labeled issues and triage them."""
        await self._polling_loop(
            "triage",
            self._triager.triage_issues,
            self._config.poll_interval,
            enabled_name="triage",
        )

    async def _plan_loop(self) -> None:
        """Continuously poll for planner-labeled issues."""
        await self._polling_loop(
            "plan",
            self._planner_phase.plan_issues,
            self._config.poll_interval,
            enabled_name="plan",
        )

    async def _implement_loop(self) -> None:
        """Continuously poll for ``hydraflow-ready`` issues and implement them."""
        await self._polling_loop(
            "implement",
            self._do_implement_work,
            self._config.poll_interval,
            enabled_name="implement",
        )

    async def _review_loop(self) -> None:
        """Continuously consume reviewable issues from the store and review their PRs."""
        await self._polling_loop(
            "review",
            self._do_review_work,
            self._config.poll_interval,
            enabled_name="review",
        )

    async def _hitl_loop(self) -> None:
        """Continuously process HITL corrections submitted via the dashboard."""
        await self._polling_loop(
            "hitl",
            self._hitl_phase.process_corrections,
            self._config.poll_interval,
        )

    async def _memory_sync_loop(self) -> None:
        """Continuously poll ``hydraflow-memory`` issues and rebuild the digest."""
        await self._memory_sync_bg.run()

    async def _metrics_sync_loop(self) -> None:
        """Continuously aggregate and persist metrics snapshots."""
        await self._metrics_sync_bg.run()

    async def _manifest_refresh_bg_loop(self) -> None:
        """Continuously rescan the repo and update the project manifest."""
        await self._manifest_refresh_loop.run()

    async def _post_run_hooks(
        self,
        transcript: str,
        source: str,
        reference: str,
        issue_number: int,
        phase: str,
        status: str,
        duration_seconds: float,
        log_file: str,
    ) -> None:
        """Run memory-suggestion filing and transcript summarization for a completed run."""
        await safe_file_memory_suggestion(
            transcript,
            source,
            reference,
            self._config,
            self._prs,
            self._state,
        )
        if issue_number > 0:
            try:
                await self._summarizer.summarize_and_comment(
                    transcript=transcript,
                    issue_number=issue_number,
                    phase=phase,
                    status=status,
                    duration_seconds=duration_seconds,
                    log_file=log_file,
                )
            except Exception:
                logger.exception(
                    "Failed to post transcript summary for issue #%d",
                    issue_number,
                )

    def _log_reference(self, filename: str) -> str:
        """Return a repo- or data-relative log reference for display."""
        path = self._config.log_dir / filename
        return self._config.format_path_for_display(path)

    async def _do_implement_work(self) -> bool:
        """Work function for the implement loop."""
        did_work = False
        # After one poll cycle, release crash-recovered issues
        if self._recovered_issues:
            async with self._active_issues_lock:
                self._active_impl_issues -= self._recovered_issues
                self._recovered_issues.clear()
                self._state.set_active_issue_numbers(
                    list(
                        self._active_impl_issues
                        | self._active_review_issues
                        | self._active_hitl_issues
                    )
                )
        while not self._stop_event.is_set():
            results, issues = await self._implementer.run_batch()
            if not issues:
                break
            did_work = True
            for result in results:
                self._session_issue_results[result.issue_number] = result.success
                if result.transcript:
                    await self._post_run_hooks(
                        transcript=result.transcript,
                        source="implementer",
                        reference=f"issue #{result.issue_number}",
                        issue_number=result.issue_number,
                        phase="implement",
                        status="success" if result.success else "failed",
                        duration_seconds=result.duration_seconds,
                        log_file=self._log_reference(
                            f"issue-{result.issue_number}.txt"
                        ),
                    )
        return did_work

    async def _do_review_work(self) -> bool:
        """Work function for the review loop."""
        did_work = False
        while not self._stop_event.is_set():
            review_issues = self._store.get_reviewable(self._config.batch_size)
            if not review_issues:
                break
            try:
                cycle_did_work = False
                adr_issues = [
                    issue for issue in review_issues if is_adr_issue_title(issue.title)
                ]
                normal_review_issues = [
                    issue
                    for issue in review_issues
                    if issue.id not in {a.id for a in adr_issues}
                ]

                if adr_issues:
                    cycle_did_work = True
                    await self._reviewer.review_adrs(adr_issues)

                if not normal_review_issues:
                    did_work = did_work or cycle_did_work
                    continue

                active_in_store = set(self._store.get_active_issues().keys())
                gh_review_issues = [
                    GitHubIssue.from_task(t) for t in normal_review_issues
                ]
                prs, gh_issues = await self._fetcher.fetch_reviewable_prs(
                    active_in_store, prefetched_issues=gh_review_issues
                )
                if not prs:
                    # Keep review tasks in queue memory when PR visibility lags labels.
                    for issue in normal_review_issues:
                        self._store.enqueue_transition(issue, "review")
                    # Treat as idle so the polling loop applies its normal backoff.
                    did_work = did_work or cycle_did_work
                    break
                cycle_did_work = True
                review_results = await self._reviewer.review_prs(
                    prs, [i.to_task() for i in gh_issues]
                )
                reviewed_issue_numbers = {pr.issue_number for pr in prs}
                for issue in normal_review_issues:
                    if issue.id not in reviewed_issue_numbers:
                        self._store.enqueue_transition(issue, "review")
                for result in review_results:
                    if result.transcript:
                        if result.merged:
                            review_status = "success"
                        elif result.ci_passed is False:
                            review_status = "failed"
                        else:
                            review_status = "completed"
                        await self._post_run_hooks(
                            transcript=result.transcript,
                            source="reviewer",
                            reference=f"PR #{result.pr_number}",
                            issue_number=result.issue_number,
                            phase="review",
                            status=review_status,
                            duration_seconds=result.duration_seconds,
                            log_file=self._log_reference(
                                f"review-pr-{result.pr_number}.txt"
                            ),
                        )
                if any(r.merged for r in review_results):
                    await asyncio.sleep(_POST_MERGE_DELAY)
                    await self._prs.pull_main()
                did_work = did_work or cycle_did_work
            finally:
                release_batch_in_flight(self._store, {i.id for i in review_issues})
        return did_work

    async def _sleep_or_stop(self, seconds: int | float) -> None:
        """Sleep for *seconds*, waking early if stop is requested."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)

    def _compute_resume_time(self, exc: CreditExhaustedError) -> datetime:
        """Compute the UTC datetime at which credit pause should end."""
        buffer = timedelta(minutes=self._config.credit_pause_buffer_minutes)
        now = datetime.now(UTC)
        if exc.resume_at is not None:
            return exc.resume_at + buffer
        return now + timedelta(hours=5) + buffer

    async def _cancel_all_loops_and_runners(
        self, tasks: dict[str, asyncio.Task[None]]
    ) -> None:
        """Cancel all loop tasks and terminate active subprocesses."""
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        self._planners.terminate()
        self._agents.terminate()
        self._reviewers.terminate()
        self._hitl_runner.terminate()

    async def _sleep_until_resume(self, resume_at: datetime) -> None:
        """Sleep until *resume_at* (interruptible by stop event)."""
        pause_seconds = max((resume_at - datetime.now(UTC)).total_seconds(), 0)
        await self._sleep_or_stop(pause_seconds)

    async def _pause_for_credits(
        self,
        exc: CreditExhaustedError,
        source: str,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> None:
        """Pause all loops until API credits reset, then restart them.

        Uses ``asyncio.Lock`` to prevent multiple loops from racing into
        the pause logic simultaneously.
        """
        async with self._credit_pause_lock:
            # If another loop already triggered a pause, skip
            if (
                self._credits_paused_until is not None
                and self._credits_paused_until > datetime.now(UTC)
            ):
                return

            resume_at = self._compute_resume_time(exc)
            self._credits_paused_until = resume_at
            pause_seconds = max((resume_at - datetime.now(UTC)).total_seconds(), 0)

            logger.warning(
                "Credit limit reached (detected in %r). "
                "Pausing all loops until %s (%.0f minutes).",
                source,
                resume_at.isoformat(),
                pause_seconds / 60,
            )

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "message": (
                            f"Credit limit reached. Pausing all loops until "
                            f"{resume_at.strftime('%H:%M UTC')}. "
                            f"Will resume automatically."
                        ),
                        "source": source,
                    },
                )
            )

            await self._cancel_all_loops_and_runners(tasks)

        await self._sleep_until_resume(resume_at)

        if self._stop_event.is_set():
            self._credits_paused_until = None
            return

        await self._resume_loops_after_credit_pause(tasks, loop_factories, source)

    async def _resume_loops_after_credit_pause(
        self,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
        source: str,
    ) -> None:
        """Clear pause state and restart all loops after credit pause."""
        self._credits_paused_until = None
        logger.info("Credit pause ended — restarting all loops")
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data={
                    "message": "Credit pause ended. Resuming all loops.",
                    "source": source,
                },
            )
        )
        for loop_name, factory in loop_factories:
            tasks[loop_name] = asyncio.create_task(
                factory(), name=f"hydraflow-{loop_name}"
            )
