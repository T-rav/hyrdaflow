"""Goal-driven PR unsticker — resolves ALL HITL causes autonomously."""

from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from memory import file_memory_suggestion
from models import ConflictResolutionResult

if TYPE_CHECKING:
    from agent import AgentRunner
    from config import HydraFlowConfig
    from events import EventBus
    from hitl_runner import HITLRunner
    from issue_fetcher import IssueFetcher
    from models import GitHubIssue, HITLItem, UnstickResult
    from pr_manager import PRManager
    from state import StateTracker
    from worktree import WorktreeManager

logger = logging.getLogger("hydraflow.pr_unsticker")

# Keywords that indicate a merge conflict cause
_MERGE_CONFLICT_KEYWORDS = ("merge conflict", "conflict")

# Keywords for CI / quality failures
_CI_FAILURE_KEYWORDS = (
    "ci fail",
    "ci_fail",
    "check fail",
    "test fail",
    "lint fail",
    "type",
)

# Keywords for review fix cap exceeded
_REVIEW_CAP_KEYWORDS = ("review fix", "fix attempt", "fix cap", "review cap")


class FailureCause(StrEnum):
    """Classification of HITL escalation causes."""

    MERGE_CONFLICT = "merge_conflict"
    CI_FAILURE = "ci_failure"
    REVIEW_FIX_CAP = "review_fix_cap"
    GENERIC = "generic"


# Priority order: lower index = processed first
_CAUSE_PRIORITY = {
    FailureCause.MERGE_CONFLICT: 0,
    FailureCause.CI_FAILURE: 1,
    FailureCause.REVIEW_FIX_CAP: 2,
    FailureCause.GENERIC: 3,
}


def _classify_cause(cause: str) -> FailureCause:
    """Classify a free-text HITL cause into a FailureCause enum value."""
    lower = cause.lower()
    if any(kw in lower for kw in _MERGE_CONFLICT_KEYWORDS):
        return FailureCause.MERGE_CONFLICT
    if any(kw in lower for kw in _CI_FAILURE_KEYWORDS):
        return FailureCause.CI_FAILURE
    if any(kw in lower for kw in _REVIEW_CAP_KEYWORDS):
        return FailureCause.REVIEW_FIX_CAP
    return FailureCause.GENERIC


