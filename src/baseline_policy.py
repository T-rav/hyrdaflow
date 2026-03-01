"""Baseline image ownership, approval, and rollback policy enforcement."""

from __future__ import annotations

import fnmatch
import logging
from datetime import UTC, datetime

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from models import (
    BaselineApprovalResult,
    BaselineAuditRecord,
    BaselineChangeType,
)
from state import StateTracker

logger = logging.getLogger("hydraflow.baseline_policy")


def _glob_match(path: str, pattern: str) -> bool:
    """Match *path* against a glob *pattern* with proper ``**`` support.

    ``fnmatch.fnmatch`` treats ``*`` as matching everything (including ``/``)
    but ``**`` in glob semantics should also match *zero* path segments.
    This helper strips leading ``**/`` and trailing ``/**`` to cover that case.
    """
    if fnmatch.fnmatch(path, pattern):
        return True
    # Handle ** matching zero directories by stripping leading **/ prefixes.
    stripped = pattern
    while stripped.startswith("**/"):
        stripped = stripped[3:]
        if fnmatch.fnmatch(path, stripped):
            return True
    # Handle trailing /** matching zero directories.
    stripped = pattern
    while stripped.endswith("/**"):
        stripped = stripped[:-3]
        if fnmatch.fnmatch(path, stripped):
            return True
    return False


