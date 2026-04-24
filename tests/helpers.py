"""Shared test helpers for HydraFlow tests."""

from __future__ import annotations

import asyncio

SMOKE_SUITE_SIZE = 8
import shutil
from collections.abc import Callable, Coroutine
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, NamedTuple
from unittest.mock import AsyncMock, MagicMock, patch

from config import Credentials

if TYPE_CHECKING:
    from events import HydraFlowEvent
    from models import QueueStats, Task
    from state import StateTracker
    from workspace import WorkspaceManager


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
    loop_deps: Any  # LoopDeps


def make_bg_loop_deps(
    tmp_path: Path,
    *,
    enabled: bool = True,
    **config_overrides: Any,
) -> BgLoopDeps:
    """Create common dependencies for background worker loop tests.

    Returns a BgLoopDeps NamedTuple with config, bus, stop_event,
    status_cb, enabled_cb, sleep_fn, and loop_deps — the shared
    constructor args for all background loop classes.

    Pass interval overrides via config_overrides, e.g.:
        make_bg_loop_deps(tmp_path, memory_sync_interval=30)
    """
    from base_background_loop import LoopDeps
    from events import EventBus

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        **config_overrides,
    )
    bus = EventBus()
    stop_event = asyncio.Event()
    sleep_fn = instant_sleep_factory(stop_event)
    status_cb = MagicMock()

    def enabled_cb(_name: str) -> bool:
        return enabled

    loop_deps = LoopDeps(
        event_bus=bus,
        stop_event=stop_event,
        status_cb=status_cb,
        enabled_cb=enabled_cb,
        sleep_fn=sleep_fn,  # override default stop_event-based sleep for tests
    )

    return BgLoopDeps(
        config=config,
        bus=bus,
        stop_event=stop_event,
        status_cb=status_cb,
        enabled_cb=enabled_cb,
        sleep_fn=sleep_fn,
        loop_deps=loop_deps,
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
        dup_label: list[str] | None = None,
        epic_label: list[str] | None = None,
        epic_child_label: list[str] | None = None,
        verify_label: list[str] | None = None,
        find_label: list[str] | None = None,
        planner_label: list[str] | None = None,
        parked_label: list[str] | None = None,
        diagnose_label: list[str] | None = None,
        planner_tool: Literal["claude", "codex", "pi"] = "claude",
        planner_model: str = "opus",
        triage_tool: Literal["claude", "codex", "pi"] = "claude",
        triage_model: str = "haiku",
        min_plan_words: int = 200,
        max_new_files_warning: int = 5,
        lite_plan_labels: list[str] | None = None,
        repo: str = "test-org/test-repo",
        dry_run: bool = False,
        git_user_name: str = "",
        git_user_email: str = "",
        dashboard_enabled: bool = False,
        dashboard_port: int = 15555,
        dashboard_host: str = "127.0.0.1",
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
        workspace_base: Path | None = None,
        state_file: Path | None = None,
        event_log_path: Path | None = None,
        config_file: Path | None = None,
        memory_compaction_model: str = "haiku",
        memory_compaction_tool: Literal["claude", "codex", "pi"] = "claude",
        max_memory_chars: int = 4000,
        max_memory_prompt_chars: int = 4000,
        memory_sync_interval: int = 120,
        credit_pause_buffer_minutes: int = 1,
        transcript_summarization_enabled: bool = True,
        transcript_summary_model: str = "haiku",
        transcript_summary_tool: Literal["claude", "codex", "pi"] = "claude",
        max_transcript_summary_chars: int = 50_000,
        pr_unstick_interval: int = 3600,
        dependabot_merge_interval: int = 3600,
        stale_issue_interval: int = 86400,
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
        harness_insight_window: int = 20,
        harness_pattern_threshold: int = 3,
        max_runtime_log_chars: int = 8_000,
        max_ci_log_chars: int = 12_000,
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
        epic_decompose_complexity_threshold: int = 8,
        epic_monitor_interval: int = 1800,
        epic_sweep_interval: int = 3600,
        workspace_gc_interval: int = 1800,
        epic_stale_days: int = 7,
        epic_merge_strategy: Literal[
            "independent", "bundled", "bundled_hitl", "ordered"
        ] = "independent",
        collaborator_check_enabled: bool = False,
        collaborator_cache_ttl: int = 600,
        artifact_retention_days: int = 30,
        artifact_max_size_mb: int = 500,
        runs_gc_interval: int = 3600,
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
        health_monitor_interval: int = 7200,
        adr_review_model: str = "sonnet",
        adr_pre_review: bool = True,
        # Prompt budget configuration
        max_discussion_comment_chars: int = 500,
        max_common_feedback_chars: int = 2_000,
        max_impl_plan_chars: int = 6_000,
        max_review_feedback_chars: int = 2_000,
        max_planner_comment_chars: int = 1_000,
        max_planner_line_chars: int = 500,
        max_planner_failed_plan_chars: int = 4_000,
        max_hitl_correction_chars: int = 4_000,
        max_hitl_cause_chars: int = 2_000,
        max_ci_log_prompt_chars: int = 6_000,
        max_unsticker_cause_chars: int = 3_000,
        max_verification_instructions_chars: int = 50_000,
        hindsight_timeout: int = 30,
        security_patch_interval: int = 3600,
        security_patch_severity_threshold: str = "high",
        code_grooming_interval: int = 86400,
        code_grooming_enabled: bool = False,
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
                dup_label=dup_label if dup_label is not None else ["hydraflow-dup"],
                epic_label=epic_label if epic_label is not None else ["hydraflow-epic"],
                epic_child_label=(
                    epic_child_label
                    if epic_child_label is not None
                    else ["hydraflow-epic-child"]
                ),
                verify_label=(
                    verify_label if verify_label is not None else ["hydraflow-verify"]
                ),
                find_label=find_label if find_label is not None else ["hydraflow-find"],
                planner_label=planner_label
                if planner_label is not None
                else ["hydraflow-plan"],
                parked_label=parked_label
                if parked_label is not None
                else ["hydraflow-parked"],
                diagnose_label=diagnose_label
                if diagnose_label is not None
                else ["hydraflow-diagnose"],
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
                git_user_name=git_user_name,
                git_user_email=git_user_email,
                dashboard_enabled=dashboard_enabled,
                dashboard_port=dashboard_port,
                dashboard_host=dashboard_host,
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
                workspace_base=workspace_base or root.parent / "test-worktrees",
                state_file=state_file or root / ".hydraflow-state.json",
                event_log_path=event_log_path or root / ".hydraflow-events.jsonl",
                memory_compaction_model=memory_compaction_model,
                memory_compaction_tool=memory_compaction_tool,
                max_memory_chars=max_memory_chars,
                max_memory_prompt_chars=max_memory_prompt_chars,
                memory_sync_interval=memory_sync_interval,
                credit_pause_buffer_minutes=credit_pause_buffer_minutes,
                transcript_summarization_enabled=transcript_summarization_enabled,
                transcript_summary_model=transcript_summary_model,
                transcript_summary_tool=transcript_summary_tool,
                max_transcript_summary_chars=max_transcript_summary_chars,
                pr_unstick_interval=pr_unstick_interval,
                dependabot_merge_interval=dependabot_merge_interval,
                stale_issue_interval=stale_issue_interval,
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
                harness_insight_window=harness_insight_window,
                harness_pattern_threshold=harness_pattern_threshold,
                max_runtime_log_chars=max_runtime_log_chars,
                max_ci_log_chars=max_ci_log_chars,
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
                epic_decompose_complexity_threshold=epic_decompose_complexity_threshold,
                epic_monitor_interval=epic_monitor_interval,
                epic_sweep_interval=epic_sweep_interval,
                workspace_gc_interval=workspace_gc_interval,
                epic_stale_days=epic_stale_days,
                epic_merge_strategy=epic_merge_strategy,
                collaborator_check_enabled=collaborator_check_enabled,
                collaborator_cache_ttl=collaborator_cache_ttl,
                artifact_retention_days=artifact_retention_days,
                artifact_max_size_mb=artifact_max_size_mb,
                runs_gc_interval=runs_gc_interval,
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
                adr_review_model=adr_review_model,
                adr_pre_review=adr_pre_review,
                health_monitor_interval=health_monitor_interval,
                max_discussion_comment_chars=max_discussion_comment_chars,
                max_common_feedback_chars=max_common_feedback_chars,
                max_impl_plan_chars=max_impl_plan_chars,
                max_review_feedback_chars=max_review_feedback_chars,
                max_planner_comment_chars=max_planner_comment_chars,
                max_planner_line_chars=max_planner_line_chars,
                max_planner_failed_plan_chars=max_planner_failed_plan_chars,
                max_hitl_correction_chars=max_hitl_correction_chars,
                max_hitl_cause_chars=max_hitl_cause_chars,
                max_ci_log_prompt_chars=max_ci_log_prompt_chars,
                max_unsticker_cause_chars=max_unsticker_cause_chars,
                max_verification_instructions_chars=max_verification_instructions_chars,
                hindsight_timeout=hindsight_timeout,
                security_patch_interval=security_patch_interval,
                security_patch_severity_threshold=security_patch_severity_threshold,
                code_grooming_interval=code_grooming_interval,
                code_grooming_enabled=code_grooming_enabled,
            )