class PRUnsticker:
    """Goal-driven system that resolves ALL HITL causes autonomously.

    Processing flow:
    1. Fetch and classify HITL items by cause
    2. Fix in parallel (semaphore-limited)
    3. Merge sequentially (one at a time)
    4. Re-rebase remaining items after each merge
    5. Repeat until done or all remaining are stuck
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        event_bus: EventBus,
        pr_manager: PRManager,
        agents: AgentRunner,
        worktrees: WorktreeManager,
        fetcher: IssueFetcher,
        hitl_runner: HITLRunner | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._bus = event_bus
        self._prs = pr_manager
        self._agents = agents
        self._worktrees = worktrees
        self._fetcher = fetcher
        self._hitl_runner = hitl_runner
        self._stop_event = stop_event or asyncio.Event()

    async def unstick(self, hitl_items: list[HITLItem]) -> UnstickResult:
        """Process HITL items and return stats.

        Returns a dict with keys: ``processed``, ``resolved``, ``failed``,
        ``skipped``, ``merged``.
        """
        from events import EventType, HydraFlowEvent

        stats: UnstickResult = {
            "processed": 0,
            "resolved": 0,
            "failed": 0,
            "skipped": 0,
            "merged": 0,
        }

        if not hitl_items:
            return stats

        # Filter by cause mode
        if self._config.unstick_all_causes:
            candidates = list(hitl_items)
        else:
            candidates = [
                item
                for item in hitl_items
                if self._is_merge_conflict(self._state.get_hitl_cause(item.issue) or "")
            ]

        # Sort by cause priority (merge conflicts first)
        candidates.sort(
            key=lambda item: _CAUSE_PRIORITY.get(
                _classify_cause(self._state.get_hitl_cause(item.issue) or ""),
                99,
            )
        )

        # Apply batch size limit
        batch_size = self._config.pr_unstick_batch_size
        batch = candidates[:batch_size]
        stats["skipped"] = len(hitl_items) - len(batch)

        # --- PARALLEL FIX PHASE ---
        semaphore = asyncio.Semaphore(batch_size)
        fixed: list[HITLItem] = []
        stuck: list[HITLItem] = []

        async def _fix_one(item: HITLItem) -> tuple[HITLItem, bool]:
            async with semaphore:
                if self._stop_event.is_set():
                    return item, False
                return item, await self._process_item(item)

        tasks = [asyncio.create_task(_fix_one(item)) for item in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            stats["processed"] += 1
            if isinstance(result, BaseException):
                stats["failed"] += 1
                continue
            item, success = result
            if success:
                fixed.append(item)
                stats["resolved"] += 1
            else:
                stuck.append(item)
                stats["failed"] += 1

            action = "unstick_resolved" if success else "unstick_failed"
            issue_num = item.issue if not isinstance(result, BaseException) else 0
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.HITL_UPDATE,
                    data={
                        "issue": issue_num,
                        "action": action,
                        "source": "pr_unsticker",
                    },
                )
            )

        # --- SEQUENTIAL MERGE PHASE ---
        if self._config.unstick_auto_merge and fixed:
            merged_count = await self._merge_phase(fixed)
            stats["merged"] = merged_count

        return stats

    async def _merge_phase(self, fixed_items: list[HITLItem]) -> int:
        """Merge fixed items one at a time, re-rebasing remaining after each."""
        merged = 0
        remaining = list(fixed_items)

        while remaining:
            if self._stop_event.is_set():
                break

            item = remaining.pop(0)
            success = await self._wait_and_merge(item)

            if success:
                merged += 1
                # Pull main and re-rebase remaining items
                if remaining:
                    await self._prs.pull_main()
                    await self._re_rebase_remaining(remaining)
            # If merge failed, item already released back to HITL

        return merged

    async def _process_item(self, item: HITLItem) -> bool:
        """Attempt to resolve issues for a single HITL item.

        Returns *True* if the fix was successful and branch was pushed.
        """
        issue_number = item.issue
        branch = self._config.branch_for_issue(issue_number)
        cause_str = self._state.get_hitl_cause(issue_number) or ""
        cause = _classify_cause(cause_str)

        # Claim: swap labels
        await self._prs.swap_pipeline_labels(
            issue_number, self._config.hitl_active_label[0]
        )

        cause_desc = cause.value.replace("_", " ")
        await self._prs.post_comment(
            issue_number,
            f"**PR Unsticker** attempting to resolve {cause_desc}...\n\n"
            "---\n*Automated by HydraFlow PR Unsticker*",
        )

        try:
            # Fetch full issue for prompt context
            issue = await self._fetcher.fetch_issue_by_number(issue_number)
            if not issue:
                logger.warning("Could not fetch issue #%d for unsticker", issue_number)
                await self._release_back_to_hitl(issue_number, "Could not fetch issue")
                return False

            # Get or create worktree
            wt_path = self._config.worktree_path_for_issue(issue_number)
            if not wt_path.is_dir():
                wt_path = await self._worktrees.create(issue_number, branch)
            self._state.set_worktree(issue_number, str(wt_path))

            # Dispatch to cause-specific resolver
            resolution = await self._resolve_by_cause(
                cause,
                issue_number,
                issue,
                wt_path,
                branch,
                item.prUrl,
                pr_number=item.pr,
            )

            if resolution.success:
                # Push the fixed branch
                if resolution.used_rebuild:
                    new_wt = self._config.worktree_path_for_issue(issue_number)
                    await self._prs.force_push_branch(new_wt, branch)
                else:
                    await self._prs.push_branch(wt_path, branch)

                if not self._config.unstick_auto_merge:
                    # Restore origin label when not auto-merging
                    origin = self._state.get_hitl_origin(issue_number)
                    if origin:
                        await self._prs.swap_pipeline_labels(issue_number, origin)
                    else:
                        for lbl in self._config.hitl_active_label:
                            await self._prs.remove_label(issue_number, lbl)

                    self._state.remove_hitl_origin(issue_number)
                    self._state.remove_hitl_cause(issue_number)
                    self._state.reset_issue_attempts(issue_number)

                    await self._prs.post_comment(
                        issue_number,
                        f"**PR Unsticker** resolved {cause_desc} successfully.\n\n"
                        f"Returning issue to `{origin or 'pipeline'}` stage."
                        "\n\n---\n*Automated by HydraFlow PR Unsticker*",
                    )
                # When auto-merge is on, state cleanup happens after merge

                logger.info(
                    "PR Unsticker resolved %s for issue #%d",
                    cause_desc,
                    issue_number,
                )
                return True
            else:
                await self._release_back_to_hitl(
                    issue_number, f"All {cause_desc} resolution attempts exhausted"
                )
                return False

        except Exception:
            logger.exception("PR Unsticker failed for issue #%d", issue_number)
            await self._release_back_to_hitl(
                issue_number, "Unexpected error during resolution"
            )
            return False

    async def _resolve_by_cause(
        self,
        cause: FailureCause,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
        pr_url: str,
        pr_number: int = 0,
    ) -> ConflictResolutionResult:
        """Dispatch to the appropriate resolver based on cause classification.

        Returns a :class:`ConflictResolutionResult` — *used_rebuild* is True
        when the fresh-branch rebuild path was taken (caller should force-push).
        """
        if cause == FailureCause.MERGE_CONFLICT:
            return await self._resolve_conflicts(
                issue_number,
                issue,
                wt_path,
                branch,
                pr_url=pr_url,
                pr_number=pr_number,
            )
        if cause in (FailureCause.CI_FAILURE, FailureCause.REVIEW_FIX_CAP):
            success = await self._resolve_ci_or_quality(
                issue_number, issue, wt_path, branch, pr_url=pr_url
            )
            return ConflictResolutionResult(success=success, used_rebuild=False)
        success = await self._resolve_generic(issue_number, issue, wt_path, branch)
        return ConflictResolutionResult(success=success, used_rebuild=False)

    async def _resolve_ci_or_quality(
        self,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
        pr_url: str,
    ) -> bool:
        """Rebase on main and run agent with a CI/quality fix prompt."""
        # First rebase on main
        clean = await self._worktrees.start_merge_main(wt_path, branch)
        if not clean:
            # If there are conflicts during rebase, try to resolve them first
            await self._worktrees.abort_merge(wt_path)

        cause_str = self._state.get_hitl_cause(issue_number) or ""
        prompt = self._build_ci_fix_prompt(issue, pr_url, cause_str)

        try:
            cmd = self._agents._build_command(wt_path)
            transcript = await self._agents._execute(
                cmd,
                prompt,
                wt_path,
                {"issue": issue_number, "source": "pr_unsticker"},
            )
            self._save_transcript(issue_number, 1, transcript)

            try:
                await file_memory_suggestion(
                    transcript,
                    "pr_unsticker",
                    f"issue #{issue_number}",
                    self._config,
                    self._prs,
                    self._state,
                )
            except Exception:
                logger.exception(
                    "Failed to file memory suggestion for unsticker on issue #%d",
                    issue_number,
                )

            success, error_msg = await self._agents._verify_result(wt_path, branch)
            if success:
                return True

            logger.warning(
                "CI/quality fix failed for issue #%d: %s",
                issue_number,
                error_msg[:200] if error_msg else "",
            )
            return False
        except Exception as exc:
            logger.error(
                "Unsticker CI fix agent failed for issue #%d: %s",
                issue_number,
                exc,
            )
            return False

    async def _resolve_generic(
        self,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
    ) -> bool:
        """Use HITLRunner for generic/unknown causes."""
        if not self._hitl_runner:
            logger.warning(
                "No HITL runner available for generic fix on issue #%d",
                issue_number,
            )
            return False

        cause_str = self._state.get_hitl_cause(issue_number) or ""
        correction = f"Automated fix attempt by PR Unsticker. Cause: {cause_str}"

        result = await self._hitl_runner.run(
            issue=issue,
            correction=correction,
            cause=cause_str,
            worktree_path=wt_path,
        )
        return result.success

    def _build_ci_fix_prompt(self, issue: GitHubIssue, pr_url: str, cause: str) -> str:
        """Build a targeted prompt for CI/quality fix."""
        return f"""You are fixing CI/quality failures for a pull request.

