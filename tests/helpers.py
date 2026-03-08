"""Shared test helpers for HydraFlow tests."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable, Coroutine
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from events import HydraFlowEvent
    from models import QueueStats, Task
    from worktree import WorktreeManager


@dataclass
class PipelineRunResult:
    """Structured result returned by ``PipelineHarness.run_full_lifecycle``."""

    task: Task
    triaged_count: int
    plan_results: list
    worker_results: list
    review_results: list
    snapshots: dict[str, QueueStats]
    events: list[HydraFlowEvent]

    def snapshot(self, label: str) -> QueueStats:
        if label not in self.snapshots:
            available = list(self.snapshots)
            msg = f"no snapshot named {label!r}; available: {available}"
            raise KeyError(msg)
        return self.snapshots[label]


def supply_once(*batches):
    """Return batches in order, then ``[]`` forever.

    Used to mock ``IssueStore.get_*`` methods for ``run_refilling_pool`` tests.
    The pool calls ``supply_fn`` repeatedly; this ensures items are returned
    once and the pool terminates cleanly.

    Usage::

        store.get_triageable = supply_once([issue])          # single item
        store.get_triageable = supply_once(*[[i] for i in issues])  # one per call
    """
    items = list(batches)

    def _fn(_max_count=None):
        return items.pop(0) if items else []

    return _fn


class AsyncLineIter:
    """Async iterator yielding raw bytes lines for mock proc.stdout."""

    def __init__(self, lines: list[bytes]) -> None:
        self._it = iter(lines)

    def __aiter__(self):  # noqa: ANN204
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


def make_proc(
    returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
) -> MagicMock:
    """Build a minimal mock subprocess object (communicate style).

    Unlike ``make_streaming_proc`` (which returns a callable factory mock that
    can be passed directly to ``patch("asyncio.create_subprocess_exec", ...)``),
    this helper returns the **raw process mock**.  Callers must wrap it when
    patching::

        proc = make_proc(returncode=0, stdout=b"output")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            ...

    The process mock's ``communicate()`` resolves to ``(stdout, stderr)`` bytes,
    suitable for code paths that call ``await proc.communicate()`` rather than
    iterating ``proc.stdout`` line by line.
    """
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    # kill/terminate are synchronous on asyncio subprocesses.
    proc.kill = MagicMock()
    proc.terminate = MagicMock()
    return proc


def make_streaming_proc(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> AsyncMock:
    """Build a mock for asyncio.create_subprocess_exec with streaming stdout."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    # stdin.write and stdin.close are sync on StreamWriter; drain is async
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    raw_lines = [(ln + "\n").encode() for ln in stdout.split("\n")] if stdout else []
    mock_proc.stdout = AsyncLineIter(raw_lines)
    mock_proc.stderr = AsyncMock()
    mock_proc.stderr.read = AsyncMock(return_value=stderr.encode())
    mock_proc.wait = AsyncMock(return_value=returncode)
    return AsyncMock(return_value=mock_proc)


def instant_sleep_factory(
    stop_event: asyncio.Event,
) -> Callable[[int | float], Coroutine[Any, Any, None]]:
    """Return a sleep function that stops the loop after 2 sleep cycles.

    Used by background worker loop tests to prevent infinite loops.
    """
    call_count = 0

    async def sleep(_seconds: int | float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        await asyncio.sleep(0)

    return sleep


class BgLoopDeps(NamedTuple):
    """Common dependencies for background worker loop tests."""

    config: Any  # HydraFlowConfig
    bus: Any  # EventBus
    stop_event: asyncio.Event
    status_cb: MagicMock
    enabled_cb: Callable[[str], bool]
    sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]]


def make_bg_loop_deps(
    tmp_path: Path,
    *,
    enabled: bool = True,
    **config_overrides: Any,
) -> BgLoopDeps:
    """Create common dependencies for background worker loop tests.

    Returns a BgLoopDeps NamedTuple with config, bus, stop_event,
    status_cb, enabled_cb, and sleep_fn — the 6 constructor args
    shared by all background loop classes.

    Pass interval overrides via config_overrides, e.g.:
        make_bg_loop_deps(tmp_path, memory_sync_interval=30)
    """
    from events import EventBus

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        **config_overrides,
    )
    bus = EventBus()
    stop_event = asyncio.Event()
    sleep_fn = instant_sleep_factory(stop_event)

    return BgLoopDeps(
        config=config,
        bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _name: enabled,
        sleep_fn=sleep_fn,
    )


