"""Confidence calibration — JSONL-backed outcome store + bounded weight adjustment.

Records decision outcomes and calibrates confidence weights based on
whether decisions matched actual post-merge results.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from confidence import ConfidenceWeights
from release_decision import ReleaseAction

logger = logging.getLogger("hydraflow.confidence_calibration")


class DecisionOutcome(BaseModel):
    """Recorded outcome of a release decision."""

    issue_number: int
    pr_number: int
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    action: ReleaseAction
    confidence_score: float
    confidence_rank: str
    risk_score: float
    risk_level: str
    mode: str
    # Post-merge outcomes (filled later)
    verification_passed: bool | None = None
    e2e_passed: bool | None = None
    was_reverted: bool = False
    caused_hitl: bool = False
    was_reworked: bool = False
    outcome_correct: bool | None = None


def compute_outcome_correct(outcome: DecisionOutcome) -> bool | None:
    """Determine if the decision was correct based on actual outcomes.

    Returns True if the merge was clean, False if it caused problems,
    None if we don't have enough data to judge.
    """
    bad_signals = [
        outcome.was_reverted,
        outcome.caused_hitl,
        outcome.was_reworked,
    ]
    if outcome.verification_passed is False:
        bad_signals.append(True)

    if any(bad_signals):
        # Something went wrong — was the decision to merge?
        return outcome.action != ReleaseAction.AUTO_MERGE

    # Nothing went wrong
    if outcome.verification_passed is None and outcome.e2e_passed is None:
        return None  # Not enough signal to judge

    return outcome.action not in (
        ReleaseAction.HOLD_FOR_REVIEW,
        ReleaseAction.ESCALATE_HITL,
        ReleaseAction.REJECT,
    )


class CalibrationStore:
    """JSONL-backed store for decision outcomes and weight calibration."""

    def __init__(self, store_path: Path) -> None:
        self._path = store_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record_outcome(self, outcome: DecisionOutcome) -> None:
        """Append an outcome record to the JSONL store."""
        with self._path.open("a") as f:
            f.write(outcome.model_dump_json() + "\n")

    def load_outcomes(self, limit: int = 500) -> list[DecisionOutcome]:
        """Load recent outcomes from the JSONL store."""
        if not self._path.exists():
            return []
        outcomes: list[DecisionOutcome] = []
        try:
            lines = self._path.read_text().strip().splitlines()
            for line in lines[-limit:]:
                try:
                    outcomes.append(DecisionOutcome.model_validate_json(line))
                except Exception:
                    continue
        except OSError as exc:
            logger.warning("Failed to load calibration store: %s", exc)
        return outcomes

    def update_outcome(
        self,
        pr_number: int,
        *,
        verification_passed: bool | None = None,
        was_reverted: bool | None = None,
        caused_hitl: bool | None = None,
        was_reworked: bool | None = None,
    ) -> bool:
        """Update the most recent outcome for a PR with post-merge data.

        Returns True if an outcome was found and updated.
        """
        outcomes = self.load_outcomes()
        updated = False
        for outcome in reversed(outcomes):
            if outcome.pr_number == pr_number:
                if verification_passed is not None:
                    outcome.verification_passed = verification_passed
                if was_reverted is not None:
                    outcome.was_reverted = was_reverted
                if caused_hitl is not None:
                    outcome.caused_hitl = caused_hitl
                if was_reworked is not None:
                    outcome.was_reworked = was_reworked
                outcome.outcome_correct = compute_outcome_correct(outcome)
                updated = True
                break

        if updated:
            self._rewrite(outcomes)
        return updated

    def _rewrite(self, outcomes: list[DecisionOutcome]) -> None:
        """Rewrite the full store (used after updates)."""
        try:
            with self._path.open("w") as f:
                for o in outcomes:
                    f.write(o.model_dump_json() + "\n")
        except OSError as exc:
            logger.warning("Failed to rewrite calibration store: %s", exc)

    def outcomes_with_judgement(self) -> list[DecisionOutcome]:
        """Return only outcomes where outcome_correct is known."""
        return [o for o in self.load_outcomes() if o.outcome_correct is not None]


def calibrate_weights(
    current: ConfidenceWeights,
    outcomes: list[DecisionOutcome],
    *,
    min_samples: int = 20,
    max_adjustment: float = 0.02,
    weight_floor: float = 0.05,
    weight_ceiling: float = 0.40,
) -> tuple[ConfidenceWeights, dict[str, Any]]:
    """Calibrate confidence weights from decision outcomes.

    Returns (new_weights, stats_dict). If fewer than *min_samples* judged
    outcomes are available, returns the current weights unchanged.

    Safety mechanisms:
    - Bounded weights: each clamped to [weight_floor, weight_ceiling]
    - Max adjustment per cycle: ±max_adjustment per weight
    - Anti-reinforcement: if auto-merge rate > 80% and bad outcomes exist,
      tightens across the board
    """
    judged = [o for o in outcomes if o.outcome_correct is not None]
    stats: dict[str, Any] = {
        "total_outcomes": len(outcomes),
        "judged_outcomes": len(judged),
        "adjusted": False,
    }

    if len(judged) < min_samples:
        stats["skipped_reason"] = (
            f"insufficient samples ({len(judged)} < {min_samples})"
        )
        return current, stats

    correct = sum(1 for o in judged if o.outcome_correct is True)
    accuracy = correct / len(judged) if judged else 0.0
    stats["accuracy"] = accuracy

    # Count bad outcomes by type
    false_positives = sum(
        1
        for o in judged
        if o.outcome_correct is False and o.action == ReleaseAction.AUTO_MERGE
    )
    false_negatives = sum(
        1
        for o in judged
        if o.outcome_correct is False
        and o.action in (ReleaseAction.HOLD_FOR_REVIEW, ReleaseAction.ESCALATE_HITL)
    )
    stats["false_positives"] = false_positives
    stats["false_negatives"] = false_negatives

    # Anti-reinforcement: if system approves most things but has bad outcomes,
    # tighten all weights slightly (make scores lower)
    auto_merges = sum(1 for o in judged if o.action == ReleaseAction.AUTO_MERGE)
    auto_merge_rate = auto_merges / len(judged) if judged else 0.0
    stats["auto_merge_rate"] = auto_merge_rate

    data = current.model_dump()

    if auto_merge_rate > 0.8 and false_positives > 0:
        # Tighten: reduce all weights slightly
        adjustment = -min(
            max_adjustment, max_adjustment * (false_positives / len(judged))
        )
        for key in data:
            data[key] = max(weight_floor, min(weight_ceiling, data[key] + adjustment))
        stats["anti_reinforcement"] = True
        stats["adjustment_direction"] = "tighten"
    elif false_negatives > false_positives:
        # Too conservative: nudge weights up slightly
        adjustment = min(
            max_adjustment, max_adjustment * (false_negatives / len(judged))
        )
        for key in data:
            data[key] = max(weight_floor, min(weight_ceiling, data[key] + adjustment))
        stats["adjustment_direction"] = "loosen"
    elif false_positives > false_negatives:
        # Too aggressive: nudge weights down slightly
        adjustment = -min(
            max_adjustment, max_adjustment * (false_positives / len(judged))
        )
        for key in data:
            data[key] = max(weight_floor, min(weight_ceiling, data[key] + adjustment))
        stats["adjustment_direction"] = "tighten"
    else:
        stats["adjustment_direction"] = "none"
        return current, stats

    stats["adjusted"] = True
    return ConfidenceWeights(**data), stats
