"""Crash-recovery state persistence for HydraFlow."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from file_util import atomic_write
from models import (
    HITLSummaryCacheEntry,
    HITLSummaryFailureEntry,
    LifetimeStats,
    SessionLog,
    SessionStatus,
    StateData,
    ThresholdProposal,
    WorkerResultMeta,
)

logger = logging.getLogger("hydraflow.state")


class StateTracker:
    """JSON-file backed state for crash recovery.

    Writes ``<repo_root>/.hydraflow/state.json`` after every mutation.
    """

    def __init__(self, state_file: Path) -> None:
        self._path = state_file
        self._data: StateData = StateData()
        self.load()

    # --- persistence ---

    def load(self) -> dict[str, Any]:
        """Load state from disk, or initialise defaults."""
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text())
                if not isinstance(loaded, dict):
                    raise ValueError("State file must contain a JSON object")
                self._data = StateData.model_validate(loaded)
                logger.info("State loaded from %s", self._path)
            except (
                json.JSONDecodeError,
                OSError,
                ValueError,
                UnicodeDecodeError,
            ) as exc:
                logger.warning("Corrupt state file, resetting: %s", exc, exc_info=True)
                self._data = StateData()
        return self._data.model_dump()

    def save(self) -> None:
        """Flush current state to disk atomically."""
        self._data.last_updated = datetime.now(UTC).isoformat()
        data = self._data.model_dump_json(indent=2)
        atomic_write(self._path, data)

    # --- issue tracking ---

    def mark_issue(self, issue_number: int, status: str) -> None:
        """Record the processing status for *issue_number*."""
        self._data.processed_issues[str(issue_number)] = status
        self.save()

    # --- worktree tracking ---

    def get_active_worktrees(self) -> dict[int, str]:
        """Return ``{issue_number: worktree_path}`` mapping."""
        return {int(k): v for k, v in self._data.active_worktrees.items()}

    def set_worktree(self, issue_number: int, path: str) -> None:
        """Record the worktree filesystem *path* for *issue_number*."""
        self._data.active_worktrees[str(issue_number)] = path
        self.save()

    def remove_worktree(self, issue_number: int) -> None:
        """Remove the worktree mapping for *issue_number* (no-op if absent)."""
        self._data.active_worktrees.pop(str(issue_number), None)
        self.save()

    # --- branch tracking ---

    def set_branch(self, issue_number: int, branch: str) -> None:
        """Record the active *branch* name for *issue_number*."""
        self._data.active_branches[str(issue_number)] = branch
        self.save()

    def get_branch(self, issue_number: int) -> str | None:
        """Return the active branch for *issue_number*, or *None*."""
        return self._data.active_branches.get(str(issue_number))

    # --- PR tracking ---

    def mark_pr(self, pr_number: int, status: str) -> None:
        """Record the review *status* for *pr_number*."""
        self._data.reviewed_prs[str(pr_number)] = status
        self.save()

    # --- HITL origin tracking ---

    def set_hitl_origin(self, issue_number: int, label: str) -> None:
        """Record the label that was active before HITL escalation."""
        self._data.hitl_origins[str(issue_number)] = label
        self.save()

    def get_hitl_origin(self, issue_number: int) -> str | None:
        """Return the pre-HITL label for *issue_number*, or *None*."""
        return self._data.hitl_origins.get(str(issue_number))

    def remove_hitl_origin(self, issue_number: int) -> None:
        """Clear the HITL origin record for *issue_number*."""
        self._data.hitl_origins.pop(str(issue_number), None)
        self.save()

    # --- HITL cause tracking ---

    def set_hitl_cause(self, issue_number: int, cause: str) -> None:
        """Record the escalation reason for *issue_number*."""
        self._data.hitl_causes[str(issue_number)] = cause
        self.save()

    def get_hitl_cause(self, issue_number: int) -> str | None:
        """Return the escalation reason for *issue_number*, or *None*."""
        return self._data.hitl_causes.get(str(issue_number))

    def remove_hitl_cause(self, issue_number: int) -> None:
        """Clear the escalation reason for *issue_number*."""
        self._data.hitl_causes.pop(str(issue_number), None)
        self.save()

    # --- HITL summary cache ---

    def set_hitl_summary(self, issue_number: int, summary: str) -> None:
        """Persist cached LLM summary text for *issue_number*."""
        self._data.hitl_summaries[str(issue_number)] = HITLSummaryCacheEntry(
            summary=summary,
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._data.hitl_summary_failures.pop(str(issue_number), None)
        self.save()

    def get_hitl_summary(self, issue_number: int) -> str | None:
        """Return cached summary for *issue_number*, or ``None`` if absent."""
        entry = self._data.hitl_summaries.get(str(issue_number))
        if not entry:
            return None
        summary = str(getattr(entry, "summary", "")).strip()
        return summary or None

    def get_hitl_summary_updated_at(self, issue_number: int) -> str | None:
        """Return cached summary update timestamp for *issue_number*."""
        entry = self._data.hitl_summaries.get(str(issue_number))
        if not entry:
            return None
        updated = getattr(entry, "updated_at", None)
        return updated if isinstance(updated, str) and updated else None

    def remove_hitl_summary(self, issue_number: int) -> None:
        """Delete cached summary for *issue_number*."""
        self._data.hitl_summaries.pop(str(issue_number), None)
        self._data.hitl_summary_failures.pop(str(issue_number), None)
        self.save()

    def set_hitl_summary_failure(self, issue_number: int, error: str) -> None:
        """Persist failure metadata for summary generation attempts."""
        self._data.hitl_summary_failures[str(issue_number)] = HITLSummaryFailureEntry(
            last_failed_at=datetime.now(UTC).isoformat(),
            error=error[:300],
        )
        self.save()

    def get_hitl_summary_failure(self, issue_number: int) -> tuple[str | None, str]:
        """Return ``(last_failed_at, error)`` for summary generation failures."""
        entry = self._data.hitl_summary_failures.get(str(issue_number))
        if not entry:
            return None, ""
        return getattr(entry, "last_failed_at", None), getattr(entry, "error", "")

    def clear_hitl_summary_failure(self, issue_number: int) -> None:
        """Clear summary-generation failure metadata for *issue_number*."""
        self._data.hitl_summary_failures.pop(str(issue_number), None)
        self.save()

    # --- review attempt tracking ---

    def get_review_attempts(self, issue_number: int) -> int:
        """Return the current review attempt count for *issue_number* (default 0)."""
        return self._data.review_attempts.get(str(issue_number), 0)

    def increment_review_attempts(self, issue_number: int) -> int:
        """Increment and return the new review attempt count for *issue_number*."""
        key = str(issue_number)
        current = self._data.review_attempts.get(key, 0)
        self._data.review_attempts[key] = current + 1
        self.save()
        return current + 1

    def reset_review_attempts(self, issue_number: int) -> None:
        """Clear the review attempt counter for *issue_number*."""
        self._data.review_attempts.pop(str(issue_number), None)
        self.save()

    # --- review feedback storage ---

    def set_review_feedback(self, issue_number: int, feedback: str) -> None:
        """Store review feedback for *issue_number*."""
        self._data.review_feedback[str(issue_number)] = feedback
        self.save()

    def get_review_feedback(self, issue_number: int) -> str | None:
        """Return stored review feedback for *issue_number*, or *None*."""
        return self._data.review_feedback.get(str(issue_number))

    def clear_review_feedback(self, issue_number: int) -> None:
        """Clear stored review feedback for *issue_number*."""
        self._data.review_feedback.pop(str(issue_number), None)
        self.save()

    # --- verification issue tracking ---

    def set_verification_issue(
        self, original_issue: int, verification_issue: int
    ) -> None:
        """Record the verification issue number for *original_issue*."""
        self._data.verification_issues[str(original_issue)] = verification_issue
        self.save()

    def get_verification_issue(self, original_issue: int) -> int | None:
        """Return the verification issue number for *original_issue*, or *None*."""
        return self._data.verification_issues.get(str(original_issue))

    # --- issue attempt tracking ---

    def get_issue_attempts(self, issue_number: int) -> int:
        """Return the current implementation attempt count for *issue_number* (default 0)."""
        return self._data.issue_attempts.get(str(issue_number), 0)

    def increment_issue_attempts(self, issue_number: int) -> int:
        """Increment and return the new implementation attempt count for *issue_number*."""
        key = str(issue_number)
        current = self._data.issue_attempts.get(key, 0)
        self._data.issue_attempts[key] = current + 1
        self.save()
        return current + 1

    def reset_issue_attempts(self, issue_number: int) -> None:
        """Clear the implementation attempt counter for *issue_number*."""
        self._data.issue_attempts.pop(str(issue_number), None)
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
        self._data.interrupted_issues = {str(k): v for k, v in mapping.items()}
        self.save()

    def get_interrupted_issues(self) -> dict[int, str]:
        """Return interrupted issue mapping with int keys."""
        return {int(k): v for k, v in self._data.interrupted_issues.items()}

    def clear_interrupted_issues(self) -> None:
        """Clear the interrupted issues mapping and persist."""
        self._data.interrupted_issues = {}
        self.save()

    # --- last reviewed SHA tracking ---

    def set_last_reviewed_sha(self, issue_number: int, sha: str) -> None:
        """Record the last-reviewed commit SHA for *issue_number*."""
        self._data.last_reviewed_shas[str(issue_number)] = sha
        self.save()

    def get_last_reviewed_sha(self, issue_number: int) -> str | None:
        """Return the last-reviewed commit SHA for *issue_number*, or *None*."""
        return self._data.last_reviewed_shas.get(str(issue_number))

    def clear_last_reviewed_sha(self, issue_number: int) -> None:
        """Clear the last-reviewed commit SHA for *issue_number*."""
        self._data.last_reviewed_shas.pop(str(issue_number), None)
        self.save()

    # --- worker result metadata ---

    def set_worker_result_meta(self, issue_number: int, meta: WorkerResultMeta) -> None:
        """Persist worker result metadata for *issue_number*."""
        self._data.worker_result_meta[str(issue_number)] = meta
        self.save()

    def get_worker_result_meta(self, issue_number: int) -> WorkerResultMeta:
        """Return worker result metadata for *issue_number*, or empty dict."""
        return self._data.worker_result_meta.get(str(issue_number), {})

    # --- reset ---

    def reset(self) -> None:
        """Clear all state and persist.  Lifetime stats are preserved."""
        saved_lifetime = self._data.lifetime_stats.model_copy()
        self._data = StateData(lifetime_stats=saved_lifetime)
        self.save()

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of the raw state dict."""
        return self._data.model_dump()

    # --- lifetime stats ---

    def record_issue_completed(self) -> None:
        """Increment the all-time issues-completed counter."""
        self._data.lifetime_stats.issues_completed += 1
        self.save()

    def record_pr_merged(self) -> None:
        """Increment the all-time PRs-merged counter."""
        self._data.lifetime_stats.prs_merged += 1
        self.save()

    def record_issue_created(self) -> None:
        """Increment the all-time issues-created counter."""
        self._data.lifetime_stats.issues_created += 1
        self.save()

    def record_quality_fix_rounds(self, count: int) -> None:
        """Accumulate quality fix rounds from an implementation run."""
        self._data.lifetime_stats.total_quality_fix_rounds += count
        self.save()

    def record_ci_fix_rounds(self, count: int) -> None:
        """Accumulate CI fix rounds from a review run."""
        self._data.lifetime_stats.total_ci_fix_rounds += count
        self.save()

    def record_hitl_escalation(self) -> None:
        """Increment the all-time HITL escalation counter."""
        self._data.lifetime_stats.total_hitl_escalations += 1
        self.save()

    def record_review_verdict(self, verdict: str, fixes_made: bool) -> None:
        """Record a review verdict in lifetime stats."""
        if verdict == "approve":
            self._data.lifetime_stats.total_review_approvals += 1
        elif verdict == "request-changes":
            self._data.lifetime_stats.total_review_request_changes += 1
        if fixes_made:
            self._data.lifetime_stats.total_reviewer_fixes += 1
        self.save()

    def record_implementation_duration(self, seconds: float) -> None:
        """Accumulate implementation agent duration."""
        self._data.lifetime_stats.total_implementation_seconds += seconds
        self.save()

    def record_review_duration(self, seconds: float) -> None:
        """Accumulate review agent duration."""
        self._data.lifetime_stats.total_review_seconds += seconds
        self.save()

    def get_lifetime_stats(self) -> LifetimeStats:
        """Return a copy of the lifetime stats counters."""
        return self._data.lifetime_stats.model_copy()

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

    def get_manifest_issue_number(self) -> int | None:
        """Return the cached manifest issue number, or *None*."""
        return self._data.manifest_issue_number

    def set_manifest_issue_number(self, issue_number: int) -> None:
        """Cache the manifest issue number."""
        self._data.manifest_issue_number = issue_number
        self.save()

    def get_manifest_snapshot_hash(self) -> str:
        """Return the last manifest snapshot hash posted to the manifest issue."""
        return self._data.manifest_snapshot_hash

    def set_manifest_snapshot_hash(self, snapshot_hash: str) -> None:
        """Update the last manifest snapshot hash posted to the manifest issue."""
        self._data.manifest_snapshot_hash = snapshot_hash
        self.save()

    # --- worker interval overrides ---

    def get_worker_intervals(self) -> dict[str, int]:
        """Return persisted worker interval overrides."""
        return dict(self._data.worker_intervals)

    def set_worker_intervals(self, intervals: dict[str, int]) -> None:
        """Persist worker interval overrides."""
        self._data.worker_intervals = intervals
        self.save()

    # --- metrics state ---

    def get_metrics_issue_number(self) -> int | None:
        """Return the cached metrics issue number, or *None*."""
        return self._data.metrics_issue_number

    def set_metrics_issue_number(self, issue_number: int) -> None:
        """Cache the metrics issue number."""
        self._data.metrics_issue_number = issue_number
        self.save()

    def get_metrics_state(self) -> tuple[int | None, str, str | None]:
        """Return ``(issue_number, last_snapshot_hash, last_synced)``."""
        return (
            self._data.metrics_issue_number,
            self._data.metrics_last_snapshot_hash,
            self._data.metrics_last_synced,
        )

    def update_metrics_state(self, snapshot_hash: str) -> None:
        """Update metrics tracking fields and persist."""
        self._data.metrics_last_snapshot_hash = snapshot_hash
        self._data.metrics_last_synced = datetime.now(UTC).isoformat()
        self.save()

    # --- threshold tracking ---

    def get_fired_thresholds(self) -> list[str]:
        """Return list of threshold names that have already been fired."""
        return list(self._data.lifetime_stats.fired_thresholds)

    def mark_threshold_fired(self, name: str) -> None:
        """Record that a threshold proposal has been filed."""
        if name not in self._data.lifetime_stats.fired_thresholds:
            self._data.lifetime_stats.fired_thresholds.append(name)
            self.save()

    def clear_threshold_fired(self, name: str) -> None:
        """Clear a fired threshold when the metric recovers."""
        if name in self._data.lifetime_stats.fired_thresholds:
            self._data.lifetime_stats.fired_thresholds.remove(name)
            self.save()

    # --- time-to-merge tracking ---

    def record_merge_duration(self, seconds: float) -> None:
        """Record a time-to-merge duration (issue created to PR merged)."""
        self._data.lifetime_stats.merge_durations.append(seconds)
        self.save()

    def get_merge_duration_stats(self) -> dict[str, float]:
        """Return time-to-merge statistics: avg, p50, p90.

        Returns an empty dict if no durations are recorded.
        """
        durations = self._data.lifetime_stats.merge_durations
        if not durations:
            return {}
        sorted_d = sorted(durations)
        n = len(sorted_d)
        avg = sum(sorted_d) / n
        p50 = sorted_d[n // 2]
        p90_idx = min(int(n * 0.9), n - 1)
        p90 = sorted_d[p90_idx]
        return {"avg": round(avg, 1), "p50": round(p50, 1), "p90": round(p90, 1)}

    # --- retries per stage ---

    def record_stage_retry(self, issue_number: int, stage: str) -> None:
        """Increment the retry count for a specific stage on an issue."""
        key = str(issue_number)
        retries = self._data.lifetime_stats.retries_per_stage
        if key not in retries:
            retries[key] = {}
        retries[key][stage] = retries[key].get(stage, 0) + 1
        self.save()

    def get_retries_summary(self) -> dict[str, int]:
        """Return total retries per stage across all issues."""
        totals: dict[str, int] = {}
        for stages in self._data.lifetime_stats.retries_per_stage.values():
            for stage, count in stages.items():
                totals[stage] = totals.get(stage, 0) + count
        return totals

    # --- session persistence ---

    @property
    def _sessions_path(self) -> Path:
        return self._path.parent / "sessions.jsonl"

    def _load_sessions_deduped(self) -> dict[str, SessionLog]:
        """Read sessions.jsonl and return a deduped dict keyed by session ID.

        Uses last-write-wins: later entries for the same ID overwrite earlier ones.
        Returns empty dict if the file does not exist.
        """
        if not self._sessions_path.exists():
            return {}
        seen: dict[str, SessionLog] = {}
        try:
            with open(self._sessions_path) as f:
                for line_num, raw_line in enumerate(f, 1):
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    try:
                        session = SessionLog.model_validate_json(stripped)
                    except ValidationError:
                        logger.warning(
                            "Skipping corrupt session line %d in %s",
                            line_num,
                            self._sessions_path,
                            exc_info=True,
                        )
                        continue
                    seen[session.id] = session
        except (OSError, UnicodeDecodeError):
            logger.warning(
                "Could not open sessions file %s",
                self._sessions_path,
                exc_info=True,
            )
            return {}
        return seen

    def _write_sessions(self, sessions: list[SessionLog]) -> None:
        """Atomically rewrite sessions.jsonl with the given sessions.

        Sessions are written sorted by started_at (oldest first).
        """
        result = sorted(sessions, key=lambda s: s.started_at)
        content = "\n".join(s.model_dump_json() for s in result)
        if content:
            content += "\n"
        atomic_write(self._sessions_path, content)

    def save_session(self, session: SessionLog) -> None:
        """Append a session log entry to sessions.jsonl."""
        try:
            self._sessions_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._sessions_path, "a") as f:
                f.write(session.model_dump_json() + "\n")
                f.flush()
        except OSError:
            logger.warning(
                "Could not save session to %s",
                self._sessions_path,
                exc_info=True,
            )

    def load_sessions(
        self, repo: str | None = None, limit: int = 50
    ) -> list[SessionLog]:
        """Read sessions from JSONL, optionally filtered by repo.

        Returns up to *limit* entries sorted newest-first.
        Deduplicates by session ID, keeping the last-written (most complete) entry.
        """
        seen = self._load_sessions_deduped()
        if not seen:
            return []
        sessions = [s for s in seen.values() if repo is None or s.repo == repo]
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        return sessions[:limit]

    def get_session(self, session_id: str) -> SessionLog | None:
        """Return a single session by ID, or None.

        Scans the full file and returns the last-written entry for the given ID
        so that a session updated on close (status=completed) takes precedence
        over the initial entry written at session start (status=active).
        """
        return self._load_sessions_deduped().get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a single session by ID from sessions.jsonl.

        Returns True if the session was found and deleted, False otherwise.
        Raises ValueError if the session is currently active.
        """
        seen = self._load_sessions_deduped()
        if not seen:
            return False

        target = seen.get(session_id)
        if target is None:
            return False
        if target.status == SessionStatus.ACTIVE:
            msg = f"Cannot delete active session {session_id}"
            raise ValueError(msg)

        del seen[session_id]
        self._write_sessions(list(seen.values()))
        return True

    def prune_sessions(self, repo: str, max_keep: int) -> None:
        """Remove oldest sessions for *repo* beyond *max_keep*.

        Sessions from other repos are preserved. Uses atomic rewrite.
        """
        seen = self._load_sessions_deduped()
        if not seen:
            return

        all_sessions = list(seen.values())
        repo_sessions = [s for s in all_sessions if s.repo == repo]
        other_sessions = [s for s in all_sessions if s.repo != repo]

        repo_sessions.sort(key=lambda s: s.started_at, reverse=True)
        kept = repo_sessions[:max_keep]

        self._write_sessions(other_sessions + kept)

    # --- threshold checking ---

    def check_thresholds(
        self,
        quality_fix_rate_threshold: float,
        approval_rate_threshold: float,
        hitl_rate_threshold: float,
    ) -> list[ThresholdProposal]:
        """Check metrics against thresholds, return list of crossed thresholds.

        Returns a list of dicts with keys: name, metric, threshold, value, action.
        Only returns thresholds not already fired.  Clears fired flags for
        thresholds that have recovered.
        """
        stats = self._data.lifetime_stats
        total_issues = stats.issues_completed
        total_reviews = (
            stats.total_review_approvals + stats.total_review_request_changes
        )

        # (name, metric_label, value, threshold, sample_count, exceeds_is_bad, action)
        defs: list[tuple[str, str, float, float, int, bool, str]] = [
            (
                "quality_fix_rate",
                "quality fix rate",
                stats.total_quality_fix_rounds / total_issues if total_issues else 0.0,
                quality_fix_rate_threshold,
                total_issues,
                True,
                "Review implementation prompts — too many quality fixes needed",
            ),
            (
                "approval_rate",
                "first-pass approval rate",
                stats.total_review_approvals / total_reviews if total_reviews else 1.0,
                approval_rate_threshold,
                total_reviews,
                False,
                "Review code quality — approval rate is below threshold",
            ),
            (
                "hitl_rate",
                "HITL escalation rate",
                stats.total_hitl_escalations / total_issues if total_issues else 0.0,
                hitl_rate_threshold,
                total_issues,
                True,
                "Investigate HITL escalation causes — too many issues need human intervention",
            ),
        ]

        _MIN_SAMPLES = 5
        proposals: list[ThresholdProposal] = []
        for name, metric, value, threshold, samples, exceeds_is_bad, action in defs:
            crossed = (value > threshold) if exceeds_is_bad else (value < threshold)
            if crossed and samples >= _MIN_SAMPLES:
                if name not in stats.fired_thresholds:
                    proposals.append(
                        {
                            "name": name,
                            "metric": metric,
                            "threshold": threshold,
                            "value": value,
                            "action": action,
                        }
                    )
            elif name in stats.fired_thresholds:
                self.clear_threshold_fired(name)

        return proposals