class ConfigFactory:
    """Factory for HydraFlowConfig instances."""

    @staticmethod
    def create(
        *,
        ready_label: list[str] | None = None,
        batch_size: int = 3,
        max_workers: int = 2,
        max_planners: int = 1,
        max_reviewers: int = 1,
        system_tool: Literal["inherit", "claude", "codex", "pi"] = "inherit",
        system_model: str = "",
        background_tool: Literal["inherit", "claude", "codex", "pi"] = "inherit",
        background_model: str = "",
        implementation_tool: Literal["claude", "codex", "pi"] = "claude",
        model: str = "sonnet",
        review_tool: Literal["claude", "codex", "pi"] = "claude",
        review_model: str = "sonnet",
        ci_check_timeout: int = 600,
        ci_poll_interval: int = 30,
        max_ci_fix_attempts: int = 0,
        max_pre_quality_review_attempts: int = 1,
        max_quality_fix_attempts: int = 2,
        max_review_fix_attempts: int = 2,
        min_review_findings: int = 3,
        max_merge_conflict_fix_attempts: int = 3,
        max_ci_timeout_fix_attempts: int = 2,
        max_issue_attempts: int = 3,
        review_label: list[str] | None = None,
        hitl_label: list[str] | None = None,
        hitl_active_label: list[str] | None = None,
        fixed_label: list[str] | None = None,
        improve_label: list[str] | None = None,
        memory_label: list[str] | None = None,
        transcript_label: list[str] | None = None,
        manifest_label: list[str] | None = None,
        metrics_label: list[str] | None = None,
        dup_label: list[str] | None = None,
        epic_label: list[str] | None = None,
        epic_child_label: list[str] | None = None,
        find_label: list[str] | None = None,
        planner_label: list[str] | None = None,
        planner_tool: Literal["claude", "codex", "pi"] = "claude",
        planner_model: str = "opus",
        triage_tool: Literal["claude", "codex", "pi"] = "claude",
        triage_model: str = "haiku",
        min_plan_words: int = 200,
        max_new_files_warning: int = 5,
        lite_plan_labels: list[str] | None = None,
        repo: str = "test-org/test-repo",
        dry_run: bool = False,
        gh_token: str = "",
        git_user_name: str = "",
        git_user_email: str = "",
        dashboard_enabled: bool = False,
        dashboard_port: int = 15555,
        review_insight_window: int = 10,
        review_pattern_threshold: int = 3,
        subskill_tool: Literal["claude", "codex", "pi"] = "claude",
        subskill_model: str = "haiku",
        max_subskill_attempts: int = 0,
        debug_escalation_enabled: bool = True,
        debug_tool: Literal["claude", "codex", "pi"] = "claude",
        debug_model: str = "opus",
        max_debug_attempts: int = 1,
        subskill_confidence_threshold: float = 0.7,
        poll_interval: int = 5,
        data_poll_interval: int = 300,
        gh_max_retries: int = 3,
        ac_model: str = "sonnet",
        ac_tool: Literal["claude", "codex", "pi"] = "claude",
        verification_judge_tool: Literal["claude", "codex", "pi"] = "claude",
        test_command: str = "make test",
        max_issue_body_chars: int = 10_000,
        max_review_diff_chars: int = 15_000,
        repo_root: Path | None = None,
        worktree_base: Path | None = None,
        state_file: Path | None = None,
        event_log_path: Path | None = None,
        config_file: Path | None = None,
        memory_compaction_model: str = "haiku",
        memory_compaction_tool: Literal["claude", "codex", "pi"] = "claude",
        max_memory_chars: int = 4000,
        max_memory_prompt_chars: int = 4000,
        memory_sync_interval: int = 120,
        metrics_sync_interval: int = 7200,
        manifest_refresh_interval: int = 3600,
        max_manifest_prompt_chars: int = 2000,
        credit_pause_buffer_minutes: int = 1,
        transcript_summarization_enabled: bool = True,
        transcript_summary_model: str = "haiku",
        transcript_summary_tool: Literal["claude", "codex", "pi"] = "claude",
        max_transcript_summary_chars: int = 50_000,
        pr_unstick_interval: int = 3600,
        pr_unstick_batch_size: int = 10,
        max_sessions_per_repo: int = 10,
        execution_mode: Literal["host", "docker"] = "host",
        docker_image: str = "ghcr.io/t-rav/hydraflow-agent:latest",
        docker_cpu_limit: float = 2.0,
        docker_memory_limit: str = "4g",
        docker_pids_limit: int = 256,
        docker_tmp_size: str = "1g",
        docker_network_mode: Literal["bridge", "none", "host"] = "bridge",
        docker_spawn_delay: float = 2.0,
        docker_read_only_root: bool = True,
        docker_no_new_privileges: bool = True,
        ui_dirs: list[str] | None = None,
        docker_network: str = "",
        docker_extra_mounts: list[str] | None = None,
        memory_auto_approve: bool = False,
        memory_prune_stale_items: bool = True,
        transcript_summary_as_issue: bool = False,
        harness_insight_window: int = 20,
        harness_pattern_threshold: int = 3,
        inject_runtime_logs: bool = False,
        max_runtime_log_chars: int = 8_000,
        max_ci_log_chars: int = 12_000,
        code_scanning_enabled: bool = False,
        max_code_scanning_chars: int = 6_000,
        visual_gate_enabled: bool = False,
        visual_gate_bypass: bool = False,
        visual_diff_threshold: float = 0.01,
        visual_max_screens: int = 20,
        visual_per_screen_budget_bytes: int = 5_000_000,
        agent_timeout: int = 3600,
        transcript_summary_timeout: int = 120,
        memory_compaction_timeout: int = 60,
        quality_timeout: int = 3600,
        git_command_timeout: int = 30,
        summarizer_timeout: int = 120,
        error_output_max_chars: int = 3000,
        unstick_auto_merge: bool = True,
        unstick_all_causes: bool = True,
        enable_fresh_branch_rebuild: bool = True,
        max_troubleshooting_prompt_chars: int = 3000,
        epic_group_planning: bool = False,
        epic_auto_decompose: bool = False,
        epic_decompose_complexity_threshold: int = 8,
        epic_monitor_interval: int = 1800,
        worktree_gc_interval: int = 1800,
        epic_stale_days: int = 7,
        epic_merge_strategy: Literal[
            "independent", "bundled", "bundled_hitl", "ordered"
        ] = "independent",
        collaborator_check_enabled: bool = False,
        collaborator_cache_ttl: int = 600,
        artifact_retention_days: int = 30,
        artifact_max_size_mb: int = 500,
        runs_gc_interval: int = 3600,
        release_on_epic_close: bool = False,
        release_version_source: Literal[
            "epic_title", "milestone", "manual"
        ] = "epic_title",
        release_tag_prefix: str = "v",
        baseline_snapshot_patterns: list[str] | None = None,
        baseline_approval_required: bool = True,
        baseline_approvers: list[str] | None = None,
        baseline_max_audit_records: int = 100,
        visual_validation_enabled: bool = True,
        visual_validation_trigger_patterns: list[str] | None = None,
        visual_required_label: str = "hydraflow-visual-required",
        visual_skip_label: str = "hydraflow-visual-skip",
        visual_max_retries: int = 2,
        visual_retry_delay: float = 0.0,
        visual_warn_threshold: float = 0.05,
        visual_fail_threshold: float = 0.15,
        screenshot_redaction_enabled: bool = True,
        screenshot_gist_public: bool = False,
        adr_review_interval: int = 86400,
        adr_review_approval_threshold: int = 2,
        adr_review_max_rounds: int = 3,
        adr_review_enabled: bool = False,
        adr_review_model: str = "sonnet",
    ):
        """Create a HydraFlowConfig with test-friendly defaults."""
        from config import HydraFlowConfig

        root = repo_root or Path("/tmp/hydraflow-test-repo")
        with ExitStack() as stack:
            if execution_mode == "docker" and shutil.which("docker") is None:
                stack.enter_context(
                    patch("shutil.which", return_value="/usr/bin/docker")
                )
            return HydraFlowConfig(
                config_file=config_file,
                ready_label=ready_label if ready_label is not None else ["test-label"],
                batch_size=batch_size,
                max_workers=max_workers,
                max_planners=max_planners,
                max_reviewers=max_reviewers,
                system_tool=system_tool,
                system_model=system_model,
                background_tool=background_tool,
                background_model=background_model,
                implementation_tool=implementation_tool,
                model=model,
                review_tool=review_tool,
                review_model=review_model,
                ci_check_timeout=ci_check_timeout,
                ci_poll_interval=ci_poll_interval,
                max_ci_fix_attempts=max_ci_fix_attempts,
                max_pre_quality_review_attempts=max_pre_quality_review_attempts,
                max_quality_fix_attempts=max_quality_fix_attempts,
                max_review_fix_attempts=max_review_fix_attempts,
                min_review_findings=min_review_findings,
                max_merge_conflict_fix_attempts=max_merge_conflict_fix_attempts,
                max_ci_timeout_fix_attempts=max_ci_timeout_fix_attempts,
                max_issue_attempts=max_issue_attempts,
                review_label=review_label
                if review_label is not None
                else ["hydraflow-review"],
                hitl_label=hitl_label if hitl_label is not None else ["hydraflow-hitl"],
                hitl_active_label=hitl_active_label
                if hitl_active_label is not None
                else ["hydraflow-hitl-active"],
                fixed_label=fixed_label
                if fixed_label is not None
                else ["hydraflow-fixed"],
                improve_label=improve_label
                if improve_label is not None
                else ["hydraflow-improve"],
                memory_label=memory_label
                if memory_label is not None
                else ["hydraflow-memory"],
                transcript_label=transcript_label
                if transcript_label is not None
                else ["hydraflow-transcript"],
                manifest_label=manifest_label
                if manifest_label is not None
                else ["hydraflow-manifest"],
                metrics_label=metrics_label
                if metrics_label is not None
                else ["hydraflow-metrics"],
                dup_label=dup_label if dup_label is not None else ["hydraflow-dup"],
                epic_label=epic_label if epic_label is not None else ["hydraflow-epic"],
                epic_child_label=(
                    epic_child_label
                    if epic_child_label is not None
                    else ["hydraflow-epic-child"]
                ),
                find_label=find_label if find_label is not None else ["hydraflow-find"],
                planner_label=planner_label
                if planner_label is not None
                else ["hydraflow-plan"],
                planner_tool=planner_tool,
                planner_model=planner_model,
                triage_tool=triage_tool,
                triage_model=triage_model,
                min_plan_words=min_plan_words,
                max_new_files_warning=max_new_files_warning,
                lite_plan_labels=lite_plan_labels
                if lite_plan_labels is not None
                else ["bug", "typo", "docs"],
                repo=repo,
                dry_run=dry_run,
                gh_token=gh_token,
                git_user_name=git_user_name,
                git_user_email=git_user_email,
                dashboard_enabled=dashboard_enabled,
                dashboard_port=dashboard_port,
                ac_model=ac_model,
                ac_tool=ac_tool,
                verification_judge_tool=verification_judge_tool,
                review_insight_window=review_insight_window,
                review_pattern_threshold=review_pattern_threshold,
                subskill_tool=subskill_tool,
                subskill_model=subskill_model,
                max_subskill_attempts=max_subskill_attempts,
                debug_escalation_enabled=debug_escalation_enabled,
                debug_tool=debug_tool,
                debug_model=debug_model,
                max_debug_attempts=max_debug_attempts,
                subskill_confidence_threshold=subskill_confidence_threshold,
                poll_interval=poll_interval,
                data_poll_interval=data_poll_interval,
                gh_max_retries=gh_max_retries,
                test_command=test_command,
                max_issue_body_chars=max_issue_body_chars,
                max_review_diff_chars=max_review_diff_chars,
                repo_root=root,
                worktree_base=worktree_base or root.parent / "test-worktrees",
                state_file=state_file or root / ".hydraflow-state.json",
                event_log_path=event_log_path or root / ".hydraflow-events.jsonl",
                memory_compaction_model=memory_compaction_model,
                memory_compaction_tool=memory_compaction_tool,
                max_memory_chars=max_memory_chars,
                max_memory_prompt_chars=max_memory_prompt_chars,
                memory_sync_interval=memory_sync_interval,
                metrics_sync_interval=metrics_sync_interval,
                manifest_refresh_interval=manifest_refresh_interval,
                max_manifest_prompt_chars=max_manifest_prompt_chars,
                credit_pause_buffer_minutes=credit_pause_buffer_minutes,
                transcript_summarization_enabled=transcript_summarization_enabled,
                transcript_summary_model=transcript_summary_model,
                transcript_summary_tool=transcript_summary_tool,
                max_transcript_summary_chars=max_transcript_summary_chars,
                pr_unstick_interval=pr_unstick_interval,
                pr_unstick_batch_size=pr_unstick_batch_size,
                max_sessions_per_repo=max_sessions_per_repo,
                execution_mode=execution_mode,
                docker_image=docker_image,
                docker_cpu_limit=docker_cpu_limit,
                docker_memory_limit=docker_memory_limit,
                docker_pids_limit=docker_pids_limit,
                docker_tmp_size=docker_tmp_size,
                docker_network_mode=docker_network_mode,
                docker_spawn_delay=docker_spawn_delay,
                docker_read_only_root=docker_read_only_root,
                docker_no_new_privileges=docker_no_new_privileges,
                ui_dirs=ui_dirs if ui_dirs is not None else ["ui"],
                docker_network=docker_network,
                docker_extra_mounts=docker_extra_mounts
                if docker_extra_mounts is not None
                else [],
                memory_auto_approve=memory_auto_approve,
                memory_prune_stale_items=memory_prune_stale_items,
                transcript_summary_as_issue=transcript_summary_as_issue,
                harness_insight_window=harness_insight_window,
                harness_pattern_threshold=harness_pattern_threshold,
                inject_runtime_logs=inject_runtime_logs,
                max_runtime_log_chars=max_runtime_log_chars,
                max_ci_log_chars=max_ci_log_chars,
                code_scanning_enabled=code_scanning_enabled,
                max_code_scanning_chars=max_code_scanning_chars,
                visual_gate_enabled=visual_gate_enabled,
                visual_gate_bypass=visual_gate_bypass,
                agent_timeout=agent_timeout,
                transcript_summary_timeout=transcript_summary_timeout,
                memory_compaction_timeout=memory_compaction_timeout,
                quality_timeout=quality_timeout,
                git_command_timeout=git_command_timeout,
                summarizer_timeout=summarizer_timeout,
                error_output_max_chars=error_output_max_chars,
                unstick_auto_merge=unstick_auto_merge,
                unstick_all_causes=unstick_all_causes,
                enable_fresh_branch_rebuild=enable_fresh_branch_rebuild,
                max_troubleshooting_prompt_chars=max_troubleshooting_prompt_chars,
                epic_group_planning=epic_group_planning,
                epic_auto_decompose=epic_auto_decompose,
                epic_decompose_complexity_threshold=epic_decompose_complexity_threshold,
                epic_monitor_interval=epic_monitor_interval,
                worktree_gc_interval=worktree_gc_interval,
                epic_stale_days=epic_stale_days,
                epic_merge_strategy=epic_merge_strategy,
                collaborator_check_enabled=collaborator_check_enabled,
                collaborator_cache_ttl=collaborator_cache_ttl,
                artifact_retention_days=artifact_retention_days,
                artifact_max_size_mb=artifact_max_size_mb,
                runs_gc_interval=runs_gc_interval,
                release_on_epic_close=release_on_epic_close,
                release_version_source=release_version_source,
                release_tag_prefix=release_tag_prefix,
                baseline_snapshot_patterns=baseline_snapshot_patterns
                if baseline_snapshot_patterns is not None
                else ["**/__snapshots__/**", "**/*.snap.png", "**/*.baseline.png"],
                baseline_approval_required=baseline_approval_required,
                baseline_approvers=baseline_approvers
                if baseline_approvers is not None
                else [],
                baseline_max_audit_records=baseline_max_audit_records,
                visual_validation_enabled=visual_validation_enabled,
                visual_diff_threshold=visual_diff_threshold,
                visual_warn_threshold=visual_warn_threshold,
                visual_max_screens=visual_max_screens,
                visual_per_screen_budget_bytes=visual_per_screen_budget_bytes,
                visual_validation_trigger_patterns=(
                    visual_validation_trigger_patterns
                    if visual_validation_trigger_patterns is not None
                    else [
                        "src/ui/**",
                        "ui/**",
                        "frontend/**",
                        "web/**",
                        "*.css",
                        "*.scss",
                        "*.tsx",
                        "*.jsx",
                        "*.html",
                    ]
                ),
                visual_required_label=visual_required_label,
                visual_skip_label=visual_skip_label,
                visual_max_retries=visual_max_retries,
                visual_retry_delay=visual_retry_delay,
                visual_fail_threshold=visual_fail_threshold,
                screenshot_redaction_enabled=screenshot_redaction_enabled,
                screenshot_gist_public=screenshot_gist_public,
                adr_review_interval=adr_review_interval,
                adr_review_approval_threshold=adr_review_approval_threshold,
                adr_review_max_rounds=adr_review_max_rounds,
                adr_review_enabled=adr_review_enabled,
                adr_review_model=adr_review_model,
            )


