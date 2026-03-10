"""Pre-merge preview verification phase.

When enabled, approved PRs are held for reporter verification on a preview
deployment before merging.  The phase detects deployment URLs via the GitHub
Deployments API (provider-agnostic), posts them on the issue, and waits for
reporter feedback before merging or re-routing for another implementation cycle.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from events import EventType, HydraFlowEvent
from issue_store import STAGE_PREVIEW

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from issue_store import IssueStore
    from models import Task
    from post_merge_handler import PostMergeHandler
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.preview_phase")

# Keywords that indicate reporter approval (case-insensitive)
_APPROVAL_KEYWORDS = [
    "looks good",
    "lgtm",
    "approved",
    "verified",
    "works for me",
    "all good",
    "ship it",
]

# Keywords that indicate reporter rejection (case-insensitive)
_REJECTION_KEYWORDS = [
    "still broken",
    "not fixed",
    "rejected",
    "doesn't work",
    "still not working",
    "still failing",
    "needs more work",
]

_PREVIEW_COMMENT_MARKER = "<!-- hydraflow-preview-url -->"


class PreviewPhase:
    """Pre-merge reporter verification gate."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRManager,
        store: IssueStore,
        event_bus: EventBus,
        post_merge: PostMergeHandler,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._store = store
        self._bus = event_bus
        self._post_merge = post_merge

    async def process_preview_issues(self) -> bool:
        """Work function called by the polling loop.  Returns True if work done."""
        if not self._config.preview_enabled:
            return False

        tasks = self._store.get_previewable(max_count=5)
        if not tasks:
            return False

        for task in tasks:
            self._store.mark_active(task.id, STAGE_PREVIEW)
            try:
                await self._process_single(task)
            except Exception:
                logger.exception("Preview processing failed for issue #%d", task.id)
            finally:
                self._store.mark_done(task.id)

        return True

    async def _process_single(self, task: Task) -> None:
        """Process a single preview-stage issue."""
        issue_number = task.id

        # Find the PR for this issue
        pr_number = await self._find_pr_for_issue(issue_number)
        if pr_number == 0:
            logger.warning("No PR found for preview issue #%d — skipping", issue_number)
            return

        # Check if we've already posted the preview URL
        preview_started = self._state.get_preview_started(issue_number)

        if not preview_started:
            await self._handle_first_seen(issue_number, pr_number)
            return

        # We've been tracking this issue — check for feedback or timeout
        await self._handle_tracked_issue(issue_number, pr_number, preview_started)

    async def _handle_first_seen(self, issue_number: int, pr_number: int) -> None:
        """Handle an issue seen for the first time in the preview stage."""
        deploy_url = await self._prs.get_deployment_url(pr_number)
        now = datetime.now(UTC).isoformat()
        self._state.set_preview_started(issue_number, now)

        if not deploy_url:
            logger.info(
                "No deployment found for issue #%d (PR #%d) — will poll",
                issue_number,
                pr_number,
            )
            return

        await self._post_preview_url(issue_number, deploy_url, pr_number)
        await self._publish_preview_event(
            issue_number, pr_number, "deployment_found", deploy_url
        )

    async def _handle_tracked_issue(
        self, issue_number: int, pr_number: int, preview_started: str
    ) -> None:
        """Handle an issue already being tracked in the preview stage."""
        started_at = datetime.fromisoformat(preview_started)

        # Check if preview URL has been posted yet
        if not self._state.is_preview_url_posted(issue_number):
            await self._poll_for_deployment(issue_number, pr_number, started_at)
            return

        # Preview URL posted — check for reporter feedback
        feedback = await self._check_reporter_feedback(issue_number)
        if feedback is not None:
            is_approval, author, body = feedback
            if is_approval:
                logger.info(
                    "Issue #%d: reporter %s approved preview",
                    issue_number,
                    author,
                )
                await self._prs.post_comment(
                    issue_number,
                    f"Reporter @{author} verified the preview deployment. "
                    f"Proceeding to merge.",
                )
                await self._publish_preview_event(issue_number, pr_number, "approved")
                await self._proceed_to_merge(issue_number, pr_number)
            else:
                logger.info(
                    "Issue #%d: reporter %s rejected preview",
                    issue_number,
                    author,
                )
                await self._prs.post_comment(
                    issue_number,
                    f"Reporter @{author} found issues with the preview:\n\n"
                    f"> {body}\n\n"
                    f"Routing back for another implementation cycle.",
                )
                await self._publish_preview_event(issue_number, pr_number, "rejected")
                await self._route_back_to_implementation(issue_number)
            return

        # No feedback yet — check timeout
        elapsed_hours = (datetime.now(UTC) - started_at).total_seconds() / 3600
        if elapsed_hours > self._config.preview_timeout_hours:
            await self._handle_timeout(issue_number, pr_number)

    async def _find_pr_for_issue(self, issue_number: int) -> int:
        """Find the PR number linked to this issue.  Returns 0 if not found."""
        return await self._prs.find_pr_for_issue(issue_number)

    async def _post_preview_url(
        self, issue_number: int, deploy_url: str, pr_number: int
    ) -> None:
        """Post the preview deployment URL as a comment on the issue."""
        body = (
            f"{_PREVIEW_COMMENT_MARKER}\n"
            f"## Preview Deployment Ready\n\n"
            f"A preview deployment is available for testing:\n\n"
            f"**{deploy_url}**\n\n"
            f"Please test the changes and reply with your feedback:\n"
            f'- Reply **"looks good"** or **"approved"** to proceed with merge\n'
            f'- Reply **"not fixed"** or describe remaining issues to request changes\n\n'
            f"This preview will remain active until the PR is merged or closed.\n"
            f"_Auto-action in {self._config.preview_timeout_hours} hours if no response._"
        )
        await self._prs.post_comment(issue_number, body)
        self._state.mark_preview_url_posted(issue_number)
        logger.info(
            "Posted preview URL for issue #%d (PR #%d): %s",
            issue_number,
            pr_number,
            deploy_url,
        )

    async def _poll_for_deployment(
        self, issue_number: int, pr_number: int, started_at: datetime
    ) -> None:
        """Poll for deployment URL; merge without preview if timed out."""
        deploy_url = await self._prs.get_deployment_url(pr_number)
        if deploy_url:
            await self._post_preview_url(issue_number, deploy_url, pr_number)
            await self._publish_preview_event(
                issue_number, pr_number, "deployment_found", deploy_url
            )
            return

        elapsed_minutes = (datetime.now(UTC) - started_at).total_seconds() / 60
        if elapsed_minutes > self._config.preview_deploy_poll_minutes:
            logger.warning(
                "No deployment found for issue #%d after %d min — "
                "proceeding to merge without preview",
                issue_number,
                int(elapsed_minutes),
            )
            await self._prs.post_comment(
                issue_number,
                "No preview deployment was detected for this PR. "
                "Proceeding to merge without reporter verification.\n\n"
                "To enable preview deployments, connect a deployment "
                "provider (Render, Vercel, Netlify, etc.) to your repo.",
            )
            await self._proceed_to_merge(issue_number, pr_number)

    async def _check_reporter_feedback(
        self, issue_number: int
    ) -> tuple[bool, str, str] | None:
        """Check issue comments for reporter approval or rejection.

        Returns (is_approval, author, body) or None if no feedback found.
        Only considers comments posted after the preview URL was posted.
        """
        comments = await self._prs.get_issue_comments_with_body(issue_number)
        if not comments:
            return None

        # Find the preview comment timestamp to only check newer comments
        preview_comment_idx = -1
        for i, c in enumerate(comments):
            if _PREVIEW_COMMENT_MARKER in c.get("body", ""):
                preview_comment_idx = i

        # Only check comments after the preview URL comment
        if preview_comment_idx < 0:
            return None

        for comment in comments[preview_comment_idx + 1 :]:
            body = comment.get("body", "").strip()
            author = comment.get("author", "")
            body_lower = body.lower()

            # Check approval keywords
            for keyword in _APPROVAL_KEYWORDS:
                if keyword in body_lower:
                    return (True, author, body)

            # Check rejection keywords
            for keyword in _REJECTION_KEYWORDS:
                if keyword in body_lower:
                    return (False, author, body)

        return None

    async def _proceed_to_merge(self, issue_number: int, pr_number: int) -> None:
        """Transition issue to merge — swap to review label for merge flow."""
        self._state.clear_preview(issue_number)
        await self._prs.swap_pipeline_labels(
            issue_number,
            self._config.review_label[0],
        )

    async def _route_back_to_implementation(self, issue_number: int) -> None:
        """Route issue back to implementation for another cycle."""
        self._state.clear_preview(issue_number)
        await self._prs.swap_pipeline_labels(
            issue_number,
            self._config.ready_label[0],
        )

    async def _handle_timeout(self, issue_number: int, pr_number: int) -> None:
        """Handle preview timeout based on configured action."""
        action = self._config.preview_timeout_action
        logger.warning(
            "Preview timeout for issue #%d (PR #%d) after %dh — action: %s",
            issue_number,
            pr_number,
            self._config.preview_timeout_hours,
            action,
        )

        if action == "merge":
            await self._prs.post_comment(
                issue_number,
                f"No reporter feedback received after "
                f"{self._config.preview_timeout_hours} hours. "
                f"Auto-merging the approved PR.",
            )
            await self._proceed_to_merge(issue_number, pr_number)
        else:
            # Escalate to HITL
            await self._prs.post_comment(
                issue_number,
                f"No reporter feedback received after "
                f"{self._config.preview_timeout_hours} hours. "
                f"Escalating to human-in-the-loop for manual review.",
            )
            self._state.clear_preview(issue_number)
            await self._prs.swap_pipeline_labels(
                issue_number,
                self._config.hitl_label[0],
            )

        await self._publish_preview_event(issue_number, pr_number, f"timeout_{action}")

    async def _publish_preview_event(
        self,
        issue_number: int,
        pr_number: int,
        status: str,
        deploy_url: str = "",
    ) -> None:
        """Publish a PREVIEW_UPDATE event."""
        data: dict[str, Any] = {
            "issue": issue_number,
            "pr": pr_number,
            "status": status,
        }
        if deploy_url:
            data["deploy_url"] = deploy_url
        await self._bus.publish(
            HydraFlowEvent(type=EventType.PREVIEW_UPDATE, data=data)
        )