class BaselinePolicy:
    """Enforces baseline image governance during the review phase.

    Responsibilities:
    - Detect baseline file changes in PR diffs using configurable globs
    - Require explicit approval from designated owners
    - Record an audit trail for every baseline change
    - Support rollback of bad baseline updates
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._state = state
        self._bus = event_bus

    def detect_baseline_changes(self, changed_files: list[str]) -> list[str]:
        """Return the subset of *changed_files* matching baseline patterns."""
        patterns = self._config.baseline_snapshot_patterns
        matched: list[str] = []
        for path in changed_files:
            for pattern in patterns:
                if _glob_match(path, pattern):
                    matched.append(path)
                    break
        return matched

    async def check_approval(
        self,
        pr_number: int,
        issue_number: int,
        changed_files: list[str],
        pr_approvers: list[str],
        commit_sha: str = "",
    ) -> BaselineApprovalResult:
        """Check whether baseline changes in a PR are properly approved.

        Args:
            pr_number: The PR being reviewed.
            issue_number: The linked issue number.
            changed_files: All files changed in the PR.
            pr_approvers: GitHub usernames that have approved the PR.
            commit_sha: HEAD commit SHA for the PR (recorded in audit trail).

        Returns:
            A :class:`BaselineApprovalResult` with approval status.
        """
        baseline_files = self.detect_baseline_changes(changed_files)

        if not baseline_files:
            return BaselineApprovalResult(
                approved=True,
                changed_files=[],
                reason="No baseline files changed",
                requires_approval=False,
            )

        if not self._config.baseline_approval_required:
            # Still record audit trail — all baseline changes must be tracked
            # regardless of approval policy.
            prior = self._state.get_baseline_audit(issue_number)
            change_type = (
                BaselineChangeType.INITIAL if not prior else BaselineChangeType.UPDATE
            )
            record = BaselineAuditRecord(
                pr_number=pr_number,
                issue_number=issue_number,
                changed_files=baseline_files,
                change_type=change_type,
                reason=f"Auto-approved (approval not required) via PR #{pr_number}",
                commit_sha=commit_sha,
            )
            self._state.record_baseline_change(
                issue_number,
                record,
                max_records=self._config.baseline_max_audit_records,
            )
            try:
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.BASELINE_UPDATE,
                        data={
                            "pr_number": pr_number,
                            "issue_number": issue_number,
                            "baseline_files": baseline_files,
                            "approved": True,
                            "approver": "",
                        },
                    )
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to publish BASELINE_UPDATE event for PR #%d",
                    pr_number,
                    exc_info=True,
                )
            return BaselineApprovalResult(
                approved=True,
                changed_files=baseline_files,
                reason="Baseline approval not required by policy",
                requires_approval=False,
            )

        # Check if any approver is in the allowed list
        allowed = self._config.baseline_approvers
        approver = ""

        if allowed:
            for user in pr_approvers:
                if user in allowed:
                    approver = user
                    break
        elif pr_approvers:
            # No restricted list — any approver is accepted
            approver = pr_approvers[0]

        approved = bool(approver)

        result = BaselineApprovalResult(
            approved=approved,
            approver=approver,
            changed_files=baseline_files,
            requires_approval=True,
            reason=(
                f"Approved by {approver}"
                if approved
                else "Baseline changes require approval from a designated owner"
            ),
        )

        # Record audit trail first — ensures persistence before any event is emitted.
        audit_reason = (
            f"Approved by {approver} via PR #{pr_number}"
            if approved
            else "Baseline approval denied — no authorized approver found"
        )
        # Use INITIAL type when this is the first baseline record for the issue.
        prior = self._state.get_baseline_audit(issue_number)
        change_type = (
            BaselineChangeType.INITIAL if not prior else BaselineChangeType.UPDATE
        )
        record = BaselineAuditRecord(
            pr_number=pr_number,
            issue_number=issue_number,
            changed_files=baseline_files,
            change_type=change_type,
            approver=approver,
            reason=audit_reason,
            commit_sha=commit_sha,
        )
        self._state.record_baseline_change(
            issue_number,
            record,
            max_records=self._config.baseline_max_audit_records,
        )

        # Publish event after audit is persisted; failures here are non-fatal.
        try:
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BASELINE_UPDATE,
                    data={
                        "pr_number": pr_number,
                        "issue_number": issue_number,
                        "baseline_files": baseline_files,
                        "approved": approved,
                        "approver": approver,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to publish BASELINE_UPDATE event for PR #%d",
                pr_number,
                exc_info=True,
            )

        if not approved:
            logger.warning(
                "Baseline approval denied for PR #%d (issue #%d): %d file(s) require "
                "approval from a designated owner. Files: %s",
                pr_number,
                issue_number,
                len(baseline_files),
                ", ".join(baseline_files),
            )

        return result

    async def rollback(
        self,
        issue_number: int,
        pr_number: int,
        approver: str,
        reason: str,
        commit_sha: str = "",
    ) -> BaselineAuditRecord:
        """Record a baseline rollback and publish an event.

        Returns the rollback audit record.

        Raises:
            ValueError: If ``approver`` is not in the configured allowed list.
        """
        allowed = self._config.baseline_approvers
        if allowed and approver not in allowed:
            raise ValueError(
                f"Rollback by '{approver}' not permitted; "
                f"authorised approvers: {allowed}"
            )

        record = self._state.rollback_baseline(
            issue_number=issue_number,
            pr_number=pr_number,
            approver=approver,
            reason=reason,
            commit_sha=commit_sha,
        )

        try:
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BASELINE_UPDATE,
                    data={
                        "pr_number": pr_number,
                        "issue_number": issue_number,
                        "baseline_files": record.changed_files,
                        "rollback": True,
                        "approver": approver,
                        "reason": reason,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to publish BASELINE_UPDATE event for rollback PR #%d",
                pr_number,
                exc_info=True,
            )

        logger.info(
            "Baseline rollback recorded for issue #%d (PR #%d) by %s: %s",
            issue_number,
            pr_number,
            approver,
            reason,
        )

        return record

    def get_audit_trail(self, issue_number: int) -> list[BaselineAuditRecord]:
        """Return the full audit trail for *issue_number*."""
        return self._state.get_baseline_audit(issue_number)

    def format_audit_summary(self, issue_number: int) -> str:
        """Return a human-readable summary of baseline changes for an issue."""
        records = self.get_audit_trail(issue_number)
        if not records:
            return "No baseline changes recorded."

        lines = [f"### Baseline Audit Trail (issue #{issue_number})\n"]
        for record in records:
            try:
                ts = (
                    datetime.fromisoformat(record.timestamp)
                    .astimezone(UTC)
                    .strftime("%Y-%m-%dT%H:%M:%SZ")
                )
            except ValueError:
                ts = record.timestamp
            action = record.change_type.value.upper()
            approver = record.approver or "unknown"
            files = ", ".join(record.changed_files[:3])
            if len(record.changed_files) > 3:
                files += f" (+{len(record.changed_files) - 3} more)"
            lines.append(f"- **{action}** by {approver} at {ts} — {files}")
            if record.reason:
                lines.append(f"  Reason: {record.reason}")

        return "\n".join(lines)
