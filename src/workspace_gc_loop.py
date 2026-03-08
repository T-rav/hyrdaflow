"""Background worker loop — garbage-collect stale worktrees and branches."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from typing import Any

from base_background_loop import BaseBackgroundLoop
from config import HydraFlowConfig
from events import EventBus
from models import StatusCallback
from pr_manager import PRManager
from state import StateTracker
from subprocess_util import run_subprocess
from workspace import WorkspaceManager

logger = logging.getLogger("hydraflow.workspace_gc_loop")

# Maximum worktrees to GC per cycle to avoid long-running passes.
_MAX_GC_PER_CYCLE = 20


class WorkspaceGCLoop(BaseBackgroundLoop):
    """Periodically garbage-collects stale worktrees and orphaned branches.

    Catches worktrees that leak when PRs are merged manually, via HITL,
    or when implementations fail/crash.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        worktrees: WorkspaceManager,
        prs: PRManager,
        state: StateTracker,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: StatusCallback,
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
        is_in_pipeline_cb: Callable[[int], bool] | None = None,
    ) -> None:
        super().__init__(
            worker_name="worktree_gc",
            config=config,
            bus=event_bus,
            stop_event=stop_event,
            status_cb=status_cb,
            enabled_cb=enabled_cb,
            sleep_fn=sleep_fn,
            interval_cb=interval_cb,
        )
        self._worktrees = worktrees
        self._prs = prs
        self._state = state
        self._is_in_pipeline = is_in_pipeline_cb

    def _get_default_interval(self) -> int:
        return self._config.worktree_gc_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Run one GC cycle: state workspaces, orphan dirs, orphan branches."""
        collected = 0
        skipped = 0
        errors = 0

        # Phase 1: GC workspaces tracked in state
        active_worktrees = self._state.get_active_worktrees()
        for issue_number in list(active_worktrees.keys()):
            if self._stop_event.is_set() or collected >= _MAX_GC_PER_CYCLE:
                break
            try:
                if await self._is_safe_to_gc(issue_number):
                    # Remove from state first so a crash between steps
                    # leaves the entry gone (destroy is idempotent).
                    self._state.remove_worktree(issue_number)
                    await self._worktrees.destroy(issue_number)
                    collected += 1
                    logger.info("GC: collected workspace for issue #%d", issue_number)
                else:
                    skipped += 1
            except Exception:
                logger.warning(
                    "GC: failed to collect workspace for issue #%d",
                    issue_number,
                    exc_info=True,
                )
                errors += 1

        # Phase 2: scan filesystem for orphaned issue-* dirs not in state
        if not self._stop_event.is_set():
            orphan_count = await self._collect_orphaned_dirs(
                active_worktrees, _MAX_GC_PER_CYCLE - collected
            )
            collected += orphan_count

        # Phase 3: delete orphaned agent/issue-* local branches
        if not self._stop_event.is_set():
            branch_count = await self._collect_orphaned_branches(
                _MAX_GC_PER_CYCLE - collected
            )
            collected += branch_count

        return {"collected": collected, "skipped": skipped, "errors": errors}

    async def _is_safe_to_gc(self, issue_number: int) -> bool:
        """Determine whether a worktree for *issue_number* can be safely GC'd.

        Returns False (skip) on any uncertainty.
        """
        safe_to_gc = False

        # Skip if active, HITL, or anywhere in the IssueStore pipeline
        # (queued, in-flight, or being processed).
        in_pipeline = self._is_in_pipeline and self._is_in_pipeline(issue_number)
        if (
            issue_number in self._state.get_active_issue_numbers()
            or self._state.get_hitl_cause(issue_number) is not None
            or in_pipeline
        ):
            logger.debug("GC: #%d is active/HITL/pipeline — skipping", issue_number)
            return safe_to_gc

        # Check issue state via GitHub API
        try:
            issue_state = await self._get_issue_state(issue_number)
        except Exception:
            logger.debug(
                "GC: could not fetch issue #%d state — skipping",
                issue_number,
                exc_info=True,
            )
            return safe_to_gc

        if issue_state == "closed":
            safe_to_gc = True
        elif issue_state == "open":
            # Guard against startup/refresh races where IssueStore has not yet
            # observed pipeline membership. If GitHub labels indicate pipeline
            # ownership, do not GC.
            if await self._issue_has_pipeline_label(issue_number):
                logger.debug(
                    "GC: #%d still has pipeline labels on GitHub — skipping",
                    issue_number,
                )
            else:
                try:
                    safe_to_gc = not await self._has_open_pr(issue_number)
                except Exception:
                    logger.debug(
                        "GC: could not check PR for issue #%d — skipping",
                        issue_number,
                        exc_info=True,
                    )

        return safe_to_gc

    async def _issue_has_pipeline_label(self, issue_number: int) -> bool:
        """Return True when the issue currently carries any pipeline label."""
        pipeline_labels = {
            *(lbl.lower() for lbl in self._config.find_label),
            *(lbl.lower() for lbl in self._config.planner_label),
            *(lbl.lower() for lbl in self._config.ready_label),
            *(lbl.lower() for lbl in self._config.review_label),
            *(lbl.lower() for lbl in self._config.hitl_label),
            *(lbl.lower() for lbl in self._config.hitl_active_label),
        }
        if not pipeline_labels:
            return False
        try:
            output = await run_subprocess(
                "gh",
                "api",
                f"repos/{self._config.repo}/issues/{issue_number}",
                "--jq",
                ".labels[].name",
                cwd=self._config.repo_root,
                gh_token=self._config.gh_token,
            )
        except Exception:
            logger.debug(
                "GC: could not fetch labels for issue #%d — skipping GC",
                issue_number,
                exc_info=True,
            )
            return True
        labels = {line.strip().lower() for line in output.splitlines() if line.strip()}
        return bool(labels & pipeline_labels)

    async def _get_issue_state(self, issue_number: int) -> str:
        """Query GitHub for the issue state ('open' or 'closed')."""
        output = await run_subprocess(
            "gh",
            "api",
            f"repos/{self._config.repo}/issues/{issue_number}",
            "--jq",
            ".state",
            cwd=self._config.repo_root,
            gh_token=self._config.gh_token,
        )
        return output.strip()

    async def _has_open_pr(self, issue_number: int) -> bool:
        """Check whether an open PR exists for the issue's branch."""
        branch = self._config.branch_for_issue(issue_number)
        try:
            output = await run_subprocess(
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number",
                "--jq",
                "length",
                cwd=self._config.repo_root,
                gh_token=self._config.gh_token,
            )
            return int(output.strip() or "0") > 0
        except (RuntimeError, ValueError):
            logger.debug(
                "GC: PR check failed for issue #%d",
                issue_number,
                exc_info=True,
            )
            return True  # Assume PR exists on error — don't GC

    async def _collect_orphaned_dirs(self, tracked: dict[int, str], budget: int) -> int:
        """Scan filesystem for orphaned issue-* dirs not tracked in state."""
        collected = 0
        repo_wt_base = self._config.worktree_base / self._config.repo_slug
        if not repo_wt_base.exists():
            return 0

        tracked_issues = set(tracked.keys())
        for child in sorted(repo_wt_base.iterdir()):
            if collected >= budget or self._stop_event.is_set():
                break
            if not child.is_dir() or not child.name.startswith("issue-"):
                continue
            try:
                issue_num = int(child.name.split("-", 1)[1])
            except (ValueError, IndexError):
                continue
            if issue_num in tracked_issues:
                continue
            try:
                if await self._is_safe_to_gc(issue_num):
                    await self._worktrees.destroy(issue_num)
                    collected += 1
                    logger.info(
                        "GC: collected orphaned worktree dir for issue #%d", issue_num
                    )
            except Exception:
                logger.warning(
                    "GC: failed to collect orphaned dir for issue #%d",
                    issue_num,
                    exc_info=True,
                )
        return collected

    _AGENT_BRANCH_RE = re.compile(r"^agent/issue-(\d+)$")

    async def _collect_orphaned_branches(self, budget: int = _MAX_GC_PER_CYCLE) -> int:
        """Delete local ``agent/issue-*`` branches with no corresponding worktree."""
        collected = 0
        try:
            output = await run_subprocess(
                "git",
                "branch",
                "--list",
                "agent/issue-*",
                cwd=self._config.repo_root,
                gh_token=self._config.gh_token,
            )
        except RuntimeError:
            logger.warning("GC: could not list local branches", exc_info=True)
            return 0

        active_worktrees = self._state.get_active_worktrees()
        active_issues = set(self._state.get_active_issue_numbers())

        for line in output.strip().splitlines():
            if collected >= budget:
                break
            branch = line.strip().removeprefix("* ")
            match = self._AGENT_BRANCH_RE.match(branch)
            if not match:
                continue
            issue_num = int(match.group(1))
            # Skip if worktree exists, issue is active, or in pipeline
            if issue_num in active_worktrees or issue_num in active_issues:
                continue
            if self._is_in_pipeline and self._is_in_pipeline(issue_num):
                continue
            if await self._issue_has_pipeline_label(issue_num):
                continue
            try:
                await run_subprocess(
                    "git",
                    "branch",
                    "-D",
                    branch,
                    cwd=self._config.repo_root,
                    gh_token=self._config.gh_token,
                )
                collected += 1
                logger.info("GC: deleted orphaned branch %s", branch)
            except RuntimeError:
                logger.debug("GC: could not delete branch %s", branch, exc_info=True)
        return collected
