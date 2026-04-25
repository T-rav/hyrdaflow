"""Background worker loop — health monitor with safe auto-adjustment.

Periodically evaluates pipeline health metrics, applies safe session-scoped
parameter adjustments within bounded ranges, writes a decision audit trail,
and files HITL recommendations for problems outside the safe adjustment range.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore

if TYPE_CHECKING:
    from bg_worker_manager import BGWorkerManager
    from ports import PRPort
    from retrospective_queue import RetrospectiveQueue
    from state import StateTracker

logger = logging.getLogger("hydraflow.health_monitor_loop")

# ---------------------------------------------------------------------------
# Tunable parameter bounds (inclusive)
# ---------------------------------------------------------------------------

TUNABLE_BOUNDS: dict[str, tuple[int, int]] = {
    "max_quality_fix_attempts": (1, 5),
    "agent_timeout": (120, 900),
}

# ---------------------------------------------------------------------------
# Adjustment rules: (metric_expr, parameter, direction_delta)
# Each rule is checked in order; at most one adjustment per parameter per cycle.
# ---------------------------------------------------------------------------

_AdjustmentRule = tuple[str, str, int]  # (condition_key, parameter, step)

ADJUSTMENT_RULES: list[_AdjustmentRule] = [
    ("first_pass_rate_low", "max_quality_fix_attempts", +1),
    ("first_pass_rate_high", "max_quality_fix_attempts", -1),
]

# Thresholds used in condition evaluation
_FIRST_PASS_LOW = 0.2
_FIRST_PASS_HIGH = 0.9
_SURPRISE_HIGH = 0.3
_HITL_HIGH = 0.4
_AVG_SCORE_LOW = 0.4
_STALE_COUNT_HIGH = 5

# HealthMonitor dead-man-switch for TrustFleetSanityLoop (spec §12.1).
# Files a `hydraflow-find` + `sanity-loop-stalled` issue when the sanity
# loop's heartbeat is older than this multiple of its configured interval.
_SANITY_STALL_MULTIPLIER = 3

# ---------------------------------------------------------------------------
# Trend metrics
# ---------------------------------------------------------------------------


class TrendMetrics:
    """Computed health trend metrics for one monitor cycle."""

    def __init__(
        self,
        first_pass_rate: float,
        avg_memory_score: float,
        surprise_rate: float,
        hitl_escalation_rate: float,
        stale_item_count: int,
        total_outcomes: int,
    ) -> None:
        self.first_pass_rate = first_pass_rate
        self.avg_memory_score = avg_memory_score
        self.surprise_rate = surprise_rate
        self.hitl_escalation_rate = hitl_escalation_rate
        self.stale_item_count = stale_item_count
        self.total_outcomes = total_outcomes

    def active_conditions(self) -> list[str]:
        """Return a list of active condition keys for adjustment rule matching."""
        conditions: list[str] = []
        if self.first_pass_rate < _FIRST_PASS_LOW:
            conditions.append("first_pass_rate_low")
        if self.first_pass_rate > _FIRST_PASS_HIGH:
            conditions.append("first_pass_rate_high")
        return conditions


# ---------------------------------------------------------------------------
# Decision audit trail
# ---------------------------------------------------------------------------


def _next_decision_id(_decisions_dir: Path) -> str:
    """Return a unique decision ID using UUID."""
    return f"adj-{uuid.uuid4().hex[:8]}"


def _write_decision(decisions_dir: Path, record: dict[str, Any]) -> None:
    try:
        decisions_dir.mkdir(parents=True, exist_ok=True)
        decisions_file = decisions_dir / "decisions.jsonl"
        with decisions_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Disk full, permission, or other I/O error — the health monitor loop
        # must not abort over a single failed decision write.
        logger.warning(
            "Failed to persist health decision to %s", decisions_dir, exc_info=True
        )


def _load_decisions(decisions_dir: Path) -> list[dict[str, Any]]:
    decisions_file = decisions_dir / "decisions.jsonl"
    if not decisions_file.exists():
        return []
    try:
        lines = decisions_file.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        rec: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            rec = json.loads(line)
        if rec:
            records.append(rec)
    return records


def _update_decision(
    decisions_dir: Path, decision_id: str, updates: dict[str, Any]
) -> None:
    """Atomically rewrite decisions.jsonl updating the record matching decision_id."""
    records = _load_decisions(decisions_dir)
    updated = False
    for record in records:
        if record.get("decision_id") == decision_id:
            record.update(updates)
            updated = True
            break
    if not updated:
        return
    decisions_dir.mkdir(parents=True, exist_ok=True)
    decisions_file = decisions_dir / "decisions.jsonl"
    # Write to a temp file first, then atomically rename to avoid data loss on crash
    fd, tmp_path = tempfile.mkstemp(dir=str(decisions_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(tmp_path, str(decisions_file))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Metric computation helpers
# ---------------------------------------------------------------------------


def compute_trend_metrics(
    outcomes_path: Path,
    scores_path: Path,
    failures_path: Path,
    *,
    window: int = 50,
) -> TrendMetrics:
    """Load recent data and compute all trend metrics."""
    # --- outcomes.jsonl ---
    successes = 0
    total_outcomes = 0
    if outcomes_path.exists():
        try:
            lines = outcomes_path.read_text(encoding="utf-8").strip().splitlines()
            tail = lines[-window:] if len(lines) > window else lines
            for line in tail:
                try:
                    rec = json.loads(line)
                    total_outcomes += 1
                    if rec.get("outcome") == "success":
                        successes += 1
                except Exception:  # noqa: BLE001
                    logger.debug("Skipping malformed outcomes line", exc_info=True)
        except OSError:
            pass

    first_pass_rate = (successes / total_outcomes) if total_outcomes > 0 else 0.0

    # --- item_scores.json ---
    avg_memory_score = 0.0
    stale_item_count = 0
    if scores_path.exists():
        try:
            raw: dict[str, Any] = json.loads(scores_path.read_text(encoding="utf-8"))
            scores = list(raw.values())
            if scores:
                score_vals = [float(s.get("score", 0.5)) for s in scores]
                avg_memory_score = sum(score_vals) / len(score_vals)
                stale_item_count = sum(
                    1
                    for s in scores
                    if float(s.get("score", 0.5)) < 0.3
                    and int(s.get("appearances", 0)) >= 5
                )
        except Exception:  # noqa: BLE001
            # Signal parse failure via a sentinel negative count (#6470) so
            # callers can distinguish "no data" from "corrupt file".
            logger.warning(
                "Failed to parse item_scores.json — score metrics unavailable",
                exc_info=True,
            )
            avg_memory_score = 0.0
            stale_item_count = -1

    # --- harness_failures.jsonl — surprise & hitl rates ---
    total_failures = 0
    surprise_count = 0
    hitl_count = 0
    if failures_path.exists():
        try:
            lines = failures_path.read_text(encoding="utf-8").strip().splitlines()
            tail = lines[-window:] if len(lines) > window else lines
            total_failures = len(tail)
            for line in tail:
                try:
                    rec = json.loads(line)
                    if rec.get("category") == "hitl_escalation":
                        hitl_count += 1
                    # Surprise is detected in the memory trail, not here;
                    # we approximate via "review_rejection" as unexpected
                    if rec.get("category") == "review_rejection":
                        surprise_count += 1
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "Skipping malformed harness_failures line",
                        exc_info=True,
                    )
        except OSError:
            logger.warning("Failed to read harness_failures.jsonl", exc_info=True)

    surprise_rate = (surprise_count / total_failures) if total_failures > 0 else 0.0
    hitl_escalation_rate = (hitl_count / total_failures) if total_failures > 0 else 0.0

    return TrendMetrics(
        first_pass_rate=first_pass_rate,
        avg_memory_score=avg_memory_score,
        surprise_rate=surprise_rate,
        hitl_escalation_rate=hitl_escalation_rate,
        stale_item_count=stale_item_count,
        total_outcomes=total_outcomes,
    )


# ---------------------------------------------------------------------------
# Pending adjustment tracking (for outcome verification)
# ---------------------------------------------------------------------------


class PendingAdjustment:
    """Tracks a single applied auto-adjustment awaiting outcome verification."""

    def __init__(
        self,
        decision_id: str,
        parameter: str,
        before: int,
        after: int,
        metric_name: str,
        metric_value: float,
        outcomes_at_adjustment: int,
    ) -> None:
        self.decision_id = decision_id
        self.parameter = parameter
        self.before = before
        self.after = after
        self.metric_name = metric_name
        self.metric_value = metric_value
        self.outcomes_at_adjustment = outcomes_at_adjustment


# ---------------------------------------------------------------------------
# HealthMonitorLoop
# ---------------------------------------------------------------------------


class HealthMonitorLoop(BaseBackgroundLoop):
    """Monitors pipeline health metrics, auto-adjusts bounded config parameters,
    records decisions, and files HITL recommendations for unsafe changes.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        deps: LoopDeps,
        *,
        prs: PRPort | None = None,
        verification_window: int = 20,
        retrospective_queue: RetrospectiveQueue | None = None,
        state: StateTracker | None = None,
        bg_workers: BGWorkerManager | None = None,
    ) -> None:
        super().__init__(
            worker_name="health_monitor",
            config=config,
            deps=deps,
        )
        self._prs = prs
        self._verification_window = verification_window
        self._retrospective_queue = retrospective_queue
        self._decisions_dir: Path = config.memory_dir
        # §12.1 dead-man-switch inputs — ``state`` is available at
        # service-registry time; ``bg_workers`` is built after the loop
        # registry, so orchestrator injects it via ``set_bg_workers``.
        self._state: StateTracker | None = state
        self._bg_workers: BGWorkerManager | None = bg_workers
        # Dedup for the dead-man-switch so we file one sanity-loop-stalled
        # issue per stall event, not one per health_monitor tick.
        self._sanity_stall_dedup = DedupStore(
            "health_monitor_sanity_stall",
            config.data_root / "dedup" / "health_monitor_sanity_stall.json",
        )
        self._pending: list[PendingAdjustment] = []
        self._last_log_scan: datetime | None = None

    def set_bg_workers(self, bg_workers: BGWorkerManager) -> None:
        """Late-binding for the post-ctor BGWorkerManager wiring."""
        self._bg_workers = bg_workers

    def _get_default_interval(self) -> int:
        return self._config.health_monitor_interval

    @property
    def _outcomes_path(self) -> Path:
        return self._config.memory_dir / "outcomes.jsonl"

    @property
    def _scores_path(self) -> Path:
        return self._config.memory_dir / "item_scores.json"

    @property
    def _failures_path(self) -> Path:
        return self._config.memory_dir / "harness_failures.jsonl"

    async def _do_work(self) -> dict[str, Any] | None:
        """Execute one health-monitor cycle."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Dead-man-switch: detect a stalled TrustFleetSanityLoop (spec §12.1).
        try:
            await self._check_sanity_loop_staleness()
        except Exception:  # noqa: BLE001
            logger.debug("sanity-loop stall check failed", exc_info=True)

        metrics = compute_trend_metrics(
            self._outcomes_path, self._scores_path, self._failures_path
        )
        logger.info(
            "Health monitor cycle: first_pass_rate=%.2f avg_score=%.2f "
            "surprise_rate=%.2f hitl_rate=%.2f stale_items=%d",
            metrics.first_pass_rate,
            metrics.avg_memory_score,
            metrics.surprise_rate,
            metrics.hitl_escalation_rate,
            metrics.stale_item_count,
        )

        self._verify_pending_adjustments(metrics)
        adjustments_made = self._apply_adjustments(metrics)
        await self._file_hitl_recommendations(metrics)

        gap_count = self._run_knowledge_gap_count()
        log_result = await self._run_log_ingestion_cycle()
        await self._run_harness_auto_file_cycle()
        await self._run_harness_suggestion_ingestion_cycle()
        self._run_proposal_verification_cycle()
        self._run_cross_project_pattern_cycle()

        self._emit_sentry_metrics(
            metrics,
            gap_count=gap_count,
            adjustment_count=adjustments_made,
            log_patterns_total=log_result.total_patterns if log_result else 0,
            log_patterns_novel=log_result.filed if log_result else 0,
            log_patterns_escalating=log_result.escalated if log_result else 0,
            hitl_recommendations_count=self._count_unactioned_hitl_recommendations(),
        )

        return {
            "first_pass_rate": round(metrics.first_pass_rate, 4),
            "avg_memory_score": round(metrics.avg_memory_score, 4),
            "surprise_rate": round(metrics.surprise_rate, 4),
            "hitl_escalation_rate": round(metrics.hitl_escalation_rate, 4),
            "stale_item_count": metrics.stale_item_count,
            "adjustments_made": adjustments_made,
            "total_outcomes": metrics.total_outcomes,
        }

    # ------------------------------------------------------------------
    # Extracted sub-tasks (each independently testable)
    # ------------------------------------------------------------------

    def _run_knowledge_gap_count(self) -> int:
        """Knowledge gap detection retired with memory_scoring in Phase 3 cutover."""
        return 0

    async def _run_log_ingestion_cycle(self) -> Any | None:
        """Parse logs, detect patterns, enrich, and file novel patterns."""
        try:
            from log_ingestion import (  # noqa: PLC0415
                detect_log_patterns,
                file_log_patterns,
                load_known_patterns,
                parse_log_files,
                save_known_patterns,
            )

            log_file = getattr(self._config, "log_file", None)
            if log_file:
                log_dir = Path(log_file).parent
            else:
                log_dir = self._config.data_root / "logs"

            if not log_dir.is_dir():
                return None

            entries = parse_log_files(log_dir, since=self._last_log_scan)
            patterns = detect_log_patterns(entries)
            known = load_known_patterns(self._config.memory_dir)

            # Enrich with EventBus context (best-effort)
            try:
                from log_ingestion import (
                    enrich_patterns_with_events,  # noqa: PLC0415
                )

                history = self._bus.get_history() if hasattr(self, "_bus") else []
                event_dicts = [{"type": e.type.value, "data": e.data} for e in history]
                enrich_patterns_with_events(patterns, event_dicts)
            except Exception:  # noqa: BLE001
                # Best-effort enrichment — don't crash the cycle, but leave
                # a debug-level signal so operators can diagnose failing
                # event-dict construction (#6622).
                logger.debug("EventBus enrichment failed", exc_info=True)

            log_result = await file_log_patterns(patterns, known, self._config)
            save_known_patterns(self._config.memory_dir, known)
            self._last_log_scan = datetime.now(UTC)

            logger.info(
                "Log ingestion: %d patterns, %d novel filed, %d escalated",
                log_result.total_patterns,
                log_result.filed,
                log_result.escalated,
            )
            return log_result
        except ImportError:
            return None
        except Exception:  # noqa: BLE001
            logger.debug("Log ingestion failed", exc_info=True)
            return None

    async def _run_harness_auto_file_cycle(self) -> None:
        """Auto-file harness insight suggestions."""
        try:
            from harness_insights import (  # noqa: PLC0415
                HarnessInsightStore,
                auto_file_suggestions,
            )

            store = HarnessInsightStore(self._config.memory_dir)
            await auto_file_suggestions(store, self._config)
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("Harness auto-file failed", exc_info=True)

    async def _run_harness_suggestion_ingestion_cycle(self) -> None:
        """Read harness suggestions JSONL and file each as a memory item."""
        try:
            suggestions_path = self._config.data_path(
                "memory", "harness_suggestions.jsonl"
            )
            if not suggestions_path.exists():
                return

            from phase_utils import file_memory_suggestion  # noqa: PLC0415

            raw_suggestions = (
                suggestions_path.read_text(encoding="utf-8").strip().splitlines()
            )
            for line in raw_suggestions:
                try:
                    rec = json.loads(line)
                    principle = rec.get("suggestion", rec.get("title", ""))
                    rationale = (
                        f"Detected from {rec.get('occurrences', 0)} pipeline"
                        f" failures in category {rec.get('category', 'unknown')}"
                    )
                    failure_mode = (
                        f"Pipeline failure pattern: {rec.get('title', 'Unknown')}"
                    )
                    transcript = (
                        "MEMORY_SUGGESTION_START\n"
                        f"principle: {principle}\n"
                        f"rationale: {rationale}\n"
                        f"failure_mode: {failure_mode}\n"
                        "scope: hydraflow\n"
                        "MEMORY_SUGGESTION_END"
                    )
                    await file_memory_suggestion(
                        transcript,
                        "harness_insight",
                        "health_monitor",
                        self._config,
                    )
                except Exception:  # noqa: BLE001
                    continue
            # Clear processed suggestions so they are not re-ingested
            suggestions_path.write_text("", encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.debug("Harness suggestion ingestion failed", exc_info=True)

    def _run_proposal_verification_cycle(self) -> None:
        """Enqueue proposal verification or run inline fallback."""
        if self._retrospective_queue is not None:
            from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

            self._retrospective_queue.append(QueueItem(kind=QueueKind.VERIFY_PROPOSALS))
            return

        # Fallback: inline verification when queue not wired
        try:
            from review_insights import (  # noqa: PLC0415
                ReviewInsightStore,
                verify_proposals,
            )

            insight_store = ReviewInsightStore(self._config.memory_dir)
            records = insight_store.load_recent(50)
            stale = verify_proposals(insight_store, records)
            for category in stale:
                logger.warning(
                    "HITL recommendation: stale review insight '%s'", category
                )
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("Proposal verification failed", exc_info=True)

    def _run_cross_project_pattern_cycle(self) -> None:
        """Detect log patterns shared across projects."""
        try:
            from log_ingestion import (  # noqa: PLC0415
                detect_cross_project_log_patterns,
                load_known_patterns,
            )

            project_patterns = {
                self._config.repo_slug: load_known_patterns(self._config.memory_dir)
            }
            cross_patterns = detect_cross_project_log_patterns(project_patterns)
            if cross_patterns:
                logger.info("Found %d cross-project log patterns", len(cross_patterns))
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("Cross-project log pattern detection failed", exc_info=True)

    def _count_unactioned_hitl_recommendations(self) -> int:
        """Count unactioned HITL recommendations for Sentry metrics."""
        try:
            rec_path = self._config.data_path("memory", "hitl_recommendations.jsonl")
            if not rec_path.exists():
                return 0
            lines = rec_path.read_text(encoding="utf-8").strip().splitlines()
            return sum(
                1
                for line in lines
                if line.strip() and not json.loads(line).get("actioned", False)
            )
        except Exception:  # noqa: BLE001
            return 0

    # ------------------------------------------------------------------
    # Safe auto-adjustment
    # ------------------------------------------------------------------

    def _apply_adjustments(self, metrics: TrendMetrics) -> int:
        """Apply ADJUSTMENT_RULES against active conditions. Returns count applied."""
        active = set(metrics.active_conditions())
        if not active:
            return 0

        applied = 0
        for condition_key, parameter, step in ADJUSTMENT_RULES:
            if condition_key not in active:
                continue
            try:
                current_val = int(getattr(self._config, parameter))
                lo, hi = TUNABLE_BOUNDS[parameter]
                new_val = current_val + step
                new_val = max(lo, min(hi, new_val))
                if new_val == current_val:
                    continue

                object.__setattr__(self._config, parameter, new_val)

                decision_id = _next_decision_id(self._decisions_dir)
                evidence = (
                    f"{metrics.total_outcomes - int(metrics.first_pass_rate * metrics.total_outcomes)}"
                    f"/{metrics.total_outcomes} issues needed retry"
                )
                record: dict[str, Any] = {
                    "decision_id": decision_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "type": "auto_adjust",
                    "parameter": parameter,
                    "before": current_val,
                    "after": new_val,
                    "reason": (
                        f"{condition_key.replace('_', ' ')} "
                        f"{metrics.first_pass_rate:.2f} "
                        f"{'below' if step > 0 else 'above'} "
                        f"{_FIRST_PASS_LOW if step > 0 else _FIRST_PASS_HIGH} threshold"
                    ),
                    "evidence_summary": evidence,
                    "outcome_verified": None,
                }
                _write_decision(self._decisions_dir, record)
                logger.info(
                    "Auto-adjusted %s: %d → %d (%s)",
                    parameter,
                    current_val,
                    new_val,
                    condition_key,
                )
                try:
                    import sentry_sdk  # noqa: PLC0415

                    sentry_sdk.add_breadcrumb(
                        category="memory.auto_adjust",
                        message=f"Adjusted {parameter}: {current_val} → {new_val}",
                        level="warning",
                        data={
                            "parameter": parameter,
                            "before": current_val,
                            "after": new_val,
                            "reason": record["reason"],
                        },
                    )
                except ImportError:
                    pass

                self._pending.append(
                    PendingAdjustment(
                        decision_id=decision_id,
                        parameter=parameter,
                        before=current_val,
                        after=new_val,
                        metric_name="first_pass_rate",
                        metric_value=metrics.first_pass_rate,
                        outcomes_at_adjustment=metrics.total_outcomes,
                    )
                )
                applied += 1
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Auto-adjustment failed for parameter %s",
                    parameter,
                    exc_info=True,
                )

        return applied

    # ------------------------------------------------------------------
    # Outcome verification
    # ------------------------------------------------------------------

    def _count_outcomes_since(self, since_count: int) -> int:
        """Return total outcomes accumulated since a prior snapshot count."""
        try:
            if not self._outcomes_path.exists():
                return 0
            lines = self._outcomes_path.read_text(encoding="utf-8").strip().splitlines()
            return max(0, len(lines) - since_count)
        except Exception:  # noqa: BLE001
            return 0

    def _verify_pending_adjustments(self, metrics: TrendMetrics) -> None:
        """Check if any pending adjustments have enough follow-on outcomes for verification."""
        still_pending: list[PendingAdjustment] = []
        for adj in self._pending:
            try:
                new_outcomes = self._count_outcomes_since(adj.outcomes_at_adjustment)
                if new_outcomes < self._verification_window:
                    still_pending.append(adj)
                    continue

                # Enough outcomes — evaluate
                new_metric_val = metrics.first_pass_rate
                old_metric_val = adj.metric_value
                improved_direction = adj.after > adj.before  # larger = more attempts

                if improved_direction:
                    # We increased attempts hoping to improve first_pass_rate
                    improved = new_metric_val > old_metric_val + 0.05
                    worsened = new_metric_val < old_metric_val - 0.05
                else:
                    # We reduced attempts hoping it stays high
                    improved = new_metric_val >= old_metric_val - 0.05
                    worsened = new_metric_val < old_metric_val - 0.1

                if worsened:
                    # Revert the adjustment
                    try:
                        object.__setattr__(self._config, adj.parameter, adj.before)
                        logger.warning(
                            "Reverting auto-adjustment %s for %s: metric worsened"
                            " (%.2f → %.2f)",
                            adj.decision_id,
                            adj.parameter,
                            old_metric_val,
                            new_metric_val,
                        )
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "Failed to revert %s for %s",
                            adj.decision_id,
                            adj.parameter,
                            exc_info=True,
                        )
                    outcome_verified = "reverted"
                elif improved:
                    outcome_verified = "improved"
                else:
                    outcome_verified = "neutral"

                _update_decision(
                    self._decisions_dir,
                    adj.decision_id,
                    {"outcome_verified": outcome_verified},
                )
                logger.info(
                    "Decision %s verified as %s",
                    adj.decision_id,
                    outcome_verified,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Verification check failed for decision %s",
                    adj.decision_id,
                    exc_info=True,
                )
                still_pending.append(adj)

        self._pending = still_pending

    # ------------------------------------------------------------------
    # HITL recommendations
    # ------------------------------------------------------------------

    async def _file_hitl_recommendations(self, metrics: TrendMetrics) -> None:
        """Write HITL recommendations to JSONL for unsafe problems needing human attention."""
        try:
            recommendations: list[tuple[str, float, str, str]] = []

            if metrics.surprise_rate > _SURPRISE_HIGH:
                recommendations.append(
                    (
                        "surprise_rate",
                        metrics.surprise_rate,
                        (
                            "High surprise rate indicates memory items are consistently "
                            "producing unexpected outcomes (high-score items failing or "
                            "low-score items succeeding). Manual curation may be needed."
                        ),
                        (
                            "Review item trails in `item_scores.json` for items classified "
                            "as `needs_curation`. Consider running `make compact` to evict "
                            "stale items and reset scores."
                        ),
                    )
                )

            if metrics.hitl_escalation_rate > _HITL_HIGH:
                recommendations.append(
                    (
                        "hitl_escalation_rate",
                        metrics.hitl_escalation_rate,
                        (
                            "High HITL escalation rate suggests systematic failures that "
                            "cannot be auto-recovered. Pipeline confidence is degraded."
                        ),
                        (
                            "Review recent `harness_failures.jsonl` entries categorized as "
                            "`hitl_escalation`. Update prompts or constraints to prevent "
                            "the most common escalation causes."
                        ),
                    )
                )

            if metrics.avg_memory_score < _AVG_SCORE_LOW:
                recommendations.append(
                    (
                        "avg_memory_score",
                        metrics.avg_memory_score,
                        (
                            "Average memory item score is critically low, indicating that "
                            "most memory items are not contributing to positive outcomes."
                        ),
                        (
                            "Run a full memory compaction pass to evict low-scoring items. "
                            "Review the memory digest for outdated or conflicting guidance."
                        ),
                    )
                )

            if metrics.stale_item_count > _STALE_COUNT_HIGH:
                recommendations.append(
                    (
                        "stale_item_count",
                        float(metrics.stale_item_count),
                        (
                            f"{metrics.stale_item_count} memory items have score < 0.3 "
                            "with 5+ appearances, indicating persistent low-value content."
                        ),
                        (
                            "Run `make compact` to auto-evict items below the eviction "
                            "threshold. Review remaining low-score items for manual pruning."
                        ),
                    )
                )

            for metric_name, value, observation, recommendation in recommendations:
                try:
                    title = (
                        f"[Health Monitor] {metric_name} at {value:.2f}"
                        " — recommendation"
                    )
                    body = self._build_hitl_body(
                        metric_name=metric_name,
                        value=value,
                        observation=observation,
                        recommendation=recommendation,
                        metrics=metrics,
                    )
                    try:
                        rec = {
                            "title": title,
                            "body": body,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "type": "recommendation",
                        }
                        rec_path = self._config.data_path(
                            "memory", "hitl_recommendations.jsonl"
                        )
                        rec_path.parent.mkdir(parents=True, exist_ok=True)
                        with rec_path.open("a") as f:
                            f.write(json.dumps(rec) + "\n")
                        logger.warning("HITL recommendation: %s", title)
                    except OSError:
                        logger.debug(
                            "Failed to write HITL recommendation", exc_info=True
                        )
                    try:
                        import sentry_sdk  # noqa: PLC0415

                        sentry_sdk.capture_message(
                            f"Health monitor filed HITL recommendation: {metric_name}",
                            level="warning",
                        )
                    except ImportError:
                        pass
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Failed to file HITL recommendation for %s",
                        metric_name,
                        exc_info=True,
                    )
        except Exception:  # noqa: BLE001
            logger.warning("_file_hitl_recommendations failed", exc_info=True)

    def _build_hitl_body(
        self,
        *,
        metric_name: str,
        value: float,
        observation: str,
        recommendation: str,
        metrics: TrendMetrics,
    ) -> str:
        config = self._config
        return (
            f"## Health Monitor Recommendation\n\n"
            f"**Metric:** `{metric_name}` = `{value:.4f}`\n\n"
            f"### Observation\n{observation}\n\n"
            f"### Current Config\n"
            f"- `max_quality_fix_attempts`: {config.max_quality_fix_attempts}\n"
            f"- `agent_timeout`: {config.agent_timeout}\n\n"
            f"### Evidence\n"
            f"- First-pass rate (last 50): `{metrics.first_pass_rate:.2%}`\n"
            f"- Avg memory score: `{metrics.avg_memory_score:.4f}`\n"
            f"- Surprise rate: `{metrics.surprise_rate:.2%}`\n"
            f"- HITL escalation rate: `{metrics.hitl_escalation_rate:.2%}`\n"
            f"- Stale items (score<0.3, ≥5 appearances): `{metrics.stale_item_count}`\n\n"
            f"### Recommendation\n{recommendation}\n"
        )

    # ------------------------------------------------------------------
    # Sentry metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_sentry_metrics(
        metrics: TrendMetrics,
        *,
        gap_count: int = 0,
        adjustment_count: int = 0,
        log_patterns_total: int = 0,
        log_patterns_novel: int = 0,
        log_patterns_escalating: int = 0,
        hitl_recommendations_count: int = 0,
    ) -> None:
        try:
            import sentry_sdk  # noqa: PLC0415

            sentry_sdk.set_measurement("memory.avg_score", metrics.avg_memory_score)
            sentry_sdk.set_measurement(
                "memory.first_pass_rate", metrics.first_pass_rate
            )
            sentry_sdk.set_measurement("memory.surprise_rate", metrics.surprise_rate)
            sentry_sdk.set_measurement(
                "memory.stale_items", float(metrics.stale_item_count)
            )
            sentry_sdk.set_measurement("memory.knowledge_gaps", gap_count)
            sentry_sdk.set_measurement("memory.auto_adjustments", adjustment_count)
            sentry_sdk.set_measurement("memory.log_patterns_total", log_patterns_total)
            sentry_sdk.set_measurement("memory.log_patterns_novel", log_patterns_novel)
            sentry_sdk.set_measurement(
                "memory.log_patterns_escalating", log_patterns_escalating
            )
            sentry_sdk.set_measurement(
                "memory.hitl_recommendations_unactioned",
                hitl_recommendations_count,
            )
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("Sentry metric emission failed", exc_info=True)

    # ------------------------------------------------------------------
    # Dead-man-switch for TrustFleetSanityLoop (spec §12.1)
    # ------------------------------------------------------------------

    async def _check_sanity_loop_staleness(self) -> None:  # noqa: PLR0911
        """Dead-man-switch for `TrustFleetSanityLoop` (spec §12.1).

        When the sanity loop is enabled but its heartbeat is older than
        ``_SANITY_STALL_MULTIPLIER × trust_fleet_sanity_interval``,
        file one `hydraflow-find` + `sanity-loop-stalled` issue per stall
        event. The sanity loop watches the nine trust loops; this
        method watches the sanity loop. Recursion is bounded at one
        meta-layer (spec §12.1 "Bounds of meta-observability").

        ``bg_workers`` is injected post-ctor by the orchestrator
        (chicken-and-egg with BGWorkerManager); ``state`` is passed at
        construction time. When either is missing — as happens in some
        minimal scenario fixtures — this check is a silent no-op so
        production cycles do not spam debug-level exceptions.

        Dedup: filed issues are tracked in ``_sanity_stall_dedup``. The
        key is cleared the next time the sanity loop ticks within the
        threshold, so a subsequent stall files a fresh issue.
        """
        state = self._state
        bg_workers = self._bg_workers
        prs = self._prs
        if state is None or bg_workers is None or prs is None:
            return

        dedup_key = "health_monitor:trust_fleet_sanity:stalled"
        filed_keys = self._sanity_stall_dedup.get()

        hb = state.get_worker_heartbeats().get("trust_fleet_sanity")
        last_run_iso = hb.get("last_run") if isinstance(hb, dict) else None
        enabled = bool(
            getattr(bg_workers, "worker_enabled", {}).get("trust_fleet_sanity", True)
        )
        if not last_run_iso or not enabled:
            return
        try:
            last_run = datetime.fromisoformat(
                last_run_iso.replace("Z", "+00:00"),
            )
        except ValueError:
            return
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=UTC)
        elapsed_s = (datetime.now(UTC) - last_run).total_seconds()
        threshold_s = (
            _SANITY_STALL_MULTIPLIER * self._config.trust_fleet_sanity_interval
        )
        if elapsed_s < threshold_s:
            # Recovery — the sanity loop is ticking again. Clear the
            # dedup so a future stall files a fresh issue.
            if dedup_key in filed_keys:
                self._sanity_stall_dedup.set_all(filed_keys - {dedup_key})
            return
        if dedup_key in filed_keys:
            # Already filed for the current stall event; wait for recovery
            # (or operator-close via issue_close reconcile) before refiling.
            return

        title = (
            f"sanity-loop-stalled: trust_fleet_sanity silent for "
            f"{int(elapsed_s)}s (threshold {int(threshold_s)}s)"
        )
        body = (
            f"## TrustFleetSanityLoop dead-man-switch tripped\n\n"
            f"The meta-observability loop has not ticked in "
            f"`{int(elapsed_s)}s`, exceeding "
            f"`{_SANITY_STALL_MULTIPLIER} × "
            f"trust_fleet_sanity_interval` = `{int(threshold_s)}s` "
            f"(spec §12.1).\n\n"
            f"- Last heartbeat: `{last_run_iso}`\n"
            f"- Interval: "
            f"`{self._config.trust_fleet_sanity_interval}s`\n"
            f"- Enabled: `True`\n\n"
            f"### Operator playbook\n"
            f"1. Check orchestrator logs for the `trust_fleet_sanity` "
            f"loop task (look for uncaught exceptions on the run task).\n"
            f"2. Restart the orchestrator (`systemctl restart hydraflow` "
            f"or equivalent).\n"
            f"3. If the loop continues to stall, flip its "
            f"kill-switch in the **System** tab and file a HydraFlow "
            f"bug report.\n\n"
            f"_Auto-filed by HydraFlow `health_monitor` "
            f"(spec §12.1 dead-man-switch)._"
        )
        await prs.create_issue(
            title,
            body,
            ["hydraflow-find", "sanity-loop-stalled"],
        )
        filed_keys = self._sanity_stall_dedup.get()
        self._sanity_stall_dedup.set_all(filed_keys | {dedup_key})
