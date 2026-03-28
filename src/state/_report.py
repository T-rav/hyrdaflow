"""Reports, metrics, manifest, memory, and baseline audit state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from models import (
    BaselineAuditRecord,
    BaselineChangeType,
    PendingReport,
    ReportHistoryEntry,
    TrackedReport,
)

if TYPE_CHECKING:
    from models import StateData


class ReportStateMixin:
    """Methods for pending/tracked reports, metrics, manifest, memory, and baseline audit."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    # --- pending reports queue ---

    def enqueue_report(self, report: PendingReport) -> None:
        """Append a report to the pending queue and persist."""
        self._data.pending_reports.append(report)
        self.save()

    def peek_report(self) -> PendingReport | None:
        """Return the first pending report without removing it, or None."""
        if not self._data.pending_reports:
            return None
        return self._data.pending_reports[0]

    def dequeue_report(self) -> PendingReport | None:
        """Pop the first pending report (FIFO) and persist, or return None."""
        if not self._data.pending_reports:
            return None
        report = self._data.pending_reports.pop(0)
        self.save()
        return report

    def remove_report(self, report_id: str) -> None:
        """Remove a report by ID and persist."""
        self._data.pending_reports = [
            r for r in self._data.pending_reports if r.id != report_id
        ]
        self.save()

    def fail_report(self, report_id: str) -> int:
        """Increment attempt count for a report. Returns the new count."""
        for r in self._data.pending_reports:
            if r.id == report_id:
                r.attempts += 1
                self.save()
                return r.attempts
        return 0

    def get_pending_reports(self) -> list[PendingReport]:
        """Return a copy of the pending reports list."""
        return list(self._data.pending_reports)

    # --- tracked reports ---

    def add_tracked_report(self, report: TrackedReport) -> None:
        """Add a tracked report and persist."""
        self._data.tracked_reports.append(report)
        self.save()

    def get_tracked_reports(
        self, reporter_id: str, *, status: str | None = None
    ) -> list[TrackedReport]:
        """Return tracked reports for a given reporter, optionally filtered by status."""
        reports = [
            r for r in self._data.tracked_reports if r.reporter_id == reporter_id
        ]
        if status:
            reports = [r for r in reports if r.status == status]
        return reports

    def get_tracked_report(self, report_id: str) -> TrackedReport | None:
        """Return a single tracked report by ID, or None."""
        for r in self._data.tracked_reports:
            if r.id == report_id:
                return r
        return None

    def update_tracked_report(
        self,
        report_id: str,
        *,
        status: Literal["queued", "in-progress", "filed", "fixed", "closed", "reopened"]
        | None = None,
        detail: str = "",
        action_label: str = "",
    ) -> TrackedReport | None:
        """Update a tracked report's status and append a history entry."""
        for r in self._data.tracked_reports:
            if r.id == report_id:
                if status:
                    r.status = status
                r.updated_at = datetime.now(UTC).isoformat()
                r.history.append(
                    ReportHistoryEntry(
                        action=action_label or status or "updated",
                        detail=detail,
                    )
                )
                self.save()
                return r
        return None

    def get_filed_reports(self) -> list[TrackedReport]:
        """Return all tracked reports with status ``'filed'``."""
        return [r for r in self._data.tracked_reports if r.status == "filed"]

    def get_stale_queued_reports(
        self, *, stale_minutes: int = 30
    ) -> list[TrackedReport]:
        """Return queued reports older than *stale_minutes*."""
        cutoff = datetime.now(UTC) - timedelta(minutes=stale_minutes)
        stale: list[TrackedReport] = []
        for r in self._data.tracked_reports:
            if r.status != "queued":
                continue
            try:
                created = datetime.fromisoformat(r.created_at)
            except (ValueError, TypeError):
                continue
            if created <= cutoff:
                stale.append(r)
        return stale

    # --- metrics state ---

    def get_metrics_state(self) -> tuple[str, str | None]:
        """Return ``(last_snapshot_hash, last_synced)``."""
        return (
            self._data.metrics_last_snapshot_hash,
            self._data.metrics_last_synced,
        )

    def update_metrics_state(self, snapshot_hash: str) -> None:
        """Update metrics tracking fields and persist."""
        self._data.metrics_last_snapshot_hash = snapshot_hash
        self._data.metrics_last_synced = datetime.now(UTC).isoformat()
        self.save()

    # --- manifest state ---

    def update_manifest_state(self, manifest_hash: str) -> None:
        """Update manifest tracking fields and persist."""
        self._data.manifest_hash = manifest_hash
        self._data.manifest_last_updated = datetime.now(UTC).isoformat()
        self.save()

    def get_manifest_state(self) -> tuple[str, str | None]:
        """Return ``(manifest_hash, last_updated)``."""
        return (
            self._data.manifest_hash,
            self._data.manifest_last_updated,
        )

    # --- memory state ---

    def update_memory_state(self, issue_ids: list[int], digest_hash: str) -> None:
        """Update memory tracking fields and persist."""
        self._data.memory_issue_ids = issue_ids
        self._data.memory_digest_hash = digest_hash
        self._data.memory_last_synced = datetime.now(UTC).isoformat()
        self.save()

    def get_memory_state(self) -> tuple[list[int], str, str | None]:
        """Return ``(issue_ids, digest_hash, last_synced)``."""
        return (
            list(self._data.memory_issue_ids),
            self._data.memory_digest_hash,
            self._data.memory_last_synced,
        )

    # --- Baseline audit trail ---

    _MAX_BASELINE_AUDIT_RECORDS = 100

    def record_baseline_change(
        self,
        issue_number: int,
        record: BaselineAuditRecord,
        max_records: int = 0,
    ) -> None:
        """Append a baseline audit record for *issue_number*.

        Caps at *max_records* (falls back to ``_MAX_BASELINE_AUDIT_RECORDS``).
        """
        cap = max_records or self._MAX_BASELINE_AUDIT_RECORDS
        key = self._key(issue_number)
        if key not in self._data.baseline_audit:
            self._data.baseline_audit[key] = []
        self._data.baseline_audit[key].append(record)
        if len(self._data.baseline_audit[key]) > cap:
            self._data.baseline_audit[key] = self._data.baseline_audit[key][-cap:]
        self.save()

    def get_baseline_audit(self, issue_number: int) -> list[BaselineAuditRecord]:
        """Return baseline audit records for *issue_number*."""
        return list(self._data.baseline_audit.get(self._key(issue_number), []))

    def get_latest_baseline_record(
        self, issue_number: int
    ) -> BaselineAuditRecord | None:
        """Return the most recent baseline audit record, or *None*."""
        records = self._data.baseline_audit.get(self._key(issue_number), [])
        return records[-1] if records else None

    def rollback_baseline(
        self,
        issue_number: int,
        pr_number: int,
        approver: str,
        reason: str,
        commit_sha: str = "",
    ) -> BaselineAuditRecord:
        """Record a baseline rollback for *issue_number*."""
        # Find the last non-rollback record to identify files
        records = self._data.baseline_audit.get(self._key(issue_number), [])
        changed_files: list[str] = []
        for record in reversed(records):
            if record.change_type != BaselineChangeType.ROLLBACK:
                changed_files = list(record.changed_files)
                break

        rollback_record = BaselineAuditRecord(
            pr_number=pr_number,
            issue_number=issue_number,
            changed_files=changed_files,
            change_type=BaselineChangeType.ROLLBACK,
            approver=approver,
            reason=reason,
            commit_sha=commit_sha,
        )
        self.record_baseline_change(issue_number, rollback_record)
        return rollback_record
