"""Issue, PR, outcome, hook-failure, verification, and crate state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from models import (
    HookFailureRecord,
    IssueOutcome,
    IssueOutcomeType,
    WorkerResultMeta,
)

if TYPE_CHECKING:
    from models import StateData


class IssueStateMixin:
    """Methods for issue tracking, attempts, outcomes, PRs, verification, hooks, and crates."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    # --- issue tracking ---

    def mark_issue(self, issue_number: int, status: str) -> None:
        """Record the processing status for *issue_number*."""
        self._data.processed_issues[self._key(issue_number)] = status
        self.save()

    # --- PR tracking ---

    def mark_pr(self, pr_number: int, status: str) -> None:
        """Record the review *status* for *pr_number*."""
        self._data.reviewed_prs[self._key(pr_number)] = status
        self.save()

    # --- issue attempt tracking ---

    def get_issue_attempts(self, issue_number: int) -> int:
        """Return the current implementation attempt count for *issue_number* (default 0)."""
        return self._data.issue_attempts.get(self._key(issue_number), 0)

    def increment_issue_attempts(self, issue_number: int) -> int:
        """Increment and return the new implementation attempt count for *issue_number*."""
        key = self._key(issue_number)
        current = self._data.issue_attempts.get(key, 0)
        self._data.issue_attempts[key] = current + 1
        self.save()
        return current + 1

    def reset_issue_attempts(self, issue_number: int) -> None:
        """Clear the implementation attempt counter for *issue_number*."""
        self._data.issue_attempts.pop(self._key(issue_number), None)
        self.save()

    # --- active issue numbers ---

    def get_active_issue_numbers(self) -> list[int]:
        """Return the persisted list of active issue numbers."""
        return list(self._data.active_issue_numbers)

    def set_active_issue_numbers(self, numbers: list[int]) -> None:
        """Persist the current set of active issue numbers."""
        self._data.active_issue_numbers = numbers
        self.save()

    # --- interrupted issues ---

    def set_interrupted_issues(self, mapping: dict[int, str]) -> None:
        """Persist interrupted issue → phase mapping (int keys stored as strings)."""
        self._data.interrupted_issues = {self._key(k): v for k, v in mapping.items()}
        self.save()

    def get_interrupted_issues(self) -> dict[int, str]:
        """Return interrupted issue mapping with int keys."""
        return {int(k): v for k, v in self._data.interrupted_issues.items()}

    def clear_interrupted_issues(self) -> None:
        """Clear the interrupted issues mapping and persist."""
        self._data.interrupted_issues = {}
        self.save()

    # --- worker result metadata ---

    def set_worker_result_meta(self, issue_number: int, meta: WorkerResultMeta) -> None:
        """Persist worker result metadata for *issue_number*."""
        self._data.worker_result_meta[self._key(issue_number)] = meta
        self.save()

    def get_worker_result_meta(self, issue_number: int) -> WorkerResultMeta:
        """Return worker result metadata for *issue_number*, or empty dict."""
        return self._data.worker_result_meta.get(self._key(issue_number), {})

    # --- verification issue tracking ---

    def set_verification_issue(
        self, original_issue: int, verification_issue: int
    ) -> None:
        """Record the verification issue number for *original_issue*."""
        self._data.verification_issues[self._key(original_issue)] = verification_issue
        self.save()

    def get_verification_issue(self, original_issue: int) -> int | None:
        """Return the verification issue number for *original_issue*, or *None*."""
        return self._data.verification_issues.get(self._key(original_issue))

    def clear_verification_issue(self, original_issue: int) -> None:
        """Remove the verification issue mapping for *original_issue*."""
        self._data.verification_issues.pop(self._key(original_issue), None)
        self.save()

    def get_all_verification_issues(self) -> dict[int, int]:
        """Return all pending verification issue mappings as {original: verify}."""
        return {int(k): v for k, v in self._data.verification_issues.items()}

    # --- issue outcome tracking ---

    def record_outcome(
        self,
        issue_number: int,
        outcome: IssueOutcomeType,
        reason: str,
        pr_number: int | None = None,
        phase: str = "",
        verification_issue_number: int | None = None,
    ) -> None:
        """Store an :class:`IssueOutcome` and increment the matching lifetime counter.

        If an outcome was already recorded for this issue, the previous
        counter is decremented before the new one is incremented so that
        aggregate stats stay consistent.
        """
        counter_map = {
            IssueOutcomeType.MERGED: "total_outcomes_merged",
            IssueOutcomeType.ALREADY_SATISFIED: "total_outcomes_already_satisfied",
            IssueOutcomeType.HITL_CLOSED: "total_outcomes_hitl_closed",
            IssueOutcomeType.HITL_SKIPPED: "total_outcomes_hitl_skipped",
            IssueOutcomeType.FAILED: "total_outcomes_failed",
            IssueOutcomeType.MANUAL_CLOSE: "total_outcomes_manual_close",
            IssueOutcomeType.HITL_APPROVED: "total_outcomes_hitl_approved",
            IssueOutcomeType.VERIFY_PENDING: "total_outcomes_verify_pending",
            IssueOutcomeType.VERIFY_RESOLVED: "total_outcomes_verify_resolved",
        }

        key = self._key(issue_number)
        previous = self._data.issue_outcomes.get(key)
        if previous is not None:
            old_attr = counter_map.get(previous.outcome)
            if old_attr:
                cur = getattr(self._data.lifetime_stats, old_attr)
                setattr(self._data.lifetime_stats, old_attr, max(cur - 1, 0))

        self._data.issue_outcomes[key] = IssueOutcome(
            outcome=outcome,
            reason=reason,
            closed_at=datetime.now(UTC).isoformat(),
            pr_number=pr_number,
            phase=phase,
            verification_issue_number=verification_issue_number,
        )
        attr = counter_map.get(outcome)
        if attr:
            setattr(
                self._data.lifetime_stats,
                attr,
                getattr(self._data.lifetime_stats, attr) + 1,
            )
        self.save()

    def get_outcome(self, issue_number: int) -> IssueOutcome | None:
        """Return the recorded outcome for *issue_number*, or ``None``."""
        return self._data.issue_outcomes.get(self._key(issue_number))

    def get_all_outcomes(self) -> dict[str, IssueOutcome]:
        """Return all recorded issue outcomes (deep copy)."""
        return {
            k: v.model_copy(deep=True) for k, v in self._data.issue_outcomes.items()
        }

    # --- hook failure tracking ---

    _MAX_HOOK_FAILURES = 500

    def record_hook_failure(
        self, issue_number: int, hook_name: str, error: str
    ) -> None:
        """Append a :class:`HookFailureRecord` for *issue_number*."""
        key = self._key(issue_number)
        if key not in self._data.hook_failures:
            self._data.hook_failures[key] = []
        self._data.hook_failures[key].append(
            HookFailureRecord(
                hook_name=hook_name,
                error=error[:500],
                timestamp=datetime.now(UTC).isoformat(),
            )
        )
        # Cap at _MAX_HOOK_FAILURES per issue, trimming oldest
        if len(self._data.hook_failures[key]) > self._MAX_HOOK_FAILURES:
            self._data.hook_failures[key] = self._data.hook_failures[key][
                -self._MAX_HOOK_FAILURES :
            ]
        self.save()

    def get_hook_failures(self, issue_number: int) -> list[HookFailureRecord]:
        """Return hook failure records for *issue_number* (deep copy)."""
        return [
            f.model_copy(deep=True)
            for f in self._data.hook_failures.get(self._key(issue_number), [])
        ]

    # --- active crate ---

    def get_active_crate_number(self) -> int | None:
        """Return the persisted active crate (milestone) number, or None."""
        return self._data.active_crate_number

    def set_active_crate_number(self, number: int | None) -> None:
        """Persist the active crate number (or clear it with None)."""
        self._data.active_crate_number = number
        self.save()

    # --- bead mappings ---

    def set_bead_mapping(self, issue_id: int, mapping: dict[str, str]) -> None:
        """Persist the phase→bead ID mapping for *issue_id*."""
        self._data.bead_mappings[self._key(issue_id)] = mapping
        self.save()

    def get_bead_mapping(self, issue_id: int) -> dict[str, str]:
        """Return the phase→bead ID mapping for *issue_id*, or empty dict."""
        return self._data.bead_mappings.get(self._key(issue_id), {})