class CredentialsFactory:
    """Factory for Credentials instances in tests."""

    @staticmethod
    def create(
        *,
        gh_token: str = "",
        hindsight_url: str = "",
        hindsight_api_key: str = "",
        sentry_auth_token: str = "",
        whatsapp_token: str = "",
        whatsapp_phone_id: str = "",
        whatsapp_recipient: str = "",
        whatsapp_verify_token: str = "",
    ) -> Credentials:
        """Create a Credentials with test-friendly defaults."""
        return Credentials(
            gh_token=gh_token,
            hindsight_url=hindsight_url,
            hindsight_api_key=hindsight_api_key,
            sentry_auth_token=sentry_auth_token,
            whatsapp_token=whatsapp_token,
            whatsapp_phone_id=whatsapp_phone_id,
            whatsapp_recipient=whatsapp_recipient,
            whatsapp_verify_token=whatsapp_verify_token,
        )


class PipelineHarness:
    """Utility for wiring all phases with shared real stores in tests."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        config=None,
        wiki_store: Any = None,
        wiki_compiler: Any = None,
        beads_manager: Any = None,
    ):
        from events import EventBus
        from hitl_phase import HITLPhase
        from implement_phase import ImplementPhase
        from issue_store import IssueStore
        from plan_phase import PlanPhase
        from post_merge_handler import PostMergeHandler
        from review_phase import ReviewPhase
        from state import StateTracker
        from triage_phase import TriagePhase

        self._beads_manager = beads_manager
        self.config = config or ConfigFactory.create(
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            max_workers=1,
            max_planners=1,
            max_reviewers=1,
            visual_validation_enabled=False,
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
        self.triage_runner.set_tracing_context = MagicMock()
        self.triage_runner.clear_tracing_context = MagicMock()
        self.planners = AsyncMock()
        self.planners.plan = AsyncMock()
        self.planners.set_tracing_context = MagicMock()
        self.planners.clear_tracing_context = MagicMock()
        self.agents = AsyncMock()
        self.agents.run = AsyncMock()
        self.agents.set_tracing_context = MagicMock()
        self.agents.clear_tracing_context = MagicMock()
        self.reviewers = AsyncMock()
        self.reviewers.review = AsyncMock()
        self.reviewers.fix_ci = AsyncMock()
        self.reviewers.set_tracing_context = MagicMock()
        self.reviewers.clear_tracing_context = MagicMock()
        self.hitl_runner = AsyncMock()
        self.hitl_runner.run = AsyncMock()
        self.hitl_runner.set_tracing_context = MagicMock()
        self.hitl_runner.clear_tracing_context = MagicMock()
        self._hitl_fetcher = AsyncMock()
        self._hitl_fetcher.fetch_issue_by_number = AsyncMock()

        self.workspaces = AsyncMock()
        self.workspaces.create = AsyncMock(side_effect=self._default_workspace_create)
        self.workspaces.destroy = AsyncMock()

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
            wiki_store=wiki_store,
            wiki_compiler=wiki_compiler,
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
            wiki_store=wiki_store,
            beads_manager=beads_manager,
        )
        self._implement_phase_base_kwargs: dict[str, Any] = {
            "config": self.config,
            "state": self.state,
            "workspaces": self.workspaces,
            "prs": self.prs,
            "store": self.store,
            "stop_event": self.stop_event,
            "beads_manager": beads_manager,
        }
        self.implement_phase = ImplementPhase(
            agents=self.agents,
            **self._implement_phase_base_kwargs,
        )
        self.review_phase = ReviewPhase(
            config=self.config,
            state=self.state,
            workspaces=self.workspaces,
            reviewers=self.reviewers,
            prs=self.prs,
            stop_event=self.stop_event,
            store=self.store,
            conflict_resolver=self._conflict_resolver,
            post_merge=self.post_merge,
            event_bus=self.bus,
        )
        self.hitl_phase = HITLPhase(
            config=self.config,
            state=self.state,
            store=self.store,
            fetcher=self._hitl_fetcher,
            workspaces=self.workspaces,
            hitl_runner=self.hitl_runner,
            prs=self.prs,
            event_bus=self.bus,
            stop_event=self.stop_event,
        )

    def set_agents(self, agents: Any) -> None:
        """Replace the agents runner and rebuild ImplementPhase to use it.

        ImplementPhase captures ``agents`` by reference in its constructor, so
        callers must not simply assign to ``self.agents`` — the rebuild is
        required to propagate the new runner into the phase. Base kwargs are
        preserved from ``__init__`` so future additions don't get silently dropped.
        """
        from implement_phase import ImplementPhase  # noqa: PLC0415

        self.agents = agents
        self.implement_phase = ImplementPhase(
            agents=agents,
            **self._implement_phase_base_kwargs,
        )

    def _ensure_test_dirs(self) -> None:
        paths = {
            self.config.repo_root,
            self.config.workspace_base,
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

        # `expected_pr_title` is the one synchronous method on PRPort; leaving
        # it as the default AsyncMock.__call__ returns an unawaited coroutine
        # from post_merge_handler.handle_approved, which surfaces as a
        # PytestUnraisableExceptionWarning once warnings-as-errors is enabled.
        from pr_manager import PRManager

        self.prs.expected_pr_title = MagicMock(side_effect=PRManager.expected_pr_title)
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
        self.prs.find_existing_issue = AsyncMock(return_value=0)
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

    def _default_workspace_create(self, issue_number: int, branch: str):
        path = self.config.workspace_path_for_issue(issue_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def seed_issue(self, task, stage: str = "find") -> None:
        """Place *task* in the requested queue stage."""
        self.store.enqueue_transition(task, stage)

    async def run_full_lifecycle(
        self,
        *,
        issue_number: int,
        seed_stage: str = "find",
        tags: list[str] | None = None,
        triage_result=None,
        plan_result=None,
        worker_result=None,
        review_verdict="approve",
    ) -> PipelineRunResult:
        """Drive an issue through triage -> plan -> implement -> review."""
        from models import ReviewVerdict
        from tests.conftest import (
            PlanResultFactory,
            ReviewResultFactory,
            TaskFactory,
            TriageResultFactory,
            WorkerResultFactory,
        )

        tag_list = tags or [self.config.find_label[0]]
        task = TaskFactory.create(id=issue_number, tags=tag_list)
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
        workspace_path = self.config.workspace_path_for_issue(task.id)
        worker_return = (
            worker_result
            if worker_result is not None
            else WorkerResultFactory.create(
                issue_number=task.id,
                branch=branch,
                workspace_path=str(workspace_path),
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


def make_docker_manager(tmp_path: Path) -> WorkspaceManager:
    """Create a WorkspaceManager with docker execution mode.

    Promoted from test_worktree._make_docker_manager() for reuse across test files.
    """
    from unittest.mock import patch

    from workspace import WorkspaceManager

    with patch("shutil.which", return_value="/usr/bin/docker"):
        cfg = ConfigFactory.create(
            execution_mode="docker",
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
    return WorkspaceManager(cfg)


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
    planners.set_tracing_context = MagicMock()
    planners.clear_tracing_context = MagicMock()
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
            prior_failure: str = "",
            bead_mapping: dict[str, str] | None = None,
            shared_prefix: str | None = None,
        ) -> WorkerResult:
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=success,
                workspace_path=str(wt_path),
            )

        agent_run = _default_agent_run

    mock_agents = AsyncMock()
    # Wrap agent_run to absorb extra kwargs (e.g. shared_prefix) that
    # the production code may pass but test mocks don't declare.
    _original_run = agent_run

    async def _kwargs_absorbing_run(*args: Any, **kwargs: Any) -> WorkerResult:
        import inspect  # noqa: PLC0415

        sig = inspect.signature(_original_run)
        # If the function accepts **kwargs, pass everything through
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if has_var_keyword:
            return await _original_run(*args, **kwargs)
        bound = sig.bind(
            *args, **{k: v for k, v in kwargs.items() if k in sig.parameters}
        )
        bound.apply_defaults()
        return await _original_run(*bound.args, **bound.kwargs)

    mock_agents.run = _kwargs_absorbing_run
    mock_agents.hindsight = None
    # set_tracing_context / clear_tracing_context are synchronous on the real
    # runner; override the auto-generated async mocks with plain MagicMocks so
    # callers don't get "coroutine was never awaited" warnings.
    from unittest.mock import MagicMock  # noqa: PLC0415

    mock_agents.set_tracing_context = MagicMock()
    mock_agents.clear_tracing_context = MagicMock()

    # Mock IssueStore — get_implementable returns the supplied issues once
    mock_store = AsyncMock(spec=IssueStore)
    mock_store.get_implementable = supply_once(*[[i] for i in issues])
    mock_store.mark_active = lambda num, stage: None
    mock_store.mark_complete = lambda num: None
    mock_store.is_active = lambda num: False
    mock_store.enrich_with_comments = AsyncMock(side_effect=lambda task: task)

    mock_wt = AsyncMock()
    mock_wt.create = AsyncMock(
        side_effect=lambda num, branch: config.workspace_base / f"issue-{num}"
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
        workspaces=mock_wt,
        agents=mock_agents,
        prs=mock_prs,
        store=mock_store,
        stop_event=stop_event,
    )

    return phase, mock_wt, mock_prs


class ImplementPhaseMockBuilder:
    """Fluent builder for ImplementPhase test mocks.

    Consolidates inline ``mock_prs.*`` and ``mock_wt.*`` overrides into
    chainable ``.with_*()`` calls, following the same pattern as
    ``ReviewMockBuilder`` in conftest.py.

    Usage::

        phase, mock_wt, mock_prs = (
            ImplementPhaseMockBuilder(config)
            .with_issues([issue])
            .with_push_return(False)
            .with_prs_method("find_open_pr_for_branch", AsyncMock(return_value=pr))
            .build()
        )
    """

    _UNSET: ClassVar[object] = object()  # sentinel for "not explicitly set"

    def __init__(self, config: object) -> None:
        self._config = config
        self._issues: list[object] = []
        self._push_return: bool = True
        self._create_pr_return: object = self._UNSET
        self._agent_run: object | None = None
        self._success: bool = True
        self._prs_overrides: dict[str, object] = {}
        self._wt_overrides: dict[str, object] = {}

    def with_issues(self, issues: list[object]) -> ImplementPhaseMockBuilder:
        """Set the issues to be returned by get_implementable."""
        self._issues = issues
        return self

    def with_push_return(self, val: bool) -> ImplementPhaseMockBuilder:
        """Set the return value for mock_prs.push_branch."""
        self._push_return = val
        return self

    def with_create_pr_return(self, val: object) -> ImplementPhaseMockBuilder:
        """Set the return value for mock_prs.create_pr.

        ``val`` must be a non-None object (e.g. ``PRInfoFactory.create()``).
        To make ``create_pr`` return ``None``, use
        ``with_prs_method("create_pr", AsyncMock(return_value=None))`` instead,
        because ``make_implement_phase`` treats ``None`` as "use the factory
        default" rather than as an explicit return value.
        """
        self._create_pr_return = val
        return self

    def with_agent_run(self, fn: object) -> ImplementPhaseMockBuilder:
        """Set a custom agent_run callable."""
        self._agent_run = fn
        return self

    def with_success(self, val: bool) -> ImplementPhaseMockBuilder:
        """Set the default agent success value.

        Only takes effect when no custom ``agent_run`` is provided via
        ``with_agent_run()``.  If a custom callable is set, ``success`` is
        silently ignored because the callable controls the result directly.
        """
        self._success = val
        return self

    def with_prs_method(self, name: str, mock: object) -> ImplementPhaseMockBuilder:
        """Override a specific mock_prs method/attribute after construction."""
        self._prs_overrides[name] = mock
        return self

    def with_wt_method(self, name: str, mock: object) -> ImplementPhaseMockBuilder:
        """Override a specific mock_wt method/attribute after construction."""
        self._wt_overrides[name] = mock
        return self

    def build(self) -> tuple[Any, Any, Any]:
        """Build and return ``(phase, mock_wt, mock_prs)``."""
        create_pr_kwarg: dict[str, Any] = (
            {}
            if self._create_pr_return is self._UNSET
            else {"create_pr_return": self._create_pr_return}
        )
        phase, mock_wt, mock_prs = make_implement_phase(
            self._config,
            self._issues,
            agent_run=self._agent_run,
            success=self._success,
            push_return=self._push_return,
            **create_pr_kwarg,
        )
        for name, mock in self._prs_overrides.items():
            setattr(mock_prs, name, mock)
        for name, mock in self._wt_overrides.items():
            setattr(mock_wt, name, mock)
        return phase, mock_wt, mock_prs


def make_hitl_phase(config):
    """Build a HITLPhase with mock dependencies.

    Promoted from test_hitl_phase._make_phase() for reuse across test files.

    Returns (phase, state, fetcher_mock, prs_mock, workspaces_mock,
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
    workspaces = AsyncMock()
    workspaces.create = AsyncMock(return_value=config.workspace_base / "issue-42")
    workspaces.destroy = AsyncMock()
    hitl_runner = AsyncMock()
    hitl_runner.set_tracing_context = MagicMock()
    hitl_runner.clear_tracing_context = MagicMock()
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
        workspaces,
        hitl_runner,
        prs,
        bus,
        stop_event,
    )
    return phase, state, fetcher_mock, prs, workspaces, hitl_runner, bus


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
    triage.set_tracing_context = MagicMock()
    triage.clear_tracing_context = MagicMock()
    prs = AsyncMock()
    prs.remove_label = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.find_existing_issue = AsyncMock(return_value=0)
    stop_event = asyncio.Event()
    phase = TriagePhase(config, state, store, triage, prs, bus, stop_event)
    return phase, state, triage, prs, store, stop_event


