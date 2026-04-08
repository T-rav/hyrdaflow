"""Local JSONL issue cache — append-only structured mirror of GitHub state.

HydraFlow treats GitHub as the primary system of record. This cache sits
alongside GitHub to give phases a fast, structured, versioned view of
every issue's lifecycle without re-parsing comments or re-fetching via
``gh`` on every cycle.

See issue #6422 for the full rationale. Key design points:

- **Append-only JSONL**: one file per issue at
  ``{cache_dir}/issues/{issue_id}.jsonl``. Every write is a new line;
  older records are never mutated. This makes restart rehydration and
  audit trails trivial.
- **Versioned plans and reviews**: ``plan_stored`` and ``review_stored``
  records include a ``version`` integer that increments per issue, so
  plan v1 → v2 history survives without overwriting comments.
- **Best-effort**: cache writes never raise into the domain layer. A
  broken cache cannot break the pipeline — failures log at warning.
- **Config-gated**: ``HydraFlowConfig.issue_cache_enabled`` defaults to
  True. Disabling returns HydraFlow to pre-cache behaviour exactly.

This module intentionally does NOT implement the full
``CachingIssueStore`` decorator from the issue scope — that is a
follow-up. This first slice lands the storage primitive and the first
set of record kinds so downstream phases and #6423 preconditions have
a real cache to write to and read from.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from file_util import append_jsonl

logger = logging.getLogger("hydraflow.issue_cache")

__all__ = [
    "CacheRecord",
    "CacheRecordKind",
    "IssueCache",
]


class CacheRecordKind(StrEnum):
    """Kind of snapshot captured in the cache."""

    # Raw GitHub state observed on a fetch cycle.
    FETCH = "fetch"
    # Triage classification — see #6422 amendment for structured classification.
    CLASSIFIED = "classified"
    # A comment was posted to GitHub by HydraFlow.
    COMMENT_POSTED = "comment_posted"
    # A HydraFlow pipeline label was added or removed.
    LABEL_CHANGE = "label_change"
    # A plan was produced by the planner (#6421 composes with this).
    PLAN_STORED = "plan_stored"
    # A plan or PR review was produced (#6421 composes with this).
    REVIEW_STORED = "review_stored"
    # An implementation run completed.
    IMPLEMENT_STORED = "implement_stored"
    # Triage-time reproduction of a bug (#6424 composes with this).
    REPRODUCTION_STORED = "reproduction_stored"
    # A pipeline stage routed the issue back upstream (#6423 composes with this).
    ROUTE_BACK = "route_back"


class CacheRecord(BaseModel):
    """A single append-only snapshot of issue state.

    Records are write-once. ``payload`` is deliberately loose — each
    record kind has its own shape, documented at the call site where it
    is created. Strict typing per kind is a follow-up refactor.
    """

    issue_id: int
    kind: CacheRecordKind
    ts: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO-8601 UTC timestamp of the snapshot.",
    )
    version: int = Field(
        default=0,
        description=(
            "Version counter within (issue_id, kind). Callers that care "
            "about history (plan_stored, review_stored) populate this; "
            "others leave it at 0."
        ),
    )
    payload: dict[str, Any] = Field(default_factory=dict)


class IssueCache:
    """Append-only JSONL store mirroring GitHub issue state.

    All write methods are best-effort. Read methods return ``None`` or
    empty lists when no matching record exists — they never raise on a
    missing file.
    """

    def __init__(self, cache_dir: Path, *, enabled: bool = True) -> None:
        self._cache_dir = cache_dir
        self._issues_dir = cache_dir / "issues"
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def issues_dir(self) -> Path:
        return self._issues_dir

    def _issue_path(self, issue_id: int) -> Path:
        return self._issues_dir / f"{issue_id}.jsonl"

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def record(self, record: CacheRecord) -> None:
        """Append *record* to the issue's JSONL file.

        Best-effort: on OSError, logs at warning level and returns. A
        broken cache must never break the domain layer.
        """
        if not self._enabled:
            return
        try:
            path = self._issue_path(record.issue_id)
            append_jsonl(path, record.model_dump_json())
        except OSError:
            logger.warning(
                "issue_cache: failed to append %s for issue #%d",
                record.kind,
                record.issue_id,
                exc_info=True,
            )

    def record_fetch(self, issue_id: int, payload: dict[str, Any]) -> None:
        self.record(
            CacheRecord(
                issue_id=issue_id,
                kind=CacheRecordKind.FETCH,
                payload=payload,
            )
        )

    def record_classification(
        self,
        issue_id: int,
        *,
        issue_type: str,
        complexity_score: float | int,
        complexity_rank: str,
        reasoning: str = "",
    ) -> None:
        """Record a triage classification (#6422 amendment).

        Downstream phases and the precondition gate (#6423) read this
        instead of regex-scraping triage comments.
        """
        self.record(
            CacheRecord(
                issue_id=issue_id,
                kind=CacheRecordKind.CLASSIFIED,
                payload={
                    "issue_type": issue_type,
                    "complexity_score": complexity_score,
                    "complexity_rank": complexity_rank,
                    "reasoning": reasoning,
                },
            )
        )

    def record_plan_stored(
        self,
        issue_id: int,
        *,
        plan_text: str,
        actionability_score: int | float = 0,
        findings: Iterable[dict[str, Any]] | None = None,
    ) -> int:
        """Record a plan snapshot with monotonic per-issue versioning.

        Returns the assigned version number (1-indexed). Version counts
        the number of prior ``plan_stored`` records for the same issue
        plus one — making plan v1 → v2 → v3 history readable from the
        JSONL stream without a separate index.
        """
        version = self._next_version(issue_id, CacheRecordKind.PLAN_STORED)
        self.record(
            CacheRecord(
                issue_id=issue_id,
                kind=CacheRecordKind.PLAN_STORED,
                version=version,
                payload={
                    "plan_text": plan_text,
                    "actionability_score": actionability_score,
                    "findings": list(findings or []),
                },
            )
        )
        return version

    def record_review_stored(
        self,
        issue_id: int,
        *,
        review_text: str,
        has_critical: bool,
        findings: Iterable[dict[str, Any]] | None = None,
    ) -> int:
        """Record an adversarial plan review or PR review (#6421 composes)."""
        version = self._next_version(issue_id, CacheRecordKind.REVIEW_STORED)
        self.record(
            CacheRecord(
                issue_id=issue_id,
                kind=CacheRecordKind.REVIEW_STORED,
                version=version,
                payload={
                    "review_text": review_text,
                    "has_critical": has_critical,
                    "findings": list(findings or []),
                },
            )
        )
        return version

    def record_reproduction_stored(
        self,
        issue_id: int,
        *,
        outcome: str,
        test_path: str = "",
        details: str = "",
    ) -> None:
        """Record a bug reproduction outcome from triage (#6424 composes)."""
        self.record(
            CacheRecord(
                issue_id=issue_id,
                kind=CacheRecordKind.REPRODUCTION_STORED,
                payload={
                    "outcome": outcome,
                    "test_path": test_path,
                    "details": details,
                },
            )
        )

    def record_route_back(
        self,
        issue_id: int,
        *,
        from_stage: str,
        to_stage: str,
        reason: str,
        feedback_context: str = "",
    ) -> None:
        """Record a stage route-back (#6423 composes)."""
        self.record(
            CacheRecord(
                issue_id=issue_id,
                kind=CacheRecordKind.ROUTE_BACK,
                payload={
                    "from_stage": from_stage,
                    "to_stage": to_stage,
                    "reason": reason,
                    "feedback_context": feedback_context,
                },
            )
        )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def read_history(self, issue_id: int) -> list[CacheRecord]:
        """Return every record for *issue_id* in write order.

        Empty list when the file does not exist or cannot be read.
        """
        path = self._issue_path(issue_id)
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            logger.warning(
                "issue_cache: failed to read history for issue #%d",
                issue_id,
                exc_info=True,
            )
            return []
        records: list[CacheRecord] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                records.append(CacheRecord.model_validate_json(line))
            except (json.JSONDecodeError, ValueError):
                logger.warning(
                    "issue_cache: skipping malformed record in #%d",
                    issue_id,
                )
        return records

    def latest_record_of_kind(
        self, issue_id: int, kind: CacheRecordKind
    ) -> CacheRecord | None:
        """Return the most recent record of *kind* for *issue_id*, or None."""
        history = self.read_history(issue_id)
        for record in reversed(history):
            if record.kind == kind:
                return record
        return None

    def latest_classification(self, issue_id: int) -> CacheRecord | None:
        return self.latest_record_of_kind(issue_id, CacheRecordKind.CLASSIFIED)

    def latest_plan(self, issue_id: int) -> CacheRecord | None:
        return self.latest_record_of_kind(issue_id, CacheRecordKind.PLAN_STORED)

    def latest_review(self, issue_id: int) -> CacheRecord | None:
        return self.latest_record_of_kind(issue_id, CacheRecordKind.REVIEW_STORED)

    def latest_reproduction(self, issue_id: int) -> CacheRecord | None:
        return self.latest_record_of_kind(issue_id, CacheRecordKind.REPRODUCTION_STORED)

    def _next_version(self, issue_id: int, kind: CacheRecordKind) -> int:
        """Return the next version counter for (issue_id, kind)."""
        latest = self.latest_record_of_kind(issue_id, kind)
        return (latest.version + 1) if latest else 1

    def known_issue_ids(self) -> list[int]:
        """Return every issue id that has at least one cache record."""
        if not self._issues_dir.exists():
            return []
        ids: list[int] = []
        for path in self._issues_dir.glob("*.jsonl"):
            try:
                ids.append(int(path.stem))
            except ValueError:
                continue
        return sorted(ids)
