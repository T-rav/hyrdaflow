"""Lifetime stats, thresholds, merge durations, and retries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import LifetimeStats, ThresholdProposal

if TYPE_CHECKING:
    from models import StateData


class LifetimeStatsMixin:
    """Methods for lifetime counters, merge duration, retries, and threshold checking."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

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