def make_conflict_resolver(config, *, agents=None, suggest_memory=None):
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
        workspaces=AsyncMock(),
        agents=agents,
        prs=AsyncMock(),
        event_bus=EventBus(),
        state=state,
        summarizer=None,
        suggest_memory=suggest_memory,
    )


def make_dashboard_router(
    config,
    event_bus,
    state,
    tmp_path,
    *,
    get_orch=None,
    registry=None,
    ui_dist_dir=None,
    template_dir=None,
    register_repo_cb=None,
    remove_repo_cb=None,
    list_repos_cb=None,
    repo_store=None,
    default_repo_slug=None,
    allowed_repo_roots_fn=None,
    credentials=None,
):
    """Create a dashboard router with test-friendly defaults.

    Returns ``(router, pr_mgr)`` so callers can mock individual
    ``PRManager`` methods after construction.

    Parameters
    ----------
    get_orch:
        Callable returning the orchestrator instance.  Defaults to
        ``lambda: None``.
    registry:
        Optional ``RepoRuntimeRegistry`` for multi-repo tests.
    ui_dist_dir / template_dir:
        Override the default ``tmp_path / "no-dist"`` / ``"no-templates"``.
    register_repo_cb / remove_repo_cb / list_repos_cb:
        Optional callbacks for repo management endpoints.
    repo_store:
        Optional ``RepoRegistryStore`` for config persistence tests.
    default_repo_slug:
        Optional default repo slug for multi-repo routing.
    allowed_repo_roots_fn:
        Optional callable returning allowed filesystem roots.
    credentials:
        Optional ``Credentials`` instance for route context.
    """
    from dashboard_routes import create_router
    from pr_manager import PRManager

    pr_mgr = PRManager(config, event_bus)
    router = create_router(
        config=config,
        event_bus=event_bus,
        state=state,
        pr_manager=pr_mgr,
        get_orchestrator=get_orch or (lambda: None),
        set_orchestrator=lambda o: None,
        set_run_task=lambda t: None,
        ui_dist_dir=ui_dist_dir or (tmp_path / "no-dist"),
        template_dir=template_dir or (tmp_path / "no-templates"),
        credentials=credentials,
        registry=registry,
        register_repo_cb=register_repo_cb,
        remove_repo_cb=remove_repo_cb,
        list_repos_cb=list_repos_cb,
        repo_store=repo_store,
        default_repo_slug=default_repo_slug,
        allowed_repo_roots_fn=allowed_repo_roots_fn,
    )
    return router, pr_mgr