## Issue: {issue.title}
Issue URL: {issue.url}
PR URL: {pr_url}

## Escalation Reason

{cause}

## Instructions

1. Run `make quality` to see current failures.
2. Read the error output carefully and fix the root causes.
3. Do NOT skip, disable, or weaken any tests or checks.
4. Run `make quality` again to verify your fixes pass.
5. Commit fixes with a descriptive message.

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- Write tests for all new code — tests are mandatory.
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Ensure `make quality` passes before committing.
"""

    async def _wait_and_merge(self, item: HITLItem) -> bool:
        """Wait for CI to pass, then squash-merge the PR.

        Returns *True* if the merge succeeded.
        """
        issue_number = item.issue
        pr_number = item.pr

        if not pr_number:
            logger.warning("No PR number for issue #%d — skipping merge", issue_number)
            # Still clean up state
            self._finalize_resolved(issue_number)
            return False

        # Wait for CI
        passed, summary = await self._prs.wait_for_ci(
            pr_number,
            self._config.ci_check_timeout,
            self._config.ci_poll_interval,
            self._stop_event,
        )

        if not passed:
            logger.warning(
                "CI failed for PR #%d (issue #%d): %s",
                pr_number,
                issue_number,
                summary,
            )
            await self._release_back_to_hitl(
                issue_number, f"CI failed after fix: {summary}"
            )
            return False

        # Squash merge
        success = await self._prs.merge_pr(pr_number)
        if success:
            self._finalize_resolved(issue_number, merged=True)
            await self._prs.post_comment(
                issue_number,
                "**PR Unsticker** merged PR successfully after fix.\n\n"
                "---\n*Automated by HydraFlow PR Unsticker*",
            )
            logger.info(
                "PR Unsticker merged PR #%d for issue #%d",
                pr_number,
                issue_number,
            )
            return True
        else:
            await self._release_back_to_hitl(
                issue_number, f"Merge failed for PR #{pr_number}"
            )
            return False

    def _finalize_resolved(self, issue_number: int, *, merged: bool = False) -> None:
        """Clean up HITL state after successful resolution."""
        self._state.remove_hitl_origin(issue_number)
        self._state.remove_hitl_cause(issue_number)
        self._state.reset_issue_attempts(issue_number)
        if merged:
            self._state.record_pr_merged()

    async def _re_rebase_remaining(self, remaining: list[HITLItem]) -> None:
        """Rebase remaining fixed items on updated main after a merge."""
        for item in remaining:
            issue_number = item.issue
            branch = self._config.branch_for_issue(issue_number)
            wt_path = self._config.worktree_path_for_issue(issue_number)

            if not wt_path.is_dir():
                continue

            try:
                await self._worktrees.start_merge_main(wt_path, branch)
            except Exception:
                logger.warning(
                    "Re-rebase failed for issue #%d after merge",
                    issue_number,
                    exc_info=True,
                )

    async def _resolve_conflicts(
        self,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
        pr_url: str,
        pr_number: int = 0,
    ) -> ConflictResolutionResult:
        """Run the conflict resolution loop, mirroring ReviewPhase logic.

        Returns a :class:`ConflictResolutionResult` — *used_rebuild* is True
        when the fresh-branch rebuild path was taken.
        """
        from conflict_prompt import build_conflict_prompt

        max_attempts = self._config.max_merge_conflict_fix_attempts
        last_error: str | None = None

        for attempt in range(1, max_attempts + 1):
            # Abort any prior failed merge before retrying
            if attempt > 1:
                await self._worktrees.abort_merge(wt_path)

            # Start merge leaving conflict markers in place
            clean = await self._worktrees.start_merge_main(wt_path, branch)
            if clean:
                return ConflictResolutionResult(success=True, used_rebuild=False)

            logger.info(
                "Unsticker conflict resolution attempt %d/%d for issue #%d",
                attempt,
                max_attempts,
                issue_number,
            )

            try:
                prompt = build_conflict_prompt(
                    issue.url, pr_url, last_error, attempt, config=self._config
                )
                cmd = self._agents._build_command(wt_path)
                transcript = await self._agents._execute(
                    cmd,
                    prompt,
                    wt_path,
                    {"issue": issue_number, "source": "pr_unsticker"},
                )

                self._save_transcript(issue_number, attempt, transcript)

                try:
                    await file_memory_suggestion(
                        transcript,
                        "pr_unsticker",
                        f"issue #{issue_number}",
                        self._config,
                        self._prs,
                        self._state,
                    )
                except Exception:
                    logger.exception(
                        "Failed to file memory suggestion for unsticker on issue #%d",
                        issue_number,
                    )

                success, error_msg = await self._agents._verify_result(wt_path, branch)
                if success:
                    return ConflictResolutionResult(success=True, used_rebuild=False)

                last_error = error_msg
                logger.warning(
                    "Unsticker attempt %d/%d failed for issue #%d: %s",
                    attempt,
                    max_attempts,
                    issue_number,
                    error_msg[:200] if error_msg else "",
                )
            except Exception as exc:
                logger.error(
                    "Unsticker agent failed for issue #%d (attempt %d/%d): %s",
                    issue_number,
                    attempt,
                    max_attempts,
                    exc,
                )
                last_error = str(exc)

        # All merge attempts exhausted — abort and try fresh rebuild
        await self._worktrees.abort_merge(wt_path)

        rebuilt = await self._fresh_branch_rebuild(
            issue_number, issue, branch, pr_url, pr_number
        )
        if rebuilt:
            return ConflictResolutionResult(success=True, used_rebuild=True)

        return ConflictResolutionResult(success=False, used_rebuild=False)

    async def _fresh_branch_rebuild(
        self,
        issue_number: int,
        issue: GitHubIssue,
        branch: str,
        pr_url: str,
        pr_number: int,
    ) -> bool:
        """Rebuild the PR branch from scratch on a fresh branch from main.

        Fetches the PR diff, destroys the old conflicted worktree, creates a
        fresh worktree from main, and runs an agent to re-apply the changes.
        Returns *True* if the rebuild succeeded and verified.
        """
        from conflict_prompt import build_rebuild_prompt

        if not self._config.enable_fresh_branch_rebuild:
            logger.info(
                "Fresh branch rebuild disabled — skipping for issue #%d",
                issue_number,
            )
            return False

        if not pr_number:
            logger.warning(
                "No PR number for issue #%d — cannot fetch diff for rebuild",
                issue_number,
            )
            return False

        # Fetch the PR diff
        pr_diff = await self._prs.get_pr_diff(pr_number)
        if not pr_diff.strip():
            logger.warning(
                "Empty PR diff for issue #%d — skipping fresh rebuild",
                issue_number,
            )
            return False

        logger.info(
            "Attempting fresh branch rebuild for issue #%d (PR #%d)",
            issue_number,
            pr_number,
        )

        # Destroy old worktree and create fresh one from main
        await self._worktrees.destroy(issue_number)
        new_wt = await self._worktrees.create(issue_number, branch)

        try:
            prompt = build_rebuild_prompt(
                issue.url,
                pr_url,
                issue_number,
                pr_diff,
                config=self._config,
            )
            cmd = self._agents._build_command(new_wt)
            transcript = await self._agents._execute(
                cmd,
                prompt,
                new_wt,
                {"issue": issue_number, "source": "fresh_rebuild"},
            )

            self._save_transcript(issue_number, 0, transcript)

            try:
                await file_memory_suggestion(
                    transcript,
                    "fresh_rebuild",
                    f"issue #{issue_number}",
                    self._config,
                    self._prs,
                    self._state,
                )
            except Exception:
                logger.exception(
                    "Failed to file memory suggestion for fresh rebuild on issue #%d",
                    issue_number,
                )

            success, error_msg = await self._agents._verify_result(new_wt, branch)
            if success:
                logger.info(
                    "Fresh branch rebuild succeeded for issue #%d", issue_number
                )
                return True

            logger.warning(
                "Fresh branch rebuild verification failed for issue #%d: %s",
                issue_number,
                error_msg[:200] if error_msg else "",
            )
            return False
        except Exception as exc:
            logger.error(
                "Fresh branch rebuild agent failed for issue #%d: %s",
                issue_number,
                exc,
            )
            return False

    async def _release_back_to_hitl(self, issue_number: int, reason: str) -> None:
        """Remove active label and re-add HITL label."""
        await self._prs.swap_pipeline_labels(issue_number, self._config.hitl_label[0])
        await self._prs.post_comment(
            issue_number,
            f"**PR Unsticker** could not resolve: {reason}\n\n"
            "Returning to HITL for manual intervention."
            "\n\n---\n*Automated by HydraFlow PR Unsticker*",
        )

    def _is_merge_conflict(self, cause: str) -> bool:
        """Return *True* if *cause* indicates a merge conflict."""
        lower = cause.lower()
        return any(kw in lower for kw in _MERGE_CONFLICT_KEYWORDS)

    def _save_transcript(
        self, issue_number: int, attempt: int, transcript: str
    ) -> None:
        """Save a conflict resolution transcript to ``.hydraflow/logs/``."""
        log_dir = self._config.log_dir
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"unsticker-issue-{issue_number}-attempt-{attempt}.txt"
            path.write_text(transcript)
            logger.info(
                "Unsticker transcript saved to %s",
                path,
                extra={"issue": issue_number},
            )
        except OSError:
            logger.warning(
                "Could not save unsticker transcript to %s",
                log_dir,
                exc_info=True,
                extra={"issue": issue_number},
            )
