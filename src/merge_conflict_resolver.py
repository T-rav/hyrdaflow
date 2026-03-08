"""Merge conflict resolution for the HydraFlow review pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from agent import AgentRunner
from config import HydraFlowConfig
from events import EventBus
from models import (
    ConflictResolutionResult,
    EscalateFn,
    PRInfo,
    PublishFn,
    Task,
    WorkerStatus,
)
from phase_utils import publish_review_status, safe_file_memory_suggestion
from pr_manager import PRManager
from prompt_stats import build_prompt_stats
from state import StateTracker
from transcript_summarizer import TranscriptSummarizer
from workspace import WorkspaceManager

logger = logging.getLogger("hydraflow.merge_conflict_resolver")


class MergeConflictResolver:
    """Resolves merge conflicts between PR branches and main."""

    def __init__(
        self,
        config: HydraFlowConfig,
        worktrees: WorkspaceManager,
        agents: AgentRunner | None,
        prs: PRManager,
        event_bus: EventBus,
        state: StateTracker,
        summarizer: TranscriptSummarizer | None,
    ) -> None:
        self._config = config
        self._worktrees = worktrees
        self._agents = agents
        self._prs = prs
        self._bus = event_bus
        self._state = state
        self._summarizer = summarizer

    async def merge_with_main(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        worker_id: int,
        escalate_fn: EscalateFn,
        publish_fn: PublishFn,
    ) -> bool:
        """Merge main into the PR branch, resolving conflicts if needed.

        Returns True on success, False on failure (escalates to HITL).
        """
        await publish_fn(pr, worker_id, "merge_main")
        merged = await self._worktrees.merge_main(wt_path, pr.branch)
        used_rebuild = False
        if not merged:
            logger.info(
                "PR #%d has conflicts with %s — running agent to resolve",
                pr.number,
                self._config.main_branch,
            )
            await publish_fn(pr, worker_id, WorkerStatus.MERGE_FIX.value)
            resolution = await self.resolve_merge_conflicts(
                pr, issue, wt_path, worker_id=worker_id
            )
            merged = resolution.success
            used_rebuild = resolution.used_rebuild
        if merged:
            if used_rebuild:
                # Branch history was rewritten — need force-push
                new_wt = self._config.worktree_path_for_issue(pr.issue_number)
                await self._prs.push_branch(new_wt, pr.branch, force=True)
            else:
                await self._prs.push_branch(wt_path, pr.branch)
            return True

        logger.warning(
            "PR #%d merge conflict resolution failed — escalating to HITL",
            pr.number,
        )
        await publish_fn(pr, worker_id, "escalating")
        await escalate_fn(
            pr.issue_number,
            pr.number,
            cause="Merge conflict with main branch",
            origin_label=self._config.review_label[0],
            comment=(
                f"**Merge conflicts** with "
                f"`{self._config.main_branch}` could not be "
                "resolved automatically. "
                "Escalating to human review."
            ),
            event_cause="merge_conflict",
            task=issue,
        )
        return False

    async def resolve_merge_conflicts(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        worker_id: int | None = None,
        source: str = "merge_conflict",
    ) -> ConflictResolutionResult:
        """Use the implementation agent to resolve merge conflicts.

        Retries up to ``config.max_merge_conflict_fix_attempts`` times.
        Each attempt starts a merge (leaving conflict markers), runs the
        agent to resolve them, and verifies with ``make quality``.

        If all merge attempts fail, falls back to :meth:`fresh_branch_rebuild`
        which destroys the worktree and re-applies the PR diff on a clean
        branch from main.

        Returns a :class:`ConflictResolutionResult` — *used_rebuild* is True
        when the fresh rebuild path was taken (caller should force-push).
        """
        from conflict_prompt import build_conflict_prompt

        if self._agents is None:
            logger.warning(
                "No agent runner available for conflict resolution on PR #%d",
                pr.number,
            )
            return ConflictResolutionResult(success=False, used_rebuild=False)

        max_attempts = self._config.max_merge_conflict_fix_attempts
        last_error: str | None = None

        for attempt in range(1, max_attempts + 1):
            # Abort any prior failed merge before retrying
            if attempt > 1:
                await self._worktrees.abort_merge(wt_path)

            # Start merge leaving conflict markers in place
            clean = await self._worktrees.start_merge_main(wt_path, pr.branch)
            if clean:
                return ConflictResolutionResult(success=True, used_rebuild=False)

            logger.info(
                "Conflict resolution attempt %d/%d for PR #%d",
                attempt,
                max_attempts,
                pr.number,
            )
            await self._publish_review_status(
                pr, worker_id, WorkerStatus.MERGE_FIX.value
            )

            try:
                prompt = build_conflict_prompt(
                    issue.source_url, pr.url, last_error, attempt, config=self._config
                )
                error_before = 0
                error_after = 0
                if last_error and attempt > 1:
                    error_before = len(last_error)
                    error_after = min(error_before, self._config.error_output_max_chars)
                prompt_stats = build_prompt_stats(
                    history_before=error_before,
                    history_after=error_after,
                    section_chars={
                        "previous_error_before": error_before,
                        "previous_error_after": error_after,
                    },
                )
                cmd = self._agents._build_command(wt_path)
                transcript = await self._agents._execute(
                    cmd,
                    prompt,
                    wt_path,
                    {"issue": issue.id, "source": source},
                    telemetry_stats=prompt_stats,
                )

                self.save_conflict_transcript(
                    pr.number, issue.id, attempt, transcript, source=source
                )

                await safe_file_memory_suggestion(
                    transcript,
                    source,
                    f"PR #{pr.number}",
                    self._config,
                    self._prs,
                    self._state,
                )

                success, error_msg = await self._agents._verify_result(
                    wt_path, pr.branch
                )
                if success:
                    await self._maybe_summarize_conflict(
                        transcript, issue.id, pr.number
                    )
                    return ConflictResolutionResult(success=True, used_rebuild=False)

                last_error = error_msg
                logger.warning(
                    "Conflict resolution attempt %d/%d failed for PR #%d: %s",
                    attempt,
                    max_attempts,
                    pr.number,
                    error_msg[:200] if error_msg else "",
                )
                # Summarize final failed attempt
                if attempt == max_attempts:
                    await self._maybe_summarize_conflict(
                        transcript, issue.id, pr.number
                    )
            except Exception as exc:
                logger.error(
                    "Conflict resolution agent failed for PR #%d (attempt %d/%d): %s",
                    pr.number,
                    attempt,
                    max_attempts,
                    exc,
                )
                last_error = str(exc)

        # All merge attempts exhausted — abort merge and try fresh rebuild
        await self._worktrees.abort_merge(wt_path)

        logger.info(
            "All %d merge attempts exhausted for PR #%d — trying fresh branch rebuild",
            max_attempts,
            pr.number,
        )
        rebuilt = await self.fresh_branch_rebuild(
            pr, issue, worker_id=worker_id, source=source
        )
        if rebuilt:
            return ConflictResolutionResult(success=True, used_rebuild=True)

        return ConflictResolutionResult(success=False, used_rebuild=False)

    async def fresh_branch_rebuild(
        self,
        pr: PRInfo,
        issue: Task,
        worker_id: int | None = None,
        source: str = "fresh_rebuild",
    ) -> bool:
        """Rebuild the PR branch from scratch on a fresh branch from main.

        Fetches the PR diff, destroys the old conflicted worktree, creates a
        fresh worktree from main, and runs an agent to re-apply the changes.
        Returns *True* if the rebuild succeeded and verified.
        """
        from conflict_prompt import build_rebuild_prompt

        if not self._config.enable_fresh_branch_rebuild:
            logger.info(
                "Fresh branch rebuild disabled — skipping for PR #%d", pr.number
            )
            return False

        if self._agents is None:
            logger.warning("No agent runner for fresh rebuild on PR #%d", pr.number)
            return False

        # Fetch the PR diff
        pr_diff = await self._prs.get_pr_diff(pr.number)
        if not pr_diff.strip():
            logger.warning(
                "Empty PR diff for PR #%d — skipping fresh rebuild", pr.number
            )
            return False

        await self._publish_review_status(
            pr, worker_id, WorkerStatus.FRESH_REBUILD.value
        )

        # Destroy old worktree and create fresh one from main
        await self._worktrees.destroy(pr.issue_number)
        new_wt = await self._worktrees.create(pr.issue_number, pr.branch)

        logger.info(
            "Fresh branch rebuild: created clean worktree at %s for PR #%d",
            new_wt,
            pr.number,
        )

        try:
            prompt = build_rebuild_prompt(
                issue.source_url,
                pr.url,
                issue.id,
                pr_diff,
                config=self._config,
            )
            prompt_stats = build_prompt_stats(
                context_before=len(pr_diff),
                context_after=min(len(pr_diff), self._config.max_review_diff_chars),
                section_chars={
                    "pr_diff_before": len(pr_diff),
                    "pr_diff_after": min(
                        len(pr_diff), self._config.max_review_diff_chars
                    ),
                },
            )
            cmd = self._agents._build_command(new_wt)
            transcript = await self._agents._execute(
                cmd,
                prompt,
                new_wt,
                {"issue": issue.id, "source": source},
                telemetry_stats=prompt_stats,
            )

            self.save_conflict_transcript(
                pr.number, issue.id, 0, transcript, source=source
            )

            await safe_file_memory_suggestion(
                transcript,
                source,
                f"PR #{pr.number}",
                self._config,
                self._prs,
                self._state,
            )

            success, error_msg = await self._agents._verify_result(new_wt, pr.branch)
            if success:
                await self._maybe_summarize_conflict(transcript, issue.id, pr.number)
                logger.info("Fresh branch rebuild succeeded for PR #%d", pr.number)
                return True

            logger.warning(
                "Fresh branch rebuild verification failed for PR #%d: %s",
                pr.number,
                error_msg[:200] if error_msg else "",
            )
            return False
        except Exception as exc:
            logger.error(
                "Fresh branch rebuild agent failed for PR #%d: %s",
                pr.number,
                exc,
            )
            return False

    async def _maybe_summarize_conflict(
        self, transcript: str, issue_number: int, pr_number: int
    ) -> None:
        """Summarize a conflict resolution transcript if summarizer is available."""
        if self._summarizer is None:
            return
        try:
            await self._summarizer.summarize_and_publish(
                transcript=transcript,
                issue_number=issue_number,
                phase="conflict_resolution",
            )
        except Exception:
            logger.exception(
                "Failed to file transcript summary for conflict resolution on PR #%d",
                pr_number,
            )

    def save_conflict_transcript(
        self,
        pr_number: int,
        issue_number: int,
        attempt: int,
        transcript: str,
        *,
        source: str = "conflict",
    ) -> None:
        """Save a conflict resolution transcript to ``.hydraflow/logs/``."""
        log_dir = self._config.log_dir
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"{source}-pr-{pr_number}-attempt-{attempt}.txt"
            path.write_text(transcript)
            logger.info(
                "Conflict resolution transcript saved to %s",
                path,
                extra={"issue": issue_number},
            )
        except OSError:
            logger.warning(
                "Could not save conflict transcript to %s",
                log_dir,
                exc_info=True,
                extra={"issue": issue_number},
            )

    async def _publish_review_status(
        self, pr: PRInfo, worker_id: int | None, status: str
    ) -> None:
        """Emit a REVIEW_UPDATE event with the given status.

        When *worker_id* is ``None`` (e.g. called from PRUnsticker),
        the event is silently skipped because the caller does not
        participate in review status tracking.
        """
        if worker_id is None:
            return
        await publish_review_status(self._bus, pr, worker_id, status)