def find_endpoint(router: Any, path: str, method: str | None = None) -> Any | None:
    """Locate an endpoint handler on *router* by path and optional HTTP method.

    When *method* is ``None``, returns the first route matching *path*.
    When *method* is given (e.g. ``"GET"``, ``"POST"``), also checks that
    the route's ``methods`` set contains the value.
    """
    for route in router.routes:
        if not (
            hasattr(route, "path") and route.path == path and hasattr(route, "endpoint")
        ):
            continue
        if method is None or (hasattr(route, "methods") and method in route.methods):
            return route.endpoint
    return None


def make_pr_manager_mock(**overrides: Any) -> AsyncMock:
    """Create an ``AsyncMock`` with common ``PRManager`` method stubs.

    Every method is an ``AsyncMock`` so callers can ``await`` them and
    assert calls.  Pass keyword overrides to replace individual attributes::

        prs = make_pr_manager_mock(get_pr_diff=AsyncMock(return_value="big diff"))
    """
    prs = AsyncMock()
    prs.remove_label = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.transition = AsyncMock()
    prs.get_pr_diff = AsyncMock(return_value="")
    prs.post_comment = AsyncMock()
    prs.post_pr_comment = AsyncMock()
    prs.push_branch = AsyncMock(return_value=True)
    prs.merge_pr = AsyncMock(return_value=True)
    prs.submit_review = AsyncMock(return_value=True)
    prs.create_task = AsyncMock(return_value=99)
    prs.close_task = AsyncMock()
    prs.find_existing_issue = AsyncMock(return_value=0)
    prs.add_pr_labels = AsyncMock()
    prs.remove_pr_label = AsyncMock()
    for k, v in overrides.items():
        setattr(prs, k, v)
    return prs


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
    * worktree directory ``issue-{issue_number}`` created under ``config.workspace_base``
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
    mock_reviewers.set_tracing_context = MagicMock()
    mock_reviewers.clear_tracing_context = MagicMock()
    mock_prs = AsyncMock()
    # expected_pr_title is a sync staticmethod on PRManager — use MagicMock
    # so callers don't get an unawaited coroutine when invoking it without await.
    mock_prs.expected_pr_title = MagicMock(return_value="Fixes #0: test")

    mock_store = MagicMock(spec=IssueStore)
    mock_store.mark_active = lambda _num, _stage: None
    mock_store.mark_complete = lambda _num: None
    mock_store.is_active = lambda _num: False

    bus = event_bus or EventBus()

    conflict_resolver = MergeConflictResolver(
        config=config,
        workspaces=mock_wt,
        agents=agents,
        prs=mock_prs,
        event_bus=bus,
        state=state,
        summarizer=None,
    )

    post_merge = PostMergeHandler(
        config=config,
        state=state,
        prs=mock_prs,
        event_bus=bus,
        ac_generator=ac_generator,
        retrospective=None,
        verification_judge=None,
        epic_checker=None,
        store=mock_store,
    )

    phase = ReviewPhase(
        config=config,
        state=state,
        workspaces=mock_wt,
        reviewers=mock_reviewers,
        prs=mock_prs,
        stop_event=stop_event,
        store=mock_store,
        conflict_resolver=conflict_resolver,
        post_merge=post_merge,
        event_bus=bus,
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

        wt = config.workspace_base / f"issue-{issue_number}"
        wt.mkdir(parents=True, exist_ok=True)

    return phase


def make_tracker(tmp_path: Path, *, filename: str = "state.json") -> StateTracker:
    """Return a StateTracker backed by a temp file."""
    from state import StateTracker

    return StateTracker(tmp_path / filename)


# --- Orchestrator test helpers (consolidated from test_orchestrator_*.py) ---


def mock_fetcher_noop(orch: Any) -> None:
    """Mock store and fetcher methods so no real gh CLI calls are made.

    Required for tests that go through ``run()`` since exception isolation
    catches errors from unmocked fetcher/store calls instead of propagating them.
    """
    orch._svc.store.get_triageable = lambda _max_count: []  # type: ignore[method-assign]
    orch._svc.store.get_plannable = lambda _max_count: []  # type: ignore[method-assign]
    orch._svc.store.get_reviewable = lambda _max_count: []  # type: ignore[method-assign]
    orch._svc.store.start = AsyncMock()  # type: ignore[method-assign]
    orch._svc.store.get_active_issues = lambda: {}  # type: ignore[method-assign]
    orch._svc.fetcher.fetch_issue_by_number = AsyncMock(return_value=None)  # type: ignore[method-assign]
    orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
    orch._svc.workspaces.enable_rerere = AsyncMock()  # type: ignore[method-assign]
    orch._svc.workspaces.sanitize_repo = AsyncMock()  # type: ignore[method-assign]

    # Mock the 7 background loops added in #6258 so they don't make real
    # gh/Claude CLI calls that raise AuthenticationError and set stop_event.
    async def _wait_for_stop() -> None:
        await orch._stop_event.wait()

    # All background loops that may call gh/Claude and now propagate auth/
    # credit errors instead of swallowing them — stub each to just wait for
    # the stop event so tests can drive the orchestrator without real I/O.
    for loop_attr in (
        "adr_reviewer_loop",
        "ci_monitor_loop",
        "code_grooming_loop",
        "dependabot_merge_loop",
        "diagnostic_loop",
        "epic_monitor_loop",
        "epic_sweeper_loop",
        "github_cache_loop",
        "health_monitor_loop",
        "pr_unsticker_loop",
        "repo_wiki_loop",
        "report_issue_loop",
        "retrospective_loop",
        "runs_gc_loop",
        "security_patch_loop",
        "sentry_loop",
        "stale_issue_gc_loop",
        "stale_issue_loop",
        "workspace_gc_loop",
    ):
        loop_obj = getattr(orch._svc, loop_attr, None)
        if loop_obj is not None:
            loop_obj.run = _wait_for_stop  # type: ignore[method-assign]


def make_worker_result(
    issue_number: int = 42,
    branch: str = "agent/issue-42",
    success: bool = True,
    workspace_path: str = "/tmp/worktrees/issue-42",
    transcript: str = "Implemented the feature.",
) -> Any:
    """Thin wrapper around ``WorkerResultFactory.create`` with common defaults."""
    from tests.conftest import WorkerResultFactory

    return WorkerResultFactory.create(
        issue_number=issue_number,
        branch=branch,
        success=success,
        transcript=transcript,
        commits=1,
        workspace_path=workspace_path,
        use_defaults=True,
    )


def make_review_result(
    pr_number: int = 101,
    issue_number: int = 42,
    verdict: Any = None,
    transcript: str = "",
) -> Any:
    """Create a minimal ReviewResult for orchestrator tests."""
    from models import ReviewVerdict
    from tests.conftest import ReviewResultFactory

    return ReviewResultFactory.create(
        pr_number=pr_number,
        issue_number=issue_number,
        verdict=verdict if verdict is not None else ReviewVerdict.APPROVE,
        summary="Looks good.",
        fixes_made=False,
        transcript=transcript,
    )


def make_pr_manager(config: Any, event_bus: Any) -> Any:
    """Create a real ``PRManager`` instance — consolidates ``_make_manager``."""
    from pr_manager import PRManager

    return PRManager(config=config, event_bus=event_bus)


# ---------------------------------------------------------------------------
# Route-back counter stub (#6423)
# ---------------------------------------------------------------------------


class InMemoryRouteBackCounter:
    """In-memory ``RouteBackCounterPort`` implementation for tests.

    Mirrors ``state._route_back.RouteBackStateMixin`` semantics: get
    starts at 0, increment returns the new value, decrement-to-zero
    clears the entry, decrement-below-zero is a no-op. Used by
    ``tests/test_route_back.py`` and ``tests/test_precondition_gate.py``
    so the counter shape stays consistent across both files instead
    of drifting between two parallel stubs.
    """

    def __init__(self) -> None:
        self._counts: dict[int, int] = {}

    def get_route_back_count(self, issue_id: int) -> int:
        return self._counts.get(issue_id, 0)

    def increment_route_back_count(self, issue_id: int) -> int:
        new = self._counts.get(issue_id, 0) + 1
        self._counts[issue_id] = new
        return new

    def decrement_route_back_count(self, issue_id: int) -> int:
        current = self._counts.get(issue_id, 0)
        if current <= 0:
            return 0
        new = current - 1
        if new == 0:
            self._counts.pop(issue_id, None)
        else:
            self._counts[issue_id] = new
        return new
