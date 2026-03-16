"""HITL (human-in-the-loop) state: origin, cause, summary, visual evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from models import HITLSummaryCacheEntry, HITLSummaryFailureEntry, VisualEvidence

if TYPE_CHECKING:
    from models import StateData


class HITLStateMixin:
    """Methods for HITL origin, cause, summary cache, and visual evidence."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    # --- HITL origin tracking ---

    def set_hitl_origin(self, issue_number: int, label: str) -> None:
        """Record the label that was active before HITL escalation."""
        self._data.hitl_origins[self._key(issue_number)] = label
        self.save()

    def get_hitl_origin(self, issue_number: int) -> str | None:
        """Return the pre-HITL label for *issue_number*, or *None*."""
        return self._data.hitl_origins.get(self._key(issue_number))

    def remove_hitl_origin(self, issue_number: int) -> None:
        """Clear the HITL origin record for *issue_number*."""
        self._data.hitl_origins.pop(self._key(issue_number), None)
        self.save()

    # --- HITL cause tracking ---

    def set_hitl_cause(self, issue_number: int, cause: str) -> None:
        """Record the escalation reason for *issue_number*."""
        self._data.hitl_causes[self._key(issue_number)] = cause
        self.save()

    def get_hitl_cause(self, issue_number: int) -> str | None:
        """Return the escalation reason for *issue_number*, or *None*."""
        return self._data.hitl_causes.get(self._key(issue_number))

    def remove_hitl_cause(self, issue_number: int) -> None:
        """Clear the escalation reason for *issue_number*."""
        self._data.hitl_causes.pop(self._key(issue_number), None)
        self.save()

    # --- HITL summary cache ---

    def set_hitl_summary(self, issue_number: int, summary: str) -> None:
        """Persist cached LLM summary text for *issue_number*."""
        key = self._key(issue_number)
        self._data.hitl_summaries[key] = HITLSummaryCacheEntry(
            summary=summary,
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._data.hitl_summary_failures.pop(key, None)
        self.save()

    def get_hitl_summary(self, issue_number: int) -> str | None:
        """Return cached summary for *issue_number*, or ``None`` if absent."""
        entry = self._data.hitl_summaries.get(self._key(issue_number))
        if not entry:
            return None
        summary = str(getattr(entry, "summary", "")).strip()
        return summary or None

    def get_hitl_summary_updated_at(self, issue_number: int) -> str | None:
        """Return cached summary update timestamp for *issue_number*."""
        entry = self._data.hitl_summaries.get(self._key(issue_number))
        if not entry:
            return None
        updated = getattr(entry, "updated_at", None)
        return updated if isinstance(updated, str) and updated else None

    def remove_hitl_summary(self, issue_number: int) -> None:
        """Delete cached summary for *issue_number*."""
        key = self._key(issue_number)
        self._data.hitl_summaries.pop(key, None)
        self._data.hitl_summary_failures.pop(key, None)
        self.save()

    def set_hitl_summary_failure(self, issue_number: int, error: str) -> None:
        """Persist failure metadata for summary generation attempts."""
        self._data.hitl_summary_failures[self._key(issue_number)] = (
            HITLSummaryFailureEntry(
                last_failed_at=datetime.now(UTC).isoformat(),
                error=error[:300],
            )
        )
        self.save()

    def get_hitl_summary_failure(self, issue_number: int) -> tuple[str | None, str]:
        """Return ``(last_failed_at, error)`` for summary generation failures."""
        entry = self._data.hitl_summary_failures.get(self._key(issue_number))
        if not entry:
            return None, ""
        return getattr(entry, "last_failed_at", None), getattr(entry, "error", "")

    def clear_hitl_summary_failure(self, issue_number: int) -> None:
        """Clear summary-generation failure metadata for *issue_number*."""
        self._data.hitl_summary_failures.pop(self._key(issue_number), None)
        self.save()

    # --- HITL visual evidence ---

    def set_hitl_visual_evidence(
        self, issue_number: int, evidence: VisualEvidence
    ) -> None:
        """Persist visual validation evidence for *issue_number*."""
        self._data.hitl_visual_evidence[self._key(issue_number)] = evidence
        self.save()

    def get_hitl_visual_evidence(self, issue_number: int) -> VisualEvidence | None:
        """Return visual evidence for *issue_number*, or ``None``."""
        return self._data.hitl_visual_evidence.get(self._key(issue_number))

    def remove_hitl_visual_evidence(self, issue_number: int) -> None:
        """Clear visual evidence for *issue_number*."""
        self._data.hitl_visual_evidence.pop(self._key(issue_number), None)
        self.save()
