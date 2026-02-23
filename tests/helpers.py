"""Shared test helpers for HydraFlow tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from worktree import WorktreeManager


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


def make_streaming_proc(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> AsyncMock:
    """Build a mock for asyncio.create_subprocess_exec with streaming stdout."""
    mock_proc = AsyncMock()
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
        max_budget_usd: float = 1.0,
        model: str = "sonnet",
        review_model: str = "sonnet",
        review_budget_usd: float = 1.0,
        ci_check_timeout: int = 600,
        ci_poll_interval: int = 30,
        max_ci_fix_attempts: int = 0,
        max_quality_fix_attempts: int = 2,
        max_review_fix_attempts: int = 2,
        min_review_findings: int = 3,
        max_merge_conflict_fix_attempts: int = 3,
        max_issue_attempts: int = 3,
        review_label: list[str] | None = None,
        hitl_label: list[str] | None = None,
        fixed_label: list[str] | None = None,
        improve_label: list[str] | None = None,
        memory_label: list[str] | None = None,
        dup_label: list[str] | None = None,
        epic_label: list[str] | None = None,
        find_label: list[str] | None = None,
        planner_label: list[str] | None = None,
        planner_model: str = "opus",
        triage_model: str = "haiku",
        planner_budget_usd: float = 1.0,
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
        poll_interval: int = 5,
        data_poll_interval: int = 60,
        gh_max_retries: int = 3,
        ac_model: str = "sonnet",
        ac_budget_usd: float = 0,
        test_command: str = "make test",
        max_issue_body_chars: int = 10_000,
        max_review_diff_chars: int = 15_000,
        repo_root: Path | None = None,
        worktree_base: Path | None = None,
        state_file: Path | None = None,
        event_log_path: Path | None = None,
        config_file: Path | None = None,
        memory_compaction_model: str = "haiku",
        max_memory_chars: int = 4000,
        max_memory_prompt_chars: int = 4000,
        memory_sync_interval: int = 120,
        metrics_sync_interval: int = 7200,
        manifest_refresh_interval: int = 3600,
        max_manifest_prompt_chars: int = 2000,
        credit_pause_buffer_minutes: int = 1,
        transcript_summarization_enabled: bool = True,
        transcript_summary_model: str = "haiku",
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
        docker_enabled: bool = False,
        docker_network: str = "",
        docker_extra_mounts: list[str] | None = None,
        memory_auto_approve: bool = False,
        transcript_summary_as_issue: bool = False,
    ):
        """Create a HydraFlowConfig with test-friendly defaults."""
        from config import HydraFlowConfig

        root = repo_root or Path("/tmp/hydraflow-test-repo")
        return HydraFlowConfig(
            config_file=config_file,
            ready_label=ready_label if ready_label is not None else ["test-label"],
            batch_size=batch_size,
            max_workers=max_workers,
            max_planners=max_planners,
            max_reviewers=max_reviewers,
            max_budget_usd=max_budget_usd,
            model=model,
            review_model=review_model,
            review_budget_usd=review_budget_usd,
            ci_check_timeout=ci_check_timeout,
            ci_poll_interval=ci_poll_interval,
            max_ci_fix_attempts=max_ci_fix_attempts,
            max_quality_fix_attempts=max_quality_fix_attempts,
            max_review_fix_attempts=max_review_fix_attempts,
            min_review_findings=min_review_findings,
            max_merge_conflict_fix_attempts=max_merge_conflict_fix_attempts,
            max_issue_attempts=max_issue_attempts,
            review_label=review_label
            if review_label is not None
            else ["hydraflow-review"],
            hitl_label=hitl_label if hitl_label is not None else ["hydraflow-hitl"],
            fixed_label=fixed_label if fixed_label is not None else ["hydraflow-fixed"],
            improve_label=improve_label
            if improve_label is not None
            else ["hydraflow-improve"],
            memory_label=memory_label
            if memory_label is not None
            else ["hydraflow-memory"],
            dup_label=dup_label if dup_label is not None else ["hydraflow-dup"],
            epic_label=epic_label if epic_label is not None else ["hydraflow-epic"],
            find_label=find_label if find_label is not None else ["hydraflow-find"],
            planner_label=planner_label
            if planner_label is not None
            else ["hydraflow-plan"],
            planner_model=planner_model,
            triage_model=triage_model,
            planner_budget_usd=planner_budget_usd,
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
            ac_budget_usd=ac_budget_usd,
            review_insight_window=review_insight_window,
            review_pattern_threshold=review_pattern_threshold,
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
            max_memory_chars=max_memory_chars,
            max_memory_prompt_chars=max_memory_prompt_chars,
            memory_sync_interval=memory_sync_interval,
            metrics_sync_interval=metrics_sync_interval,
            manifest_refresh_interval=manifest_refresh_interval,
            max_manifest_prompt_chars=max_manifest_prompt_chars,
            credit_pause_buffer_minutes=credit_pause_buffer_minutes,
            transcript_summarization_enabled=transcript_summarization_enabled,
            transcript_summary_model=transcript_summary_model,
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
            docker_enabled=docker_enabled,
            docker_network=docker_network,
            docker_extra_mounts=docker_extra_mounts
            if docker_extra_mounts is not None
            else [],
            memory_auto_approve=memory_auto_approve,
            transcript_summary_as_issue=transcript_summary_as_issue,
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


def make_review_phase(
    config,
    *,
    agents=None,
    event_bus=None,
    ac_generator=None,
):
    """Build a ReviewPhase with standard mock dependencies.

    Promoted from test_review_phase._make_phase() for reuse across test files.
    """
    from events import EventBus
    from issue_store import IssueStore
    from review_phase import ReviewPhase
    from state import StateTracker

    state = StateTracker(config.state_file)
    stop_event = asyncio.Event()

    mock_wt = AsyncMock()
    mock_wt.destroy = AsyncMock()

    mock_reviewers = AsyncMock()
    mock_prs = AsyncMock()

    mock_store = AsyncMock(spec=IssueStore)
    mock_store.mark_active = lambda _num, _stage: None
    mock_store.mark_complete = lambda _num: None
    mock_store.is_active = lambda _num: False

    return ReviewPhase(
        config=config,
        state=state,
        worktrees=mock_wt,
        reviewers=mock_reviewers,
        prs=mock_prs,
        stop_event=stop_event,
        store=mock_store,
        agents=agents,
        event_bus=event_bus or EventBus(),
        ac_generator=ac_generator,
    )
