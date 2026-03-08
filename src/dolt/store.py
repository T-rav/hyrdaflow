"""Dolt-backed drop-in replacement for StateTracker.

Composes all repository classes and exposes the same public API
as :class:`state.StateTracker`, delegating each call to the
appropriate Dolt-backed repository.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dolt.config_state import (
    ManifestStateRepository,
    MemoryStateRepository,
    MetricsStateRepository,
)
from dolt.connection import DoltConnection
from dolt.insights import (
    CuratedManifestRepository,
    HarnessFailureRepository,
    RetrospectiveRepository,
    ReviewRecordRepository,
)
from dolt.issues import BaselineAuditRepository, IssueRepository, PRRepository
from dolt.learnings import LearningRepository
from dolt.lifetime import (
    ActiveCrateRepository,
    LifetimeStatsRepository,
    SessionCounterRepository,
)
from dolt.persistence import (
    ContextCacheRepository,
    EventRepository,
    MetricsSnapshotRepository,
    RunRepository,
    SessionRepository,
)
from dolt.pipeline import (
    ActiveIssueRepository,
    EpicRepository,
    ReleaseRepository,
    ReportRepository,
)
from dolt.telemetry import InferenceRepository, ModelPricingRepository
from dolt.troubleshooting import TroubleshootingPatternRepository
from dolt.workers import WorkerRepository
from models import LifetimeStats

logger = logging.getLogger("hydraflow.dolt.store")


class DoltStore:
    """Facade that mirrors every public method of :class:`StateTracker`.

    Internally delegates to Dolt tables via :class:`DoltConnection` and
    the various repository classes.  Designed as a drop-in replacement
    for :class:`StateTracker`.
    """

    # Session counter field names (mirrors StateTracker._SESSION_COUNTER_FIELDS)
    _SESSION_COUNTER_FIELDS = frozenset(
        {"triaged", "planned", "implemented", "reviewed", "merged"}
    )
    _MAX_HOOK_FAILURES = 500
    _MAX_BASELINE_AUDIT_RECORDS = 100

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, dolt_dir: Path, *, port: int = 3307) -> None:
        # Accept .json file paths for backward compat
        if isinstance(dolt_dir, str):
            dolt_dir = Path(dolt_dir)
        if dolt_dir.suffix == ".json":
            dolt_dir = dolt_dir.parent / "_dolt"

        self._dolt_dir = dolt_dir
        self.db = DoltConnection(dolt_dir, port=port)
        self.db.start()

        # --- Repository instances ---
        # Issue / PR tracking
        self.issues = IssueRepository(self.db)
        self.prs = PRRepository(self.db)
        self.baseline_audit = BaselineAuditRepository(self.db)

        # Lifetime / session / crate singletons
        self._lifetime = LifetimeStatsRepository(self.db)
        self._session_ctr = SessionCounterRepository(self.db)
        self._active_crate = ActiveCrateRepository(self.db)

        # Workers
        self._workers = WorkerRepository(self.db)

        # Events, runs, sessions, cache, metrics
        self._events = EventRepository(self.db)
        self._runs = RunRepository(self.db)
        self._sessions = SessionRepository(self.db)
        self._context_cache = ContextCacheRepository(self.db)
        self._metrics_snap = MetricsSnapshotRepository(self.db)

        # Insights
        self._review_records = ReviewRecordRepository(self.db)
        self._harness_failures = HarnessFailureRepository(self.db)
        self._retrospectives = RetrospectiveRepository(self.db)
        self._curated_manifest = CuratedManifestRepository(self.db)

        # Telemetry
        self._inferences = InferenceRepository(self.db)
        self._model_pricing = ModelPricingRepository(self.db)

        # Pipeline
        self._active_issues = ActiveIssueRepository(self.db)
        self._epics = EpicRepository(self.db)
        self._releases = ReleaseRepository(self.db)
        self._reports = ReportRepository(self.db)

        # Config state singletons
        self._memory_state = MemoryStateRepository(self.db)
        self._manifest_state = ManifestStateRepository(self.db)
        self._metrics_state = MetricsStateRepository(self.db)

        # Learnings & troubleshooting
        self._learnings = LearningRepository(self.db)
        self._troubleshooting = TroubleshootingPatternRepository(self.db)

    def close(self) -> None:
        """Shut down the Dolt server and close the connection."""
        self.db.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _json_loads(raw: str | None) -> Any:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _normalise_details(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return dict(raw)
        if raw in (None, "", []):
            return {}
        return {"raw": raw}

    @staticmethod
    def _coerce_last_run(value: Any) -> str | None:
        if value is None or isinstance(value, str):
            return value
        return str(value)

    def _to_dict(self, obj: Any) -> dict[str, Any]:
        """Convert a model or dict to plain dict."""
        if isinstance(obj, dict):
            return dict(obj)
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return dict(obj)

    # ------------------------------------------------------------------
    # Persistence (StateTracker compat)
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Return current state as a dict (delegates to to_dict)."""
        return self.to_dict()

    def save(self) -> None:
        """No-op -- Dolt auto-persists via autocommit."""

    # ------------------------------------------------------------------
    # Issue tracking
    # ------------------------------------------------------------------

    def mark_issue(self, issue_number: int, status: str) -> None:
        """Record the processing status for *issue_number*."""
        self.issues.set_field(issue_number, "_status", status)

    # ------------------------------------------------------------------
    # Worktree tracking
    # ------------------------------------------------------------------

    def get_active_worktrees(self) -> dict[int, str]:
        """Return ``{issue_number: worktree_path}`` mapping."""
        all_issues = self.issues.get_all_issues()
        result: dict[int, str] = {}
        for inum, fields in all_issues.items():
            wt = fields.get("_worktree")
            if wt:
                result[inum] = wt
        return result

    def set_worktree(self, issue_number: int, path: str) -> None:
        """Record the worktree filesystem *path* for *issue_number*."""
        self.issues.set_field(issue_number, "_worktree", path)

    def remove_worktree(self, issue_number: int) -> None:
        """Remove the worktree mapping for *issue_number* (no-op if absent)."""
        self.issues.remove_field(issue_number, "_worktree")

    # ------------------------------------------------------------------
    # Branch tracking
    # ------------------------------------------------------------------

    def set_branch(self, issue_number: int, branch: str) -> None:
        """Record the active *branch* name for *issue_number*."""
        self.issues.set_field(issue_number, "_branch", branch)

    def get_branch(self, issue_number: int) -> str | None:
        """Return the active branch for *issue_number*, or *None*."""
        return self.issues.get_field(issue_number, "_branch")

    # ------------------------------------------------------------------
    # PR tracking
    # ------------------------------------------------------------------

    def mark_pr(self, pr_number: int, status: str) -> None:
        """Record the review *status* for *pr_number*."""
        self.prs.mark(pr_number, status)

    # ------------------------------------------------------------------
    # HITL origin tracking
    # ------------------------------------------------------------------

    def set_hitl_origin(self, issue_number: int, label: str) -> None:
        """Record the label that was active before HITL escalation."""
        self.issues.set_field(issue_number, "_hitl_origin", label)

    def get_hitl_origin(self, issue_number: int) -> str | None:
        """Return the pre-HITL label for *issue_number*, or *None*."""
        return self.issues.get_field(issue_number, "_hitl_origin")

    def remove_hitl_origin(self, issue_number: int) -> None:
        """Clear the HITL origin record for *issue_number*."""
        self.issues.remove_field(issue_number, "_hitl_origin")

    # ------------------------------------------------------------------
    # HITL cause tracking
    # ------------------------------------------------------------------

    def set_hitl_cause(self, issue_number: int, cause: str) -> None:
        """Record the escalation reason for *issue_number*."""
        self.issues.set_field(issue_number, "_hitl_cause", cause)

    def get_hitl_cause(self, issue_number: int) -> str | None:
        """Return the escalation reason for *issue_number*, or *None*."""
        return self.issues.get_field(issue_number, "_hitl_cause")

    def remove_hitl_cause(self, issue_number: int) -> None:
        """Clear the escalation reason for *issue_number*."""
        self.issues.remove_field(issue_number, "_hitl_cause")

    # ------------------------------------------------------------------
    # HITL summary cache
    # ------------------------------------------------------------------

    def set_hitl_summary(self, issue_number: int, summary: str) -> None:
        """Persist cached LLM summary text for *issue_number*."""
        data = json.dumps({"summary": summary, "updated_at": self._now_iso()})
        self.issues.set_field(issue_number, "_hitl_summary", data)
        self.issues.remove_field(issue_number, "_hitl_summary_failure")

    def get_hitl_summary(self, issue_number: int) -> str | None:
        """Return cached summary for *issue_number*, or ``None`` if absent."""
        raw = self.issues.get_field(issue_number, "_hitl_summary")
        if not raw:
            return None
        entry = self._json_loads(raw)
        if not entry:
            return None
        summary = str(entry.get("summary", "")).strip()
        return summary or None

    def get_hitl_summary_updated_at(self, issue_number: int) -> str | None:
        """Return cached summary update timestamp for *issue_number*."""
        raw = self.issues.get_field(issue_number, "_hitl_summary")
        if not raw:
            return None
        entry = self._json_loads(raw)
        if not entry:
            return None
        updated = entry.get("updated_at")
        return updated if isinstance(updated, str) and updated else None

    def remove_hitl_summary(self, issue_number: int) -> None:
        """Delete cached summary for *issue_number*."""
        self.issues.remove_field(issue_number, "_hitl_summary")
        self.issues.remove_field(issue_number, "_hitl_summary_failure")

    def set_hitl_summary_failure(self, issue_number: int, error: str) -> None:
        """Persist failure metadata for summary generation attempts."""
        data = json.dumps({
            "last_failed_at": self._now_iso(),
            "error": error[:300],
        })
        self.issues.set_field(issue_number, "_hitl_summary_failure", data)

    def get_hitl_summary_failure(self, issue_number: int) -> tuple[str | None, str]:
        """Return ``(last_failed_at, error)`` for summary generation failures."""
        raw = self.issues.get_field(issue_number, "_hitl_summary_failure")
        if not raw:
            return None, ""
        entry = self._json_loads(raw)
        if not entry:
            return None, ""
        return entry.get("last_failed_at"), entry.get("error", "")

    def clear_hitl_summary_failure(self, issue_number: int) -> None:
        """Clear summary-generation failure metadata for *issue_number*."""
        self.issues.remove_field(issue_number, "_hitl_summary_failure")

    # ------------------------------------------------------------------
    # HITL visual evidence
    # ------------------------------------------------------------------

    def set_hitl_visual_evidence(self, issue_number: int, evidence: Any) -> None:
        """Persist visual validation evidence for *issue_number*."""
        data = json.dumps(self._to_dict(evidence))
        self.issues.set_field(issue_number, "_hitl_visual_evidence", data)

    def get_hitl_visual_evidence(self, issue_number: int) -> Any | None:
        """Return visual evidence for *issue_number*, or ``None``."""
        raw = self.issues.get_field(issue_number, "_hitl_visual_evidence")
        return self._json_loads(raw) if raw else None

    def remove_hitl_visual_evidence(self, issue_number: int) -> None:
        """Clear visual evidence for *issue_number*."""
        self.issues.remove_field(issue_number, "_hitl_visual_evidence")

    # ------------------------------------------------------------------
    # Review attempt tracking
    # ------------------------------------------------------------------

    def get_review_attempts(self, issue_number: int) -> int:
        """Return the current review attempt count for *issue_number* (default 0)."""
        raw = self.issues.get_field(issue_number, "_review_attempts")
        return int(raw) if raw else 0

    def increment_review_attempts(self, issue_number: int) -> int:
        """Increment and return the new review attempt count."""
        current = self.get_review_attempts(issue_number)
        new_val = current + 1
        self.issues.set_field(issue_number, "_review_attempts", str(new_val))
        return new_val

    def reset_review_attempts(self, issue_number: int) -> None:
        """Clear the review attempt counter for *issue_number*."""
        self.issues.remove_field(issue_number, "_review_attempts")

    # ------------------------------------------------------------------
    # Review feedback storage
    # ------------------------------------------------------------------

    def set_review_feedback(self, issue_number: int, feedback: str) -> None:
        """Store review feedback for *issue_number*."""
        self.issues.set_field(issue_number, "_review_feedback", feedback)

    def get_review_feedback(self, issue_number: int) -> str | None:
        """Return stored review feedback for *issue_number*, or *None*."""
        return self.issues.get_field(issue_number, "_review_feedback")

    def clear_review_feedback(self, issue_number: int) -> None:
        """Clear stored review feedback for *issue_number*."""
        self.issues.remove_field(issue_number, "_review_feedback")

    # ------------------------------------------------------------------
    # Verification issue tracking
    # ------------------------------------------------------------------

    def set_verification_issue(
        self, original_issue: int, verification_issue: int
    ) -> None:
        """Record the verification issue number for *original_issue*."""
        self.issues.set_field(
            original_issue, "_verification_issue", str(verification_issue)
        )

    def get_verification_issue(self, original_issue: int) -> int | None:
        """Return the verification issue number for *original_issue*, or *None*."""
        raw = self.issues.get_field(original_issue, "_verification_issue")
        return int(raw) if raw else None

    # ------------------------------------------------------------------
    # Issue attempt tracking
    # ------------------------------------------------------------------

    def get_issue_attempts(self, issue_number: int) -> int:
        """Return the current implementation attempt count (default 0)."""
        raw = self.issues.get_field(issue_number, "_issue_attempts")
        return int(raw) if raw else 0

    def increment_issue_attempts(self, issue_number: int) -> int:
        """Increment and return the new implementation attempt count."""
        current = self.get_issue_attempts(issue_number)
        new_val = current + 1
        self.issues.set_field(issue_number, "_issue_attempts", str(new_val))
        return new_val

    def reset_issue_attempts(self, issue_number: int) -> None:
        """Clear the implementation attempt counter for *issue_number*."""
        self.issues.remove_field(issue_number, "_issue_attempts")

    # ------------------------------------------------------------------
    # Active issue numbers
    # ------------------------------------------------------------------

    def get_active_issue_numbers(self) -> list[int]:
        """Return the persisted list of active issue numbers."""
        return self._active_issues.get_all()

    def set_active_issue_numbers(self, numbers: list[int]) -> None:
        """Persist the current set of active issue numbers."""
        self.db.execute("DELETE FROM active_issues")
        for n in numbers:
            self._active_issues.add(n)

    # ------------------------------------------------------------------
    # Interrupted issues
    # ------------------------------------------------------------------

    def set_interrupted_issues(self, mapping: dict[int, str]) -> None:
        """Persist interrupted issue -> phase mapping."""
        self.issues.set_field(
            0, "_interrupted_issues",
            json.dumps({str(k): v for k, v in mapping.items()}),
        )

    def get_interrupted_issues(self) -> dict[int, str]:
        """Return interrupted issue mapping with int keys."""
        raw = self.issues.get_field(0, "_interrupted_issues")
        if not raw:
            return {}
        data = self._json_loads(raw)
        return {int(k): v for k, v in (data or {}).items()}

    def clear_interrupted_issues(self) -> None:
        """Clear the interrupted issues mapping and persist."""
        self.issues.remove_field(0, "_interrupted_issues")

    # ------------------------------------------------------------------
    # Last reviewed SHA tracking
    # ------------------------------------------------------------------

    def set_last_reviewed_sha(self, issue_number: int, sha: str) -> None:
        """Record the last-reviewed commit SHA for *issue_number*."""
        self.issues.set_field(issue_number, "_last_reviewed_sha", sha)

    def get_last_reviewed_sha(self, issue_number: int) -> str | None:
        """Return the last-reviewed commit SHA for *issue_number*, or *None*."""
        return self.issues.get_field(issue_number, "_last_reviewed_sha")

    def clear_last_reviewed_sha(self, issue_number: int) -> None:
        """Clear the last-reviewed commit SHA for *issue_number*."""
        self.issues.remove_field(issue_number, "_last_reviewed_sha")

    # ------------------------------------------------------------------
    # Worker result metadata
    # ------------------------------------------------------------------

    def set_worker_result_meta(self, issue_number: int, meta: Any) -> None:
        """Persist worker result metadata for *issue_number*."""
        data = json.dumps(self._to_dict(meta))
        self.issues.set_field(issue_number, "_worker_result_meta", data)

    def get_worker_result_meta(self, issue_number: int) -> dict[str, Any]:
        """Return worker result metadata for *issue_number*, or empty dict."""
        raw = self.issues.get_field(issue_number, "_worker_result_meta")
        return self._json_loads(raw) or {}

    # ------------------------------------------------------------------
    # Issue outcome tracking
    # ------------------------------------------------------------------

    _OUTCOME_COUNTER_MAP = {
        "merged": "total_outcomes_merged",
        "already_satisfied": "total_outcomes_already_satisfied",
        "hitl_closed": "total_outcomes_hitl_closed",
        "hitl_skipped": "total_outcomes_hitl_skipped",
        "failed": "total_outcomes_failed",
        "manual_close": "total_outcomes_manual_close",
        "hitl_approved": "total_outcomes_hitl_approved",
    }

    def record_outcome(
        self,
        issue_number: int,
        outcome: Any,
        reason: str,
        pr_number: int | None = None,
        phase: str = "",
    ) -> None:
        """Store an IssueOutcome and update lifetime counters."""
        # Decrement previous outcome counter if exists
        prev_raw = self.issues.get_field(issue_number, "_outcome")
        if prev_raw:
            prev = self._json_loads(prev_raw)
            if prev:
                old_attr = self._OUTCOME_COUNTER_MAP.get(prev.get("outcome"))
                if old_attr:
                    self._increment_lifetime_stat(old_attr, -1, floor_zero=True)

        outcome_str = str(outcome.value) if hasattr(outcome, "value") else str(outcome)
        data = json.dumps({
            "outcome": outcome_str,
            "reason": reason,
            "closed_at": self._now_iso(),
            "pr_number": pr_number,
            "phase": phase,
        })
        self.issues.set_field(issue_number, "_outcome", data)

        counter_attr = self._OUTCOME_COUNTER_MAP.get(outcome_str)
        if counter_attr:
            self._increment_lifetime_stat(counter_attr, 1)

    def get_outcome(self, issue_number: int) -> Any | None:
        """Return the recorded outcome for *issue_number*, or ``None``."""
        raw = self.issues.get_field(issue_number, "_outcome")
        return self._json_loads(raw) if raw else None

    def get_all_outcomes(self) -> dict[str, Any]:
        """Return all recorded issue outcomes."""
        all_issues = self.issues.get_all_issues()
        result: dict[str, Any] = {}
        for inum, fields in all_issues.items():
            raw = fields.get("_outcome")
            if raw:
                parsed = self._json_loads(raw)
                if parsed:
                    result[str(inum)] = parsed
        return result

    # ------------------------------------------------------------------
    # Hook failure tracking
    # ------------------------------------------------------------------

    def record_hook_failure(
        self, issue_number: int, hook_name: str, error: str
    ) -> None:
        """Append a HookFailureRecord for *issue_number*."""
        existing = self._get_hook_failures_raw(issue_number)
        existing.append({
            "hook_name": hook_name,
            "error": error[:500],
            "timestamp": self._now_iso(),
        })
        if len(existing) > self._MAX_HOOK_FAILURES:
            existing = existing[-self._MAX_HOOK_FAILURES:]
        self.issues.set_field(issue_number, "_hook_failures", json.dumps(existing))

    def get_hook_failures(self, issue_number: int) -> list[Any]:
        """Return hook failure records for *issue_number*."""
        return self._get_hook_failures_raw(issue_number)

    def _get_hook_failures_raw(self, issue_number: int) -> list[dict[str, Any]]:
        raw = self.issues.get_field(issue_number, "_hook_failures")
        if not raw:
            return []
        return self._json_loads(raw) or []

    # ------------------------------------------------------------------
    # Epic state tracking
    # ------------------------------------------------------------------

    def get_epic_state(self, epic_number: int) -> Any | None:
        """Return the persisted state for *epic_number*, or ``None``."""
        return self._epics.get(str(epic_number))

    def upsert_epic_state(self, state: Any) -> None:
        """Create or update the persisted state for an epic."""
        data = self._to_dict(state)
        epic_number = data.get("epic_number")
        self._epics.upsert(str(epic_number), data)

    def mark_epic_child_complete(self, epic_number: int, child_number: int) -> None:
        """Move *child_number* to completed_children for *epic_number*."""
        epic = self.get_epic_state(epic_number)
        if epic is None:
            return
        completed = epic.get("completed_children", [])
        if child_number not in completed:
            completed.append(child_number)
            epic["completed_children"] = completed
        failed = epic.get("failed_children", [])
        if child_number in failed:
            failed.remove(child_number)
            epic["failed_children"] = failed
        epic["last_activity"] = self._now_iso()
        self._epics.upsert(str(epic_number), epic)

    def mark_epic_child_failed(self, epic_number: int, child_number: int) -> None:
        """Move *child_number* to failed_children for *epic_number*."""
        epic = self.get_epic_state(epic_number)
        if epic is None:
            return
        failed = epic.get("failed_children", [])
        if child_number not in failed:
            failed.append(child_number)
            epic["failed_children"] = failed
        epic["last_activity"] = self._now_iso()
        self._epics.upsert(str(epic_number), epic)

    def mark_epic_child_approved(self, epic_number: int, child_number: int) -> None:
        """Add *child_number* to approved_children for *epic_number*."""
        epic = self.get_epic_state(epic_number)
        if epic is None:
            return
        approved = epic.get("approved_children", [])
        if child_number not in approved:
            approved.append(child_number)
            epic["approved_children"] = approved
        epic["last_activity"] = self._now_iso()
        self._epics.upsert(str(epic_number), epic)

    def get_epic_progress(self, epic_number: int) -> dict[str, object]:
        """Return epic progress summary for *epic_number*."""
        epic = self.get_epic_state(epic_number)
        if epic is None:
            return {}
        child_issues = epic.get("child_issues", [])
        completed_children = epic.get("completed_children", [])
        failed_children = epic.get("failed_children", [])
        approved_children = epic.get("approved_children", [])
        merge_strategy = epic.get("merge_strategy", "independent")
        total = len(child_issues)
        merged = len(completed_children)
        failed = len(failed_children)
        approved = len(approved_children)
        in_progress = total - merged - failed
        pending = total - merged - failed - approved
        ready = (
            total > 0
            and failed == 0
            and merge_strategy != "independent"
            and all(
                c in approved_children or c in completed_children
                for c in child_issues
            )
        )
        return {
            "total": total,
            "merged": merged,
            "in_progress": max(in_progress, 0),
            "pending": max(pending, 0),
            "approved": approved,
            "ready_to_merge": ready,
            "merge_strategy": merge_strategy,
        }

    def get_all_epic_states(self) -> dict[str, Any]:
        """Return all persisted epic states."""
        return self._epics.get_all()

    def close_epic(self, epic_number: int) -> None:
        """Mark an epic as closed."""
        epic = self.get_epic_state(epic_number)
        if epic is None:
            return
        epic["closed"] = True
        epic["last_activity"] = self._now_iso()
        self._epics.upsert(str(epic_number), epic)

    # ------------------------------------------------------------------
    # Release tracking
    # ------------------------------------------------------------------

    def upsert_release(self, release: Any) -> None:
        """Create or update a release record, keyed by epic number."""
        data = self._to_dict(release)
        release_id = str(data.get("epic_number", data.get("release_id", "")))
        self._releases.create(release_id, data)

    def get_release(self, epic_number: int) -> Any | None:
        """Return the release for *epic_number*, or ``None``."""
        return self._releases.get(str(epic_number))

    def get_all_releases(self) -> dict[str, Any]:
        """Return all persisted releases."""
        all_releases = self._releases.get_all()
        return {r["release_id"]: r for r in all_releases}

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all state. Lifetime stats are preserved."""
        saved_lifetime = self._lifetime.get_all()
        # Clear key tables
        for table in (
            "issues", "prs", "active_issues", "bg_workers", "events",
            "sessions", "epic_states", "releases", "pending_reports",
            "review_records", "harness_failures", "retrospectives",
        ):
            self.db.execute(f"DELETE FROM {table}")  # noqa: S608
        # Reset session counters
        self._session_ctr.update(
            triaged=0, planned=0, implemented=0,
            reviewed=0, merged=0, session_start="",
        )
        # Reset singleton states
        self._active_crate.update(crate_number=None)
        self._memory_state.update(issue_ids=None, digest_hash=None, last_synced=None)
        self._manifest_state.update(
            hash=None, last_updated=None, issue_number=None, snapshot_hash=None,
        )
        self._metrics_state.update(
            issue_number=None, last_snapshot_hash=None, last_synced=None,
        )
        # Restore lifetime stats
        if saved_lifetime:
            saved_lifetime.pop("id", None)
            self._lifetime.update(**saved_lifetime)

    # ------------------------------------------------------------------
    # to_dict -- same structure as StateTracker.to_dict()
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of the raw state dict."""
        all_issues = self.issues.get_all_issues()

        # Reconstruct per-issue fields stored in the issues KV table
        processed_issues: dict[str, str] = {}
        active_worktrees: dict[str, str] = {}
        active_branches: dict[str, str] = {}
        hitl_origins: dict[str, str] = {}
        hitl_causes: dict[str, str] = {}
        hitl_summaries: dict[str, Any] = {}
        hitl_summary_failures: dict[str, Any] = {}
        hitl_visual_evidence: dict[str, Any] = {}
        review_attempts: dict[str, int] = {}
        review_feedback: dict[str, str] = {}
        worker_result_meta: dict[str, Any] = {}
        verification_issues: dict[str, int] = {}
        issue_attempts: dict[str, int] = {}
        last_reviewed_shas: dict[str, str] = {}
        issue_outcomes: dict[str, Any] = {}
        hook_failures: dict[str, list[Any]] = {}

        for inum, fields in all_issues.items():
            key = str(inum)
            if inum == 0:
                continue  # sentinel row for interrupted_issues
            if "_status" in fields:
                processed_issues[key] = fields["_status"]
            if "_worktree" in fields:
                active_worktrees[key] = fields["_worktree"]
            if "_branch" in fields:
                active_branches[key] = fields["_branch"]
            if "_hitl_origin" in fields:
                hitl_origins[key] = fields["_hitl_origin"]
            if "_hitl_cause" in fields:
                hitl_causes[key] = fields["_hitl_cause"]
            if "_hitl_summary" in fields:
                hitl_summaries[key] = self._json_loads(fields["_hitl_summary"]) or {}
            if "_hitl_summary_failure" in fields:
                hitl_summary_failures[key] = (
                    self._json_loads(fields["_hitl_summary_failure"]) or {}
                )
            if "_hitl_visual_evidence" in fields:
                hitl_visual_evidence[key] = (
                    self._json_loads(fields["_hitl_visual_evidence"]) or {}
                )
            if "_review_attempts" in fields:
                review_attempts[key] = int(fields["_review_attempts"])
            if "_review_feedback" in fields:
                review_feedback[key] = fields["_review_feedback"]
            if "_worker_result_meta" in fields:
                worker_result_meta[key] = (
                    self._json_loads(fields["_worker_result_meta"]) or {}
                )
            if "_verification_issue" in fields:
                verification_issues[key] = int(fields["_verification_issue"])
            if "_issue_attempts" in fields:
                issue_attempts[key] = int(fields["_issue_attempts"])
            if "_last_reviewed_sha" in fields:
                last_reviewed_shas[key] = fields["_last_reviewed_sha"]
            if "_outcome" in fields:
                issue_outcomes[key] = self._json_loads(fields["_outcome"]) or {}
            if "_hook_failures" in fields:
                hook_failures[key] = self._json_loads(fields["_hook_failures"]) or []

        # PRs
        reviewed_prs: dict[str, str] = {}
        for pr_num, status in self.prs.get_all():
            reviewed_prs[str(pr_num)] = status

        # Interrupted issues
        interrupted_raw = self.issues.get_field(0, "_interrupted_issues")
        interrupted_issues = self._json_loads(interrupted_raw) if interrupted_raw else {}

        # Memory state
        mem = self._memory_state.get_all()
        mem_issue_ids = self._json_loads(mem.get("issue_ids")) if mem.get("issue_ids") else []

        # Manifest state
        mfst = self._manifest_state.get_all()

        # Metrics state
        mets = self._metrics_state.get_all()

        # Lifetime stats
        lt = self._lifetime.get_all()
        lt.pop("id", None)
        # Deserialize JSON text fields
        for json_field in ("merge_durations", "retries_per_stage", "fired_thresholds"):
            val = lt.get(json_field)
            if isinstance(val, str):
                lt[json_field] = self._json_loads(val) or (
                    [] if json_field != "retries_per_stage" else {}
                )

        # Session counters
        sc = self._session_ctr.get_all()
        sc.pop("id", None)

        # Worker heartbeats and states
        worker_heartbeats = self._build_worker_heartbeats()
        bg_worker_states = self._build_bg_worker_states()

        # Worker intervals and disabled
        worker_intervals = self._build_worker_intervals()
        disabled_workers = self._build_disabled_workers()

        # Baseline audit
        baseline_audit = self._build_all_baseline_audit()

        return {
            "processed_issues": processed_issues,
            "active_worktrees": active_worktrees,
            "active_branches": active_branches,
            "reviewed_prs": reviewed_prs,
            "hitl_origins": hitl_origins,
            "hitl_causes": hitl_causes,
            "hitl_summaries": hitl_summaries,
            "hitl_summary_failures": hitl_summary_failures,
            "hitl_visual_evidence": hitl_visual_evidence,
            "review_attempts": review_attempts,
            "review_feedback": review_feedback,
            "worker_result_meta": worker_result_meta,
            "bg_worker_states": bg_worker_states,
            "worker_heartbeats": worker_heartbeats,
            "verification_issues": verification_issues,
            "issue_attempts": issue_attempts,
            "active_issue_numbers": self.get_active_issue_numbers(),
            "lifetime_stats": lt,
            "session_counters": sc,
            "memory_issue_ids": mem_issue_ids,
            "memory_digest_hash": mem.get("digest_hash") or "",
            "memory_last_synced": mem.get("last_synced"),
            "manifest_issue_number": mfst.get("issue_number"),
            "manifest_snapshot_hash": mfst.get("snapshot_hash") or "",
            "manifest_hash": mfst.get("hash") or "",
            "manifest_last_updated": mfst.get("last_updated"),
            "metrics_issue_number": mets.get("issue_number"),
            "metrics_last_snapshot_hash": mets.get("last_snapshot_hash") or "",
            "metrics_last_synced": mets.get("last_synced"),
            "worker_intervals": worker_intervals,
            "disabled_workers": disabled_workers,
            "interrupted_issues": interrupted_issues or {},
            "last_reviewed_shas": last_reviewed_shas,
            "pending_reports": self.get_pending_reports(),
            "issue_outcomes": issue_outcomes,
            "hook_failures": hook_failures,
            "epic_states": self.get_all_epic_states(),
            "releases": self.get_all_releases(),
            "baseline_audit": baseline_audit,
            "active_crate_number": self.get_active_crate_number(),
            "last_updated": self._now_iso(),
        }

    # ------------------------------------------------------------------
    # Lifetime stats
    # ------------------------------------------------------------------

    def _increment_lifetime_stat(
        self, field: str, delta: int, *, floor_zero: bool = False
    ) -> None:
        current = self._lifetime._get(field) or 0  # noqa: SLF001
        new_val = current + delta
        if floor_zero and new_val < 0:
            new_val = 0
        self._lifetime._set(field, new_val)  # noqa: SLF001

    def record_issue_completed(self) -> None:
        """Increment the all-time issues-completed counter."""
        self._increment_lifetime_stat("issues_completed", 1)

    def record_pr_merged(self) -> None:
        """Increment the all-time PRs-merged counter."""
        self._increment_lifetime_stat("prs_merged", 1)

    def record_issue_created(self) -> None:
        """Increment the all-time issues-created counter."""
        self._increment_lifetime_stat("issues_created", 1)

    def record_quality_fix_rounds(self, count: int) -> None:
        """Accumulate quality fix rounds from an implementation run."""
        self._increment_lifetime_stat("total_quality_fix_rounds", count)

    def record_ci_fix_rounds(self, count: int) -> None:
        """Accumulate CI fix rounds from a review run."""
        self._increment_lifetime_stat("total_ci_fix_rounds", count)

    def record_hitl_escalation(self) -> None:
        """Increment the all-time HITL escalation counter."""
        self._increment_lifetime_stat("total_hitl_escalations", 1)

    def record_review_verdict(self, verdict: str, fixes_made: bool) -> None:
        """Record a review verdict in lifetime stats."""
        if verdict == "approve":
            self._increment_lifetime_stat("total_review_approvals", 1)
        elif verdict == "request-changes":
            self._increment_lifetime_stat("total_review_request_changes", 1)
        if fixes_made:
            self._increment_lifetime_stat("total_reviewer_fixes", 1)

    def record_implementation_duration(self, seconds: float) -> None:
        """Accumulate implementation agent duration."""
        current = self._lifetime._get("total_implementation_seconds") or 0.0  # noqa: SLF001
        self._lifetime._set("total_implementation_seconds", current + seconds)  # noqa: SLF001

    def record_review_duration(self, seconds: float) -> None:
        """Accumulate review agent duration."""
        current = self._lifetime._get("total_review_seconds") or 0.0  # noqa: SLF001
        self._lifetime._set("total_review_seconds", current + seconds)  # noqa: SLF001

    def get_lifetime_stats(self) -> LifetimeStats:
        """Return lifetime stats as a ``LifetimeStats`` Pydantic model."""
        lt = self._lifetime.get_all()
        lt.pop("id", None)
        for json_field in ("merge_durations", "retries_per_stage", "fired_thresholds"):
            val = lt.get(json_field)
            if isinstance(val, str):
                lt[json_field] = self._json_loads(val) or (
                    [] if json_field != "retries_per_stage" else {}
                )
        return LifetimeStats.model_validate(lt)

    # ------------------------------------------------------------------
    # Active crate
    # ------------------------------------------------------------------

    def get_active_crate_number(self) -> int | None:
        """Return the persisted active crate (milestone) number, or None."""
        val = self._active_crate._get("crate_number")  # noqa: SLF001
        return val if val is not None else None

    def set_active_crate_number(self, number: int | None) -> None:
        """Persist the active crate number (or clear it with None)."""
        self._active_crate._set("crate_number", number)  # noqa: SLF001

    # ------------------------------------------------------------------
    # Session counters
    # ------------------------------------------------------------------

    def increment_session_counter(self, stage: str) -> None:
        """Increment the session counter for *stage* and persist."""
        if stage not in self._SESSION_COUNTER_FIELDS:
            return
        # Safe: stage validated against frozenset
        self.db.execute(
            f"UPDATE session_counters SET {stage} = {stage} + 1 WHERE id = 1"  # noqa: S608
        )

    def get_session_counters(self) -> dict[str, Any]:
        """Return a copy of the current session counters."""
        sc = self._session_ctr.get_all()
        sc.pop("id", None)
        return sc

    def reset_session_counters(self, session_start: str) -> None:
        """Replace session counters with a fresh instance and persist."""
        self._session_ctr.update(
            triaged=0, planned=0, implemented=0,
            reviewed=0, merged=0, session_start=session_start,
        )

    def compute_session_throughput(self) -> dict[str, float]:
        """Compute issues/hour per stage from session counters and uptime."""
        sc = self.get_session_counters()
        if not sc.get("session_start"):
            return dict.fromkeys(self._SESSION_COUNTER_FIELDS, 0.0)
        try:
            started = datetime.fromisoformat(sc["session_start"])
        except (ValueError, TypeError):
            return dict.fromkeys(self._SESSION_COUNTER_FIELDS, 0.0)
        uptime_hours = (datetime.now(UTC) - started).total_seconds() / 3600.0
        uptime_hours = max(uptime_hours, 0.001)
        return {
            f: round((sc.get(f, 0) or 0) / uptime_hours, 2)
            for f in self._SESSION_COUNTER_FIELDS
        }

    # ------------------------------------------------------------------
    # Memory state
    # ------------------------------------------------------------------

    def update_memory_state(self, issue_ids: list[int], digest_hash: str) -> None:
        """Update memory tracking fields and persist."""
        self._memory_state.update(
            issue_ids=json.dumps(issue_ids),
            digest_hash=digest_hash,
            last_synced=self._now_iso(),
        )

    def get_memory_state(self) -> tuple[list[int], str, str | None]:
        """Return ``(issue_ids, digest_hash, last_synced)``."""
        data = self._memory_state.get_all()
        raw_ids = data.get("issue_ids")
        issue_ids = self._json_loads(raw_ids) if isinstance(raw_ids, str) else (raw_ids or [])
        return (
            issue_ids or [],
            data.get("digest_hash") or "",
            data.get("last_synced"),
        )

    # ------------------------------------------------------------------
    # Manifest state
    # ------------------------------------------------------------------

    def update_manifest_state(self, manifest_hash: str) -> None:
        """Update manifest tracking fields and persist."""
        self._manifest_state.update(hash=manifest_hash, last_updated=self._now_iso())

    def get_manifest_state(self) -> tuple[str, str | None]:
        """Return ``(manifest_hash, last_updated)``."""
        data = self._manifest_state.get_all()
        return data.get("hash") or "", data.get("last_updated")

    def get_manifest_issue_number(self) -> int | None:
        """Return the cached manifest issue number, or *None*."""
        return self._manifest_state._get("issue_number")  # noqa: SLF001

    def set_manifest_issue_number(self, issue_number: int) -> None:
        """Cache the manifest issue number."""
        self._manifest_state._set("issue_number", issue_number)  # noqa: SLF001

    def get_manifest_snapshot_hash(self) -> str:
        """Return the last manifest snapshot hash."""
        return self._manifest_state._get("snapshot_hash") or ""  # noqa: SLF001

    def set_manifest_snapshot_hash(self, snapshot_hash: str) -> None:
        """Update the last manifest snapshot hash."""
        self._manifest_state._set("snapshot_hash", snapshot_hash)  # noqa: SLF001

    # ------------------------------------------------------------------
    # Worker interval overrides
    # ------------------------------------------------------------------

    def _build_worker_intervals(self) -> dict[str, int]:
        workers = self._workers.get_all()
        return {
            w["name"]: w["interval"]
            for w in workers
            if w.get("interval") is not None
        }

    def get_worker_intervals(self) -> dict[str, int]:
        """Return persisted worker interval overrides."""
        return self._build_worker_intervals()

    def set_worker_intervals(self, intervals: dict[str, int]) -> None:
        """Persist worker interval overrides."""
        for name, seconds in intervals.items():
            self._workers.upsert(name, interval=seconds)

    # ------------------------------------------------------------------
    # Disabled workers
    # ------------------------------------------------------------------

    def _build_disabled_workers(self) -> list[str]:
        workers = self._workers.get_all()
        return sorted(w["name"] for w in workers if not w.get("enabled", True))

    def get_disabled_workers(self) -> set[str]:
        """Return the set of worker names that have been disabled."""
        return set(self._build_disabled_workers())

    def set_disabled_workers(self, names: set[str]) -> None:
        """Persist the set of disabled worker names."""
        # First re-enable all
        for w in self._workers.get_all():
            self._workers.set_enabled(w["name"], True)
        # Then disable the specified ones
        for name in names:
            worker = self._workers.get(name)
            if worker:
                self._workers.set_enabled(name, False)
            else:
                self._workers.upsert(name, enabled=False)

    # ------------------------------------------------------------------
    # Background worker states
    # ------------------------------------------------------------------

    def _build_worker_heartbeats(self) -> dict[str, Any]:
        workers = self._workers.get_all()
        result: dict[str, Any] = {}
        for w in workers:
            hb = w.get("heartbeat_json")
            if hb:
                result[w["name"]] = hb
        if result:
            return result
        # Fall back to state_json
        for w in workers:
            st = w.get("state_json")
            if st:
                result[w["name"]] = {
                    "status": st.get("status", "disabled"),
                    "last_run": st.get("last_run"),
                    "details": st.get("details", {}),
                }
        return result

    def _build_bg_worker_states(self) -> dict[str, Any]:
        hbs = self._build_worker_heartbeats()
        result: dict[str, Any] = {}
        for name, heartbeat in hbs.items():
            result[name] = {
                "name": name,
                "status": heartbeat.get("status", "disabled"),
                "last_run": heartbeat.get("last_run"),
                "details": heartbeat.get("details", {}),
            }
        return result

    def get_worker_heartbeats(self) -> dict[str, Any]:
        """Return the minimal persisted heartbeat snapshots."""
        return self._build_worker_heartbeats()

    def set_worker_heartbeat(self, name: str, heartbeat: Any) -> None:
        """Persist a single worker heartbeat snapshot."""
        hb = heartbeat if isinstance(heartbeat, dict) else dict(heartbeat)
        details = self._normalise_details(hb.get("details"))
        status = str(hb.get("status", "disabled"))
        last_run = self._coerce_last_run(hb.get("last_run"))
        clean_hb = {"status": status, "last_run": last_run, "details": details}
        state_data = {"name": name, "status": status, "last_run": last_run, "details": details}
        self._workers.upsert(
            name,
            heartbeat_json=clean_hb,
            state_json=state_data,
        )

    def get_bg_worker_states(self) -> dict[str, Any]:
        """Return persisted background worker heartbeat states."""
        return self._build_bg_worker_states()

    def set_bg_worker_state(self, name: str, state: Any) -> None:
        """Persist a single background worker heartbeat entry."""
        stored = state if isinstance(state, dict) else dict(state)
        stored.pop("enabled", None)
        details = self._normalise_details(stored.get("details"))
        status = str(stored.get("status", "disabled"))
        last_run = self._coerce_last_run(stored.get("last_run"))
        self.set_worker_heartbeat(
            name, {"status": status, "last_run": last_run, "details": details}
        )

    def remove_bg_worker_state(self, name: str) -> None:
        """Remove persisted heartbeat entry for *name*."""
        self._workers.upsert(name, state_json=None, heartbeat_json=None)

    # ------------------------------------------------------------------
    # Pending reports queue
    # ------------------------------------------------------------------

    def enqueue_report(self, report: Any) -> None:
        """Append a report to the pending queue and persist."""
        data = self._to_dict(report)
        self.db.execute(
            "INSERT INTO pending_reports (data_json) VALUES (%s)",
            (json.dumps(data),),
        )

    def peek_report(self) -> Any | None:
        """Return the first pending report without removing it, or None."""
        row = self.db.fetchone(
            "SELECT data_json FROM pending_reports ORDER BY id LIMIT 1"
        )
        return self._json_loads(row[0]) if row else None

    def dequeue_report(self) -> Any | None:
        """Pop the first pending report (FIFO) and persist, or return None."""
        row = self.db.fetchone(
            "SELECT id, data_json FROM pending_reports ORDER BY id LIMIT 1"
        )
        if not row:
            return None
        self.db.execute("DELETE FROM pending_reports WHERE id = %s", (row[0],))
        return self._json_loads(row[1])

    def remove_report(self, report_id: str) -> None:
        """Remove a report by ID and persist."""
        rows = self.db.fetchall(
            "SELECT id, data_json FROM pending_reports ORDER BY id"
        )
        for row_id, data_json in rows:
            parsed = self._json_loads(data_json)
            if parsed and parsed.get("id") == report_id:
                self.db.execute("DELETE FROM pending_reports WHERE id = %s", (row_id,))
                return

    def fail_report(self, report_id: str) -> int:
        """Increment attempt count for a report. Returns the new count."""
        rows = self.db.fetchall(
            "SELECT id, data_json FROM pending_reports ORDER BY id"
        )
        for row_id, data_json in rows:
            parsed = self._json_loads(data_json)
            if parsed and parsed.get("id") == report_id:
                parsed["attempts"] = parsed.get("attempts", 0) + 1
                self.db.execute(
                    "UPDATE pending_reports SET data_json = %s WHERE id = %s",
                    (json.dumps(parsed), row_id),
                )
                return parsed["attempts"]
        return 0

    def get_pending_reports(self) -> list[Any]:
        """Return a copy of the pending reports list."""
        rows = self.db.fetchall(
            "SELECT data_json FROM pending_reports ORDER BY id"
        )
        result = []
        for (data_json,) in rows:
            parsed = self._json_loads(data_json)
            if parsed:
                result.append(parsed)
        return result

    # ------------------------------------------------------------------
    # Metrics state
    # ------------------------------------------------------------------

    def get_metrics_issue_number(self) -> int | None:
        """Return the cached metrics issue number, or *None*."""
        return self._metrics_state._get("issue_number")  # noqa: SLF001

    def set_metrics_issue_number(self, issue_number: int) -> None:
        """Cache the metrics issue number."""
        self._metrics_state._set("issue_number", issue_number)  # noqa: SLF001

    def get_metrics_state(self) -> tuple[int | None, str, str | None]:
        """Return ``(issue_number, last_snapshot_hash, last_synced)``."""
        data = self._metrics_state.get_all()
        return (
            data.get("issue_number"),
            data.get("last_snapshot_hash") or "",
            data.get("last_synced"),
        )

    def update_metrics_state(self, snapshot_hash: str) -> None:
        """Update metrics tracking fields and persist."""
        self._metrics_state.update(
            last_snapshot_hash=snapshot_hash, last_synced=self._now_iso()
        )

    # ------------------------------------------------------------------
    # Threshold tracking
    # ------------------------------------------------------------------

    def get_fired_thresholds(self) -> list[str]:
        """Return list of threshold names that have already been fired."""
        raw = self._lifetime._get("fired_thresholds")  # noqa: SLF001
        if isinstance(raw, str):
            return self._json_loads(raw) or []
        return raw or []

    def mark_threshold_fired(self, name: str) -> None:
        """Record that a threshold proposal has been filed."""
        fired = self.get_fired_thresholds()
        if name not in fired:
            fired.append(name)
            self._lifetime._set("fired_thresholds", json.dumps(fired))  # noqa: SLF001

    def clear_threshold_fired(self, name: str) -> None:
        """Clear a fired threshold when the metric recovers."""
        fired = self.get_fired_thresholds()
        if name in fired:
            fired.remove(name)
            self._lifetime._set("fired_thresholds", json.dumps(fired))  # noqa: SLF001

    # ------------------------------------------------------------------
    # Time-to-merge tracking
    # ------------------------------------------------------------------

    def record_merge_duration(self, seconds: float) -> None:
        """Record a time-to-merge duration."""
        raw = self._lifetime._get("merge_durations")  # noqa: SLF001
        durations = self._json_loads(raw) if isinstance(raw, str) else (raw or [])
        durations.append(seconds)
        self._lifetime._set("merge_durations", json.dumps(durations))  # noqa: SLF001

    def get_merge_duration_stats(self) -> dict[str, float]:
        """Return time-to-merge statistics: avg, p50, p90."""
        raw = self._lifetime._get("merge_durations")  # noqa: SLF001
        durations = self._json_loads(raw) if isinstance(raw, str) else (raw or [])
        if not durations:
            return {}
        sorted_d = sorted(durations)
        n = len(sorted_d)
        avg = sum(sorted_d) / n
        p50 = sorted_d[n // 2]
        p90_idx = min(int(n * 0.9), n - 1)
        p90 = sorted_d[p90_idx]
        return {"avg": round(avg, 1), "p50": round(p50, 1), "p90": round(p90, 1)}

    # ------------------------------------------------------------------
    # Retries per stage
    # ------------------------------------------------------------------

    def record_stage_retry(self, issue_number: int, stage: str) -> None:
        """Increment the retry count for a specific stage on an issue."""
        raw = self._lifetime._get("retries_per_stage")  # noqa: SLF001
        retries = self._json_loads(raw) if isinstance(raw, str) else (raw or {})
        key = str(issue_number)
        if key not in retries:
            retries[key] = {}
        retries[key][stage] = retries[key].get(stage, 0) + 1
        self._lifetime._set("retries_per_stage", json.dumps(retries))  # noqa: SLF001

    def get_retries_summary(self) -> dict[str, int]:
        """Return total retries per stage across all issues."""
        raw = self._lifetime._get("retries_per_stage")  # noqa: SLF001
        retries = self._json_loads(raw) if isinstance(raw, str) else (raw or {})
        totals: dict[str, int] = {}
        for stages in retries.values():
            for stage, count in stages.items():
                totals[stage] = totals.get(stage, 0) + count
        return totals

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def save_session(self, session: Any) -> None:
        """Persist a session log entry."""
        data = self._to_dict(session)
        session_id = data.get("id", data.get("session_id", ""))
        started_at = data.get("started_at")
        ended_at = data.get("ended_at")
        # Use REPLACE for upsert semantics (last-write-wins)
        self.db.execute(
            "REPLACE INTO sessions (session_id, data_json, started_at, ended_at) "
            "VALUES (%s, %s, %s, %s)",
            (session_id, json.dumps(data), started_at, ended_at),
        )

    def load_sessions(
        self, repo: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Read sessions, optionally filtered by repo. Newest-first."""
        rows = self.db.fetchall(
            "SELECT data_json FROM sessions ORDER BY started_at DESC"
        )
        sessions: list[dict[str, Any]] = []
        for (data_json,) in rows:
            parsed = self._json_loads(data_json)
            if parsed:
                if repo is not None and parsed.get("repo") != repo:
                    continue
                sessions.append(parsed)
                if len(sessions) >= limit:
                    break
        return sessions

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return a single session by ID, or None."""
        row = self.db.fetchone(
            "SELECT data_json FROM sessions WHERE session_id = %s", (session_id,)
        )
        return self._json_loads(row[0]) if row else None

    def delete_session(self, session_id: str) -> bool:
        """Delete a single session by ID. Raises ValueError if active."""
        existing = self.get_session(session_id)
        if existing is None:
            return False
        if existing.get("status") == "active":
            msg = f"Cannot delete active session {session_id}"
            raise ValueError(msg)
        self.db.execute(
            "DELETE FROM sessions WHERE session_id = %s", (session_id,)
        )
        return True

    def prune_sessions(self, repo: str, max_keep: int) -> None:
        """Remove oldest sessions for *repo* beyond *max_keep*."""
        rows = self.db.fetchall(
            "SELECT session_id, data_json FROM sessions ORDER BY started_at DESC"
        )
        repo_count = 0
        to_delete: list[str] = []
        for sid, data_json in rows:
            parsed = self._json_loads(data_json)
            if parsed and parsed.get("repo") == repo:
                repo_count += 1
                if repo_count > max_keep:
                    to_delete.append(sid)
        for sid in to_delete:
            self.db.execute(
                "DELETE FROM sessions WHERE session_id = %s", (sid,)
            )

    # ------------------------------------------------------------------
    # Threshold checking
    # ------------------------------------------------------------------

    def check_thresholds(
        self,
        quality_fix_rate_threshold: float,
        approval_rate_threshold: float,
        hitl_rate_threshold: float,
    ) -> list[dict[str, Any]]:
        """Check metrics against thresholds, return crossed thresholds."""
        stats = self.get_lifetime_stats()
        total_issues = stats.issues_completed
        total_reviews = (
            stats.total_review_approvals
            + stats.total_review_request_changes
        )
        fired = getattr(stats, "fired_thresholds", []) or []

        defs: list[tuple[str, str, float, float, int, bool, str]] = [
            (
                "quality_fix_rate",
                "quality fix rate",
                (stats.total_quality_fix_rounds / total_issues
                 if total_issues else 0.0),
                quality_fix_rate_threshold,
                total_issues,
                True,
                "Review implementation prompts -- too many quality fixes needed",
            ),
            (
                "approval_rate",
                "first-pass approval rate",
                (stats.total_review_approvals / total_reviews
                 if total_reviews else 1.0),
                approval_rate_threshold,
                total_reviews,
                False,
                "Review code quality -- approval rate is below threshold",
            ),
            (
                "hitl_rate",
                "HITL escalation rate",
                (stats.total_hitl_escalations / total_issues
                 if total_issues else 0.0),
                hitl_rate_threshold,
                total_issues,
                True,
                "Investigate HITL escalation causes",
            ),
        ]

        _MIN_SAMPLES = 5
        proposals: list[dict[str, Any]] = []
        for name, metric, value, threshold, samples, exceeds_is_bad, action in defs:
            crossed = (value > threshold) if exceeds_is_bad else (value < threshold)
            if crossed and samples >= _MIN_SAMPLES:
                if name not in fired:
                    proposals.append({
                        "name": name,
                        "metric": metric,
                        "threshold": threshold,
                        "value": value,
                        "action": action,
                    })
            elif name in fired:
                self.clear_threshold_fired(name)

        return proposals

    # ------------------------------------------------------------------
    # Baseline audit trail
    # ------------------------------------------------------------------

    def record_baseline_change(
        self,
        issue_number: int,
        record: Any,
        max_records: int = 0,
    ) -> None:
        """Append a baseline audit record for *issue_number*."""
        cap = max_records or self._MAX_BASELINE_AUDIT_RECORDS
        data = self._to_dict(record)
        change_type = data.get("change_type", "")
        if hasattr(change_type, "value"):
            change_type = change_type.value
        reason = data.get("reason", "")
        pr_number = data.get("pr_number")
        changed_files = json.dumps(data.get("changed_files", []))
        approver = data.get("approver", "")
        commit_sha = data.get("commit_sha", "")
        self.db.execute(
            "INSERT INTO baseline_audit (issue_number, change_type, reason, "
            "pr_number, changed_files, approver, commit_sha) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (issue_number, change_type, reason, pr_number,
             changed_files, approver, commit_sha),
        )
        # Enforce cap
        rows = self.db.fetchall(
            "SELECT id FROM baseline_audit WHERE issue_number = %s ORDER BY id",
            (issue_number,),
        )
        if len(rows) > cap:
            to_delete = [r[0] for r in rows[: len(rows) - cap]]
            for row_id in to_delete:
                self.db.execute(
                    "DELETE FROM baseline_audit WHERE id = %s", (row_id,)
                )

    def get_baseline_audit(self, issue_number: int) -> list[dict[str, Any]]:
        """Return baseline audit records for *issue_number*."""
        rows = self.db.fetchall(
            "SELECT change_type, reason, pr_number, changed_files, "
            "approver, commit_sha, timestamp "
            "FROM baseline_audit WHERE issue_number = %s ORDER BY id",
            (issue_number,),
        )
        result = []
        for row in rows:
            result.append({
                "change_type": row[0],
                "reason": row[1],
                "pr_number": row[2],
                "changed_files": self._json_loads(row[3]) or [],
                "approver": row[4],
                "commit_sha": row[5],
                "timestamp": str(row[6]) if row[6] else None,
                "issue_number": issue_number,
            })
        return result

    def get_latest_baseline_record(
        self, issue_number: int
    ) -> dict[str, Any] | None:
        """Return the most recent baseline audit record, or *None*."""
        records = self.get_baseline_audit(issue_number)
        return records[-1] if records else None

    def rollback_baseline(
        self,
        issue_number: int,
        pr_number: int,
        approver: str,
        reason: str,
        commit_sha: str = "",
    ) -> dict[str, Any]:
        """Record a baseline rollback for *issue_number*."""
        records = self.get_baseline_audit(issue_number)
        changed_files: list[str] = []
        for record in reversed(records):
            if record.get("change_type") != "rollback":
                changed_files = list(record.get("changed_files", []))
                break
        rollback_record = {
            "pr_number": pr_number,
            "issue_number": issue_number,
            "changed_files": changed_files,
            "change_type": "rollback",
            "approver": approver,
            "reason": reason,
            "commit_sha": commit_sha,
        }
        self.record_baseline_change(issue_number, rollback_record)
        return rollback_record

    def _build_all_baseline_audit(self) -> dict[str, list[dict[str, Any]]]:
        rows = self.db.fetchall(
            "SELECT DISTINCT issue_number FROM baseline_audit"
        )
        result: dict[str, list[dict[str, Any]]] = {}
        for (inum,) in rows:
            result[str(inum)] = self.get_baseline_audit(inum)
        return result

    # ==================================================================
    # Extra telemetry methods (not in StateTracker)
    # ==================================================================

    # ------------------------------------------------------------------
    # Inferences
    # ------------------------------------------------------------------

    def append_inference(self, record: dict[str, Any]) -> None:
        """Append an inference record to the inferences table."""
        self.db.execute(
            "INSERT INTO inferences (data_json, source, session_id, pr_number, issue_number) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                json.dumps(record),
                record.get("source"),
                record.get("session_id"),
                record.get("pr_number"),
                record.get("issue_number"),
            ),
        )

    def load_recent_inferences(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent inference records, newest first."""
        rows = self.db.fetchall(
            "SELECT data_json, timestamp FROM inferences ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        result = []
        for data_json, ts in rows:
            parsed = self._json_loads(data_json)
            if parsed:
                parsed["_timestamp"] = str(ts) if ts else None
                result.append(parsed)
        return result

    def count_inferences(self) -> int:
        """Return total inference count."""
        row = self.db.fetchone("SELECT COUNT(*) FROM inferences")
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Inference stats
    # ------------------------------------------------------------------

    def save_inference_stats(self, key: str, data: dict[str, Any]) -> None:
        """Upsert inference statistics for *key*."""
        self.db.execute(
            "REPLACE INTO inference_stats (stat_key, data_json) VALUES (%s, %s)",
            (key, json.dumps(data)),
        )

    def load_inference_stats(self, key: str) -> dict[str, Any] | None:
        """Load inference statistics for *key*."""
        row = self.db.fetchone(
            "SELECT data_json FROM inference_stats WHERE stat_key = %s", (key,)
        )
        return self._json_loads(row[0]) if row else None

    def load_all_inference_stats(self) -> dict[str, Any]:
        """Load all inference statistics."""
        rows = self.db.fetchall("SELECT stat_key, data_json FROM inference_stats")
        return {r[0]: self._json_loads(r[1]) for r in rows if r[1]}

    def load_all_inference_stats_by_prefix(self, prefix: str) -> dict[str, Any]:
        """Load all inference stats whose key starts with *prefix*."""
        rows = self.db.fetchall(
            "SELECT stat_key, data_json FROM inference_stats WHERE stat_key LIKE %s",
            (prefix + "%",),
        )
        return {r[0]: self._json_loads(r[1]) for r in rows if r[1]}

    # ------------------------------------------------------------------
    # Model pricing
    # ------------------------------------------------------------------

    def upsert_model_pricing(self, model_id: str, **fields: Any) -> None:
        """Insert or update model pricing."""
        aliases = fields.get("aliases")
        if isinstance(aliases, list):
            fields["aliases"] = json.dumps(aliases)

        existing = self.db.fetchone(
            "SELECT model_id FROM model_pricing WHERE model_id = %s", (model_id,)
        )
        if existing:
            if fields:
                assignments = ", ".join(f"{k} = %s" for k in fields)
                values = tuple(fields.values()) + (model_id,)
                self.db.execute(
                    f"UPDATE model_pricing SET {assignments} WHERE model_id = %s",  # noqa: S608
                    values,
                )
        else:
            cols = ["model_id"] + list(fields.keys())
            placeholders = ", ".join(["%s"] * len(cols))
            col_names = ", ".join(cols)
            self.db.execute(
                f"INSERT INTO model_pricing ({col_names}) VALUES ({placeholders})",  # noqa: S608
                (model_id, *fields.values()),
            )

    def load_all_model_pricing(self) -> list[dict[str, Any]]:
        """Return all model pricing records."""
        rows = self.db.fetchall(
            "SELECT model_id, input_cost_per_million, output_cost_per_million, "
            "cache_write_cost_per_million, cache_read_cost_per_million, aliases "
            "FROM model_pricing"
        )
        result = []
        for row in rows:
            aliases = row[5]
            if aliases and isinstance(aliases, str):
                parsed_aliases = self._json_loads(aliases)
                if parsed_aliases is None:
                    parsed_aliases = aliases
            else:
                parsed_aliases = aliases
            result.append({
                "model_id": row[0],
                "input_cost_per_million": row[1],
                "output_cost_per_million": row[2],
                "cache_write_cost_per_million": row[3],
                "cache_read_cost_per_million": row[4],
                "aliases": parsed_aliases,
            })
        return result

    def delete_model_pricing(self, model_id: str) -> None:
        """Remove pricing for a model."""
        self.db.execute(
            "DELETE FROM model_pricing WHERE model_id = %s", (model_id,)
        )

    # ------------------------------------------------------------------
    # Review records
    # ------------------------------------------------------------------

    def append_review_record(self, record: dict[str, Any]) -> None:
        """Append a review record."""
        self._review_records.append(record)

    def load_recent_review_records(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent review records, newest first."""
        rows = self._review_records.query(limit)
        return [r.get("record", r) for r in rows]

    # ------------------------------------------------------------------
    # Harness failures
    # ------------------------------------------------------------------

    def append_harness_failure(self, record: dict[str, Any]) -> None:
        """Append a harness failure record."""
        self._harness_failures.append(record)

    def load_recent_harness_failures(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent harness failure records, newest first."""
        rows = self._harness_failures.query(limit)
        return [r.get("failure", r) for r in rows]

    # ------------------------------------------------------------------
    # Retrospectives
    # ------------------------------------------------------------------

    def append_retrospective(self, record: dict[str, Any]) -> None:
        """Append a retrospective record."""
        self._retrospectives.append(record)

    def load_recent_retrospectives(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent retrospective records, newest first."""
        rows = self._retrospectives.query(limit)
        return [r.get("retrospective", r) for r in rows]

    # ------------------------------------------------------------------
    # Events (for EventBus persistence)
    # ------------------------------------------------------------------

    def append_event(self, event: dict[str, Any]) -> None:
        """Append an event for EventBus persistence."""
        event_type = event.get("type", "unknown")
        self._events.append(event_type, event)

    def load_recent_events(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Return recent events for EventBus history replay."""
        rows = self._events.query(limit=limit)
        return [r.get("payload", r) for r in rows]

    def load_events_since(self, since_iso: str) -> list[dict[str, Any]]:
        """Return events since *since_iso* timestamp."""
        rows = self._events.query_since(since_iso)
        return [r.get("payload", r) for r in rows]

    # ------------------------------------------------------------------
    # Troubleshooting patterns
    # ------------------------------------------------------------------

    def append_troubleshooting_pattern(self, record: dict[str, Any]) -> None:
        """Append or merge a troubleshooting pattern."""
        lang = str(record.get("language", "")).lower()
        name = str(record.get("pattern_name", "")).lower()
        key = f"{lang}:{name}"
        existing = self._troubleshooting.get(key)
        if existing:
            existing["frequency"] = existing.get("frequency", 1) + 1
            src = existing.get("source_issues", [])
            for iss in record.get("source_issues", []):
                if iss not in src:
                    src.append(iss)
            existing["source_issues"] = src
            self._troubleshooting.upsert(key, existing)
        else:
            self._troubleshooting.upsert(key, record)

    def load_troubleshooting_patterns(
        self, *, language: str | None = None, limit: int | None = 10
    ) -> list[dict[str, Any]]:
        """Load patterns filtered by *language*, sorted by frequency descending."""
        all_patterns = self._troubleshooting.get_all()
        results = []
        for _key, pattern in all_patterns.items():
            if language:
                pat_lang = str(pattern.get("language", "")).lower()
                if pat_lang != language.lower() and pat_lang != "general":
                    continue
            results.append(pattern)
        results.sort(key=lambda p: p.get("frequency", 1), reverse=True)
        if limit is not None:
            results = results[:limit]
        return results

    def increment_troubleshooting_frequency(
        self, language: str, pattern_name: str
    ) -> None:
        """Bump the frequency counter for an existing pattern."""
        key = f"{language.lower()}:{pattern_name.lower()}"
        existing = self._troubleshooting.get(key)
        if existing:
            existing["frequency"] = existing.get("frequency", 1) + 1
            self._troubleshooting.upsert(key, existing)

    # ------------------------------------------------------------------
    # Dolt version-control helpers (pass-through)
    # ------------------------------------------------------------------

    def commit(self, message: str) -> None:
        """Create a Dolt commit with *message*."""
        self.db.commit(message)

    def tag(self, tag_name: str, message: str) -> None:
        """Create a Dolt tag."""
        self.db.tag(tag_name, message)
