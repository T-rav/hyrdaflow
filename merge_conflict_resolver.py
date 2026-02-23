"""Merge conflict resolution for the HydraFlow review pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from agent import AgentRunner
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from memory import file_memory_suggestion
from models import GitHubIssue, PRInfo, WorkerStatus
from pr_manager import PRManager
from state import StateTracker
from transcript_summarizer import TranscriptSummarizer
from worktree import WorktreeManager

logger = logging.getLogger("hydraflow.merge_conflict_resolver")


class MergeConflictResolver:
    """Resolves merge conflicts between PR branches and main."""

    def __init__(
        self,
        config: HydraFlowConfig,
        worktrees: WorktreeManager,
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
        issue: GitHubIssue,
        wt_path: Path,
        worker_id: int,
        escalate_fn: Callable[..., Coroutine[Any, Any, None]],
        publish_fn: Callable[..., Coroutine[Any, Any, None]],
    ) -> bool:
        """Merge main into the PR branch, resolving conflicts if needed.

        Returns True on success, False on failure (escalates to HITL).
        """
        await publish_fn(pr, worker_id, "merge_main")
        merged = await self._worktrees.merge_main(wt_path, pr.branch)
        if not merged:
            logger.info(
                "PR #%d has conflicts with %s — running agent to resolve",
                pr.number,
                self._config.main_branch,
            )
            await publish_fn(pr, worker_id, WorkerStatus.MERGE_FIX.value)
            merged = await self.resolve_merge_conflicts(
                pr, issue, wt_path, worker_id=worker_id
            )
        if merged:
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
        )
        return False

    async def resolve_merge_conflicts(
        self,
        pr: PRInfo,
        issue: GitHubIssue,
        wt_path: Path,
        worker_id: int,
    ) -> bool:
        """Use the implementation agent to resolve merge conflicts.

        Retries up to ``config.max_merge_conflict_fix_attempts`` times.
        Each attempt starts a merge (leaving conflict markers), runs the
        agent to resolve them, and verifies with ``make quality``.
        Returns *True* if the conflicts were resolved successfully.
        """
        from conflict_prompt import build_conflict_prompt

        if self._agents is None:
            logger.warning(
                "No agent runner available for conflict resolution on PR #%d",
                pr.number,
            )
            return False

        max_attempts = self._config.max_merge_conflict_fix_attempts
        last_error: str | None = None

        for attempt in range(1, max_attempts + 1):
            # Abort any prior failed merge before retrying
            if attempt > 1:
                await self._worktrees.abort_merge(wt_path)

            # Start merge leaving conflict markers in place
            clean = await self._worktrees.start_merge_main(wt_path, pr.branch)
            if clean:
                return True

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
                    issue.url, pr.url, last_error, attempt, config=self._config
                )
                cmd = self._agents._build_command(wt_path)
                transcript = await self._agents._execute(
                    cmd,
                    prompt,
                    wt_path,
                    {"issue": issue.number, "source": "merge_conflict"},
                )

                self._save_conflict_transcript(
                    pr.number, issue.number, attempt, transcript
                )

                try:
                    await file_memory_suggestion(
                        transcript,
                        "conflict_resolver",
                        f"PR #{pr.number}",
                        self._config,
                        self._prs,
                        self._state,
                    )
                except Exception:
                    logger.exception(
                        "Failed to file memory suggestion for conflict resolution on PR #%d",
                        pr.number,
                    )

                success, error_msg = await self._agents._verify_result(
                    wt_path, pr.branch
                )
                if success:
                    await self._maybe_summarize_conflict(
                        transcript, issue.number, pr.number
                    )
                    return True

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
                        transcript, issue.number, pr.number
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

        # All attempts exhausted — abort and let caller escalate
        await self._worktrees.abort_merge(wt_path)
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

    def _save_conflict_transcript(
        self,
        pr_number: int,
        issue_number: int,
        attempt: int,
        transcript: str,
    ) -> None:
        """Save a conflict resolution transcript to ``.hydraflow/logs/``."""
        log_dir = self._config.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"conflict-pr-{pr_number}-attempt-{attempt}.txt"
        path.write_text(transcript)
        logger.info(
            "Conflict resolution transcript saved to %s",
            path,
            extra={"issue": issue_number},
        )

    async def _publish_review_status(
        self, pr: PRInfo, worker_id: int, status: str
    ) -> None:
        """Emit a REVIEW_UPDATE event with the given status."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.REVIEW_UPDATE,
                data={
                    "pr": pr.number,
                    "issue": pr.issue_number,
                    "worker": worker_id,
                    "status": status,
                    "role": "reviewer",
                },
            )
        )