class PipelineHarness:
    """Utility for wiring all phases with shared real stores in tests."""

    def __init__(self, tmp_path: Path, *, config=None):
        from events import EventBus
        from hitl_phase import HITLPhase
        from implement_phase import ImplementPhase
        from issue_store import IssueStore
        from plan_phase import PlanPhase
        from post_merge_handler import PostMergeHandler
        from review_phase import ReviewPhase
        from state import StateTracker
        from triage_phase import TriagePhase

        self.config = config or ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            max_workers=1,
            max_planners=1,
            max_reviewers=1,
            visual_validation_enabled=False,
            code_scanning_enabled=False,
            max_ci_fix_attempts=0,
        )
        self._ensure_test_dirs()

        self.bus = EventBus()
        self.state = StateTracker(self.config.state_file)
        self.fetcher = AsyncMock()
        self.store = IssueStore(self.config, self.fetcher, self.bus)
        self.stop_event = asyncio.Event()

        self.prs = AsyncMock()
        self._setup_pr_manager_mocks()

        self.triage_runner = AsyncMock()
        self.triage_runner.evaluate = AsyncMock()
        self.planners = AsyncMock()
        self.planners.plan = AsyncMock()
        self.agents = AsyncMock()
        self.agents.run = AsyncMock()
        self.reviewers = AsyncMock()
        self.reviewers.review = AsyncMock()
        self.reviewers.fix_ci = AsyncMock()
        self.hitl_runner = AsyncMock()
        self.hitl_runner.run = AsyncMock()
        self._hitl_fetcher = AsyncMock()
        self._hitl_fetcher.fetch_issue_by_number = AsyncMock()

        self.worktrees = AsyncMock()
        self.worktrees.create = AsyncMock(side_effect=self._default_worktree_create)
        self.worktrees.destroy = AsyncMock()

        self._conflict_resolver = MagicMock()
        self._conflict_resolver.merge_with_main = AsyncMock(return_value=True)
        self.post_merge = PostMergeHandler(
            config=self.config,
            state=self.state,
            prs=self.prs,
            event_bus=self.bus,
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

        self.triage_phase = TriagePhase(
            self.config,
            self.state,
            self.store,
            self.triage_runner,
            self.prs,
            self.bus,
            self.stop_event,
        )
        self.plan_phase = PlanPhase(
            self.config,
            self.state,
            self.store,
            self.planners,
            self.prs,
            self.bus,
            self.stop_event,
        )
        self.implement_phase = ImplementPhase(
            config=self.config,
            state=self.state,
            worktrees=self.worktrees,
            agents=self.agents,
            prs=self.prs,
            store=self.store,
            stop_event=self.stop_event,
        )
        self.review_phase = ReviewPhase(
            config=self.config,
            state=self.state,
            worktrees=self.worktrees,
            reviewers=self.reviewers,
            prs=self.prs,
            stop_event=self.stop_event,
            store=self.store,
            event_bus=self.bus,
            conflict_resolver=self._conflict_resolver,
            post_merge=self.post_merge,
        )
        self.hitl_phase = HITLPhase(
            config=self.config,
            state=self.state,
            store=self.store,
            fetcher=self._hitl_fetcher,
            worktrees=self.worktrees,
            hitl_runner=self.hitl_runner,
            prs=self.prs,
            event_bus=self.bus,
            stop_event=self.stop_event,
        )

    def _ensure_test_dirs(self) -> None:
        paths = {
            self.config.repo_root,
            self.config.worktree_base,
            self.config.state_file.parent,
            self.config.data_root,
            self.config.plans_dir,
            self.config.memory_dir,
            self.config.log_dir,
            self.config.visual_reports_dir,
        }
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)

    def _setup_pr_manager_mocks(self) -> None:
        from tests.conftest import PRInfoFactory

        counter = iter(range(10_000, 20_000))

        def _make_pr(issue, branch, *, draft=False, **_unused):
            number = next(counter)
            issue_number = getattr(issue, "number", getattr(issue, "id", 0))
            return PRInfoFactory.create(
                number=number,
                issue_number=issue_number,
                branch=branch,
                draft=draft,
            )

        def _find_pr(branch, *, issue_number=None, **_unused):
            number = next(counter)
            return PRInfoFactory.create(
                number=number,
                issue_number=issue_number or 0,
                branch=branch,
            )

        self.prs.transition = AsyncMock()
        self.prs.swap_pipeline_labels = AsyncMock()
        self.prs.add_labels = AsyncMock()
        self.prs.remove_label = AsyncMock()
        self.prs.post_comment = AsyncMock()
        self.prs.post_pr_comment = AsyncMock()
        self.prs.submit_review = AsyncMock()
        self.prs.create_task = AsyncMock(return_value=12345)
        self.prs.close_task = AsyncMock()
        self.prs.close_issue = AsyncMock()
        self.prs.push_branch = AsyncMock(return_value=True)
        self.prs.create_pr = AsyncMock(side_effect=_make_pr)
        self.prs.find_open_pr_for_branch = AsyncMock(side_effect=_find_pr)
        self.prs.branch_has_diff_from_main = AsyncMock(return_value=True)
        self.prs.add_pr_labels = AsyncMock()
        self.prs.get_pr_diff = AsyncMock(return_value="diff --git a/x b/x")
        self.prs.get_pr_head_sha = AsyncMock(return_value="abc123")
        self.prs.get_pr_diff_names = AsyncMock(return_value=["src/app.py"])
        self.prs.get_pr_approvers = AsyncMock(return_value=["octocat"])
        self.prs.fetch_code_scanning_alerts = AsyncMock(return_value=[])
        self.prs.wait_for_ci = AsyncMock(return_value=(True, "CI passed"))
        self.prs.fetch_ci_failure_logs = AsyncMock(return_value="")
        self.prs.merge_pr = AsyncMock(return_value=True)

    def _default_worktree_create(self, issue_number: int, branch: str):
        path = self.config.worktree_path_for_issue(issue_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def seed_issue(self, task, stage: str = "find") -> None:
        """Place *task* in the requested queue stage."""
        self.store.enqueue_transition(task, stage)

    async def run_full_lifecycle(
        self,
        *,
        task_id: int,
        seed_stage: str = "find",
        tags: list[str] | None = None,
        triage_result=None,
        plan_result=None,
        worker_result=None,
        review_verdict="approve",
    ) -> PipelineRunResult:
        """Drive an issue through triage → plan → implement → review."""
        from models import ReviewVerdict
        from tests.conftest import (
            PlanResultFactory,
            ReviewResultFactory,
            TaskFactory,
            TriageResultFactory,
            WorkerResultFactory,
        )

        tag_list = tags or [self.config.find_label[0]]
        task = TaskFactory.create(id=task_id, tags=tag_list)
        self.seed_issue(task, seed_stage)

        triage_return = (
            triage_result
            if triage_result is not None
            else TriageResultFactory.create(issue_number=task.id, ready=True)
        )
        plan_return = (
            plan_result
            if plan_result is not None
            else PlanResultFactory.create(issue_number=task.id)
        )

        branch = self.config.branch_for_issue(task.id)
        worktree_path = self.config.worktree_path_for_issue(task.id)
        worker_return = (
            worker_result
            if worker_result is not None
            else WorkerResultFactory.create(
                issue_number=task.id,
                branch=branch,
                worktree_path=str(worktree_path),
                success=True,
                commits=1,
            )
        )

        self.triage_runner.evaluate.return_value = triage_return
        self.planners.plan.return_value = plan_return
        self.agents.run.return_value = worker_return

        verdict_enum = (
            review_verdict
            if isinstance(review_verdict, ReviewVerdict)
            else ReviewVerdict(review_verdict)
        )
        previous_side_effect = self.reviewers.review.side_effect

        async def _review_side_effect(
            pr, issue, wt_path, diff, *, worker_id, **_kwargs
        ):
            return ReviewResultFactory.create(
                pr_number=pr.number,
                issue_number=issue.id,
                verdict=verdict_enum,
                merged=True,
                ci_passed=True,
            )

        self.reviewers.review.side_effect = _review_side_effect

        snapshots: dict[str, QueueStats] = {}

        def _capture(label: str) -> None:
            snapshots[label] = self.store.get_queue_stats().model_copy(deep=True)

        try:
            triaged = await self.triage_phase.triage_issues()
            _capture("after_triage")

            plan_results = await self.plan_phase.plan_issues()
            _capture("after_plan")

            worker_results, _ = await self.implement_phase.run_batch()
            _capture("after_implement")

            assert worker_results, (
                "implement_phase produced no results; check task seeding and ready-queue routing"
            )
            pr_info = worker_results[0].pr_info
            assert pr_info is not None, (
                "worker_results[0].pr_info is None; implement phase did not create a PR"
            )
            review_candidates = self.store.get_reviewable(self.config.batch_size)
            review_results = await self.review_phase.review_prs(
                [pr_info], review_candidates
            )
            _capture("after_review")

            await asyncio.sleep(0)
            events = self.bus.get_history()
        finally:
            self.reviewers.review.side_effect = previous_side_effect

        return PipelineRunResult(
            task=task,
            triaged_count=triaged,
            plan_results=plan_results,
            worker_results=worker_results,
            review_results=review_results,
            snapshots=snapshots,
            events=events,
        )


def make_docker_manager(tmp_path: Path) -> WorktreeManager:
    """Create a WorktreeManager with docker execution mode.

    Promoted from test_worktree._make_docker_manager() for reuse across test files.
    """
    from unittest.mock import patch

    from worktree import WorktreeManager

    with patch("shutil.which", return_value="/usr/bin/docker"):
        cfg = ConfigFactory.create(
            execution_mode="docker",
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
    return WorktreeManager(cfg)


class AuditCheckFactory:
    """Factory for AuditCheck instances."""

    @staticmethod
    def create(
        *,
        name: str = "Test Check",
        status: str = "present",
        detail: str = "",
        critical: bool = False,
    ):
        """Create an AuditCheck with test-friendly defaults."""
        from models import AuditCheck, AuditCheckStatus

        return AuditCheck(
            name=name,
            status=AuditCheckStatus(status),
            detail=detail,
            critical=critical,
        )


class AuditResultFactory:
    """Factory for AuditResult instances."""

    @staticmethod
    def create(
        *,
        repo: str = "test-org/test-repo",
        checks: list | None = None,
    ):
        """Create an AuditResult with test-friendly defaults."""
        from models import AuditResult

        return AuditResult(
            repo=repo,
            checks=checks if checks is not None else [],
        )


def make_plan_phase(
    config,
    *,
    summarizer=None,
):
    """Build a PlanPhase with mock dependencies.

    Promoted from test_plan_phase._make_phase() for reuse across test files.

    Returns (phase, state, planners_mock, prs_mock, store, stop_event).
    """
    from events import EventBus
    from issue_store import IssueStore
    from plan_phase import PlanPhase
    from state import StateTracker

    state = StateTracker(config.state_file)
    bus = EventBus()
    fetcher = AsyncMock()
    store = IssueStore(config, fetcher, bus)
    planners = AsyncMock()
    prs = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.remove_label = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.transition = AsyncMock()
    prs.create_task = AsyncMock(return_value=99)
    prs.close_task = AsyncMock()
    stop_event = asyncio.Event()
    phase = PlanPhase(
        config,
        state,
        store,
        planners,
        prs,
        bus,
        stop_event,
        transcript_summarizer=summarizer,
    )
    return phase, state, planners, prs, store, stop_event


def make_implement_phase(
    config,
    issues,
    *,
    agent_run=None,
    success=True,
    push_return=True,
    create_pr_return=None,
):
    """Build an ImplementPhase with standard mocks.

    Promoted from test_implement_phase._make_phase() for reuse across test files.

    Returns (phase, mock_wt, mock_prs).
    """
    from implement_phase import ImplementPhase
    from issue_store import IssueStore
    from models import WorkerResult
    from state import StateTracker
    from tests.conftest import PRInfoFactory, WorkerResultFactory

    state = StateTracker(config.state_file)
    stop_event = asyncio.Event()

    if agent_run is None:

        async def _default_agent_run(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
        ) -> WorkerResult:
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=success,
                worktree_path=str(wt_path),
            )

        agent_run = _default_agent_run

    mock_agents = AsyncMock()
    mock_agents.run = agent_run

    # Mock IssueStore — get_implementable returns the supplied issues once
    mock_store = AsyncMock(spec=IssueStore)
    mock_store.get_implementable = supply_once(*[[i] for i in issues])
    mock_store.mark_active = lambda num, stage: None
    mock_store.mark_complete = lambda num: None
    mock_store.is_active = lambda num: False

    mock_wt = AsyncMock()
    mock_wt.create = AsyncMock(
        side_effect=lambda num, branch: config.worktree_base / f"issue-{num}"
    )

    mock_prs = AsyncMock()
    mock_prs.push_branch = AsyncMock(return_value=push_return)
    mock_prs.create_pr = AsyncMock(
        return_value=create_pr_return
        if create_pr_return is not None
        else PRInfoFactory.create()
    )
    mock_prs.find_open_pr_for_branch = AsyncMock(return_value=None)
    mock_prs.branch_has_diff_from_main = AsyncMock(return_value=True)
    mock_prs.add_labels = AsyncMock()
    mock_prs.remove_label = AsyncMock()
    mock_prs.swap_pipeline_labels = AsyncMock()
    mock_prs.transition = AsyncMock()
    mock_prs.post_comment = AsyncMock()
    mock_prs.close_task = AsyncMock()
    mock_prs.add_pr_labels = AsyncMock()

    phase = ImplementPhase(
        config=config,
        state=state,
        worktrees=mock_wt,
        agents=mock_agents,
        prs=mock_prs,
        store=mock_store,
        stop_event=stop_event,
    )

    return phase, mock_wt, mock_prs


def make_hitl_phase(config):
    """Build a HITLPhase with mock dependencies.

    Promoted from test_hitl_phase._make_phase() for reuse across test files.

    Returns (phase, state, fetcher_mock, prs_mock, worktrees_mock,
             hitl_runner_mock, bus).
    """
    from events import EventBus
    from hitl_phase import HITLPhase
    from issue_store import IssueStore
    from state import StateTracker

    state = StateTracker(config.state_file)
    bus = EventBus()
    fetcher_mock = AsyncMock()
    store = IssueStore(config, AsyncMock(), bus)
    worktrees = AsyncMock()
    worktrees.create = AsyncMock(return_value=config.worktree_base / "issue-42")
    worktrees.destroy = AsyncMock()
    hitl_runner = AsyncMock()
    prs = AsyncMock()
    prs.remove_label = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.push_branch = AsyncMock(return_value=True)
    prs.post_comment = AsyncMock()
    stop_event = asyncio.Event()
    phase = HITLPhase(
        config,
        state,
        store,
        fetcher_mock,
        worktrees,
        hitl_runner,
        prs,
        bus,
        stop_event,
    )
    return phase, state, fetcher_mock, prs, worktrees, hitl_runner, bus


def make_triage_phase(config):
    """Build a TriagePhase with mock dependencies.

    Promoted from test_triage_phase._make_phase() for reuse across test files.

    Returns (phase, state, triage_mock, prs_mock, store, stop_event).
    """
    from events import EventBus
    from issue_store import IssueStore
    from state import StateTracker
    from triage_phase import TriagePhase

    state = StateTracker(config.state_file)
    bus = EventBus()
    fetcher = AsyncMock()
    store = IssueStore(config, fetcher, bus)
    triage = AsyncMock()
    prs = AsyncMock()
    prs.remove_label = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    stop_event = asyncio.Event()
    phase = TriagePhase(config, state, store, triage, prs, bus, stop_event)
    return phase, state, triage, prs, store, stop_event


def make_conflict_resolver(config, *, agents=None):
    """Build a MergeConflictResolver with standard mock dependencies.

    Promoted from test_merge_conflict_resolver._make_resolver() for reuse
    across test files.
    """
    from events import EventBus
    from merge_conflict_resolver import MergeConflictResolver
    from state import StateTracker

    state = StateTracker(config.state_file)
    return MergeConflictResolver(
        config=config,
        worktrees=AsyncMock(),
        agents=agents,
        prs=AsyncMock(),
        event_bus=EventBus(),
        state=state,
        summarizer=None,
    )


def make_review_phase(
    config,
    *,
    event_bus=None,
    agents=None,
    ac_generator=None,
    default_mocks: bool = False,
    review_result=None,
    issue_number: int = 42,
    baseline_policy=None,
):
    """Build a ReviewPhase with standard mock dependencies.

    Promoted from test_review_phase._make_phase() for reuse across test files.

    Args:
        agents: Optional AgentRunner mock; wired into a MergeConflictResolver.
        ac_generator: Optional AcceptanceCriteriaGenerator mock; wired into a
            PostMergeHandler.

    When ``default_mocks=True``, the phase is returned with the standard happy-path
    mocks pre-wired so tests only need to override the specific mocks they care about:

    * ``_reviewers.review`` → returns *review_result* (default ``ReviewResultFactory.create()``)
    * ``_prs.get_pr_diff`` → ``"diff text"``
    * ``_prs.push_branch`` → ``True``
    * ``_prs.merge_pr`` → ``True``
    * ``_prs.remove_label`` / ``add_labels`` / ``post_pr_comment`` / ``submit_review``
    * worktree directory ``issue-{issue_number}`` created under ``config.worktree_base``
    """
    from events import EventBus
    from issue_store import IssueStore
    from merge_conflict_resolver import MergeConflictResolver
    from post_merge_handler import PostMergeHandler
    from review_phase import ReviewPhase
    from state import StateTracker

    state = StateTracker(config.state_file)
    stop_event = asyncio.Event()

    mock_wt = AsyncMock()
    mock_wt.destroy = AsyncMock()

    mock_reviewers = AsyncMock()
    mock_prs = AsyncMock()

    mock_store = MagicMock(spec=IssueStore)
    mock_store.mark_active = lambda _num, _stage: None
    mock_store.mark_complete = lambda _num: None
    mock_store.is_active = lambda _num: False

    bus = event_bus or EventBus()

    conflict_resolver = None
    if agents is not None:
        conflict_resolver = MergeConflictResolver(
            config=config,
            worktrees=mock_wt,
            agents=agents,
            prs=mock_prs,
            event_bus=bus,
            state=state,
            summarizer=None,
        )

    post_merge = None
    if ac_generator is not None:
        post_merge = PostMergeHandler(
            config=config,
            state=state,
            prs=mock_prs,
            event_bus=bus,
            ac_generator=ac_generator,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

    phase = ReviewPhase(
        config=config,
        state=state,
        worktrees=mock_wt,
        reviewers=mock_reviewers,
        prs=mock_prs,
        stop_event=stop_event,
        store=mock_store,
        event_bus=bus,
        conflict_resolver=conflict_resolver,
        post_merge=post_merge,
        baseline_policy=baseline_policy,
    )

    # Default fix_review_findings to return no-op so _attempt_review_fix
    # doesn't loop unexpectedly in tests that don't care about it.
    from models import ReviewResult as _RR

    _no_fix = _RR(pr_number=0, issue_number=0, fixes_made=False)
    phase._reviewers.fix_review_findings = AsyncMock(return_value=_no_fix)

    if default_mocks:
        from tests.conftest import ReviewResultFactory

        phase._reviewers.review = AsyncMock(
            return_value=review_result or ReviewResultFactory.create()
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock(return_value=True)

        wt = config.worktree_base / f"issue-{issue_number}"
        wt.mkdir(parents=True, exist_ok=True)

    return phase
