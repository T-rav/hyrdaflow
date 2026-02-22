"""Background worker that resolves merge-conflict HITL items autonomously."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memory import file_memory_suggestion

if TYPE_CHECKING:
    from agent import AgentRunner
    from config import HydraFlowConfig
    from events import EventBus
    from issue_fetcher import IssueFetcher
    from models import HITLItem
    from pr_manager import PRManager
    from state import StateTracker
    from worktree import WorktreeManager

logger = logging.getLogger("hydraflow.pr_unsticker")

# Keywords that indicate a merge conflict cause
_MERGE_CONFLICT_KEYWORDS = ("merge conflict", "conflict")


class PRUnsticker:
    """Resolve merge-conflict HITL items by running the implementation agent."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        event_bus: EventBus,
        pr_manager: PRManager,
        agents: AgentRunner,
        worktrees: WorktreeManager,
        fetcher: IssueFetcher,
    ) -> None:
        self._config = config
        self._state = state
        self._bus = event_bus
        self._prs = pr_manager
        self._agents = agents
        self._worktrees = worktrees
        self._fetcher = fetcher

    async def unstick(self, hitl_items: list[HITLItem]) -> dict[str, Any]:
        """Process merge-conflict HITL items and return stats.

        Returns a dict with keys: ``processed``, ``resolved``, ``failed``,
        ``skipped``.
        """
        from events import EventType, HydraFlowEvent

        stats: dict[str, int] = {
            "processed": 0,
            "resolved": 0,
            "failed": 0,
            "skipped": 0,
        }

        if not hitl_items:
            return stats

        # Filter to merge-conflict items only
        candidates = [
            item
            for item in hitl_items
            if self._is_merge_conflict(self._state.get_hitl_cause(item.issue) or "")
        ]

        # Apply batch size limit
        batch = candidates[: self._config.pr_unstick_batch_size]
        stats["skipped"] = len(hitl_items) - len(batch)

        for item in batch:
            stats["processed"] += 1
            success = await self._process_item(item)
            if success:
                stats["resolved"] += 1
            else:
                stats["failed"] += 1

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.HITL_UPDATE,
                    data={
                        "issue": item.issue,
                        "action": "unstick_resolved" if success else "unstick_failed",
                        "source": "pr_unsticker",
                    },
                )
            )

        return stats

    async def _process_item(self, item: HITLItem) -> bool:
        """Attempt to resolve merge conflicts for a single HITL item.

        Returns *True* if conflicts were resolved successfully.
        """
        issue_number = item.issue
        branch = self._config.branch_for_issue(issue_number)

        # Claim: swap labels
        await self._prs.swap_pipeline_labels(
            issue_number, self._config.hitl_active_label[0]
        )

        await self._prs.post_comment(
            issue_number,
            "**PR Unsticker** attempting to resolve merge conflicts...\n\n"
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

            # Run conflict resolution loop
            resolved = await self._resolve_conflicts(
                issue_number, issue, wt_path, branch, pr_url=item.prUrl
            )

            if resolved:
                # Push the fixed branch
                await self._prs.push_branch(wt_path, branch)

                # Restore origin label (swap removes all pipeline labels first)
                origin = self._state.get_hitl_origin(issue_number)
                if origin:
                    await self._prs.swap_pipeline_labels(issue_number, origin)
                else:
                    for lbl in self._config.hitl_active_label:
                        await self._prs.remove_label(issue_number, lbl)

                # Clear HITL state
                self._state.remove_hitl_origin(issue_number)
                self._state.remove_hitl_cause(issue_number)
                self._state.reset_issue_attempts(issue_number)

                await self._prs.post_comment(
                    issue_number,
                    "**PR Unsticker** resolved merge conflicts successfully.\n\n"
                    f"Returning issue to `{origin or 'pipeline'}` stage."
                    "\n\n---\n*Automated by HydraFlow PR Unsticker*",
                )

                logger.info(
                    "PR Unsticker resolved merge conflicts for issue #%d",
                    issue_number,
                )
                return True
            else:
                await self._release_back_to_hitl(
                    issue_number, "All conflict resolution attempts exhausted"
                )
                return False

        except Exception:
            logger.exception("PR Unsticker failed for issue #%d", issue_number)
            await self._release_back_to_hitl(
                issue_number, "Unexpected error during conflict resolution"
            )
            return False

    async def _resolve_conflicts(
        self,
        issue_number: int,
        issue: Any,
        wt_path: Path,
        branch: str,
        pr_url: str,
    ) -> bool:
        """Run the conflict resolution loop, mirroring ReviewPhase logic."""
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
                return True

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
                    cmd, prompt, wt_path, issue_number
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
                    return True

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

        # All attempts exhausted — abort the merge
        await self._worktrees.abort_merge(wt_path)
        return False

    async def _release_back_to_hitl(self, issue_number: int, reason: str) -> None:
        """Remove active label and re-add HITL label."""
        await self._prs.swap_pipeline_labels(issue_number, self._config.hitl_label[0])
        await self._prs.post_comment(
            issue_number,
            f"**PR Unsticker** could not resolve merge conflicts: {reason}\n\n"
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
        log_dir = self._config.repo_root / ".hydraflow" / "logs"
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
