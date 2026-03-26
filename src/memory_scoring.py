"""MemoryScorer — outcome recording, item scoring with trails, and noise filtering."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Relevance matrix: memory type -> set of relevant failure categories.
# None means "always relevant" (matches everything).
# ---------------------------------------------------------------------------
RELEVANCE_MATRIX: dict[str, list[str] | None] = {
    "code": ["quality_gate", "review_rejection", "implementation_error"],
    "config": ["ci_failure", "quality_gate"],
    "instruction": None,  # always relevant
    "knowledge": ["plan_validation", "review_rejection"],
}

_TRAIL_MAX = 10
_SCORE_DEFAULT = 0.5
_DELTA_SUCCESS = 0.1
_DELTA_PARTIAL = 0.05
_DELTA_FAILURE = -0.1
_EVICT_SCORE_THRESHOLD = 0.3
_EVICT_APPEARANCES_THRESHOLD = 5
_SURPRISE_HIGH = 0.7
_SURPRISE_LOW = 0.3
_AUTO_EVICT_SCORE = 0.2
_NEEDS_CURATION_SCORE = 0.4


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class OutcomeRecord(BaseModel):
    issue_id: int
    outcome: Literal["success", "partial", "failure"]
    score: float
    digest_hash: str
    failure_category: str | None = None
    summary: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class TrailEntry(BaseModel):
    issue: int
    outcome: str
    delta: float
    summary: str
    surprising: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ---------------------------------------------------------------------------
# Internal item score record (plain dict stored in JSON)
# ---------------------------------------------------------------------------

ItemScore = dict[str, Any]  # {score, appearances, trail, condensed_summary}


def _default_item_score() -> ItemScore:
    return {
        "score": _SCORE_DEFAULT,
        "appearances": 0,
        "trail": [],
        "condensed_summary": "",
    }


# ---------------------------------------------------------------------------
# MemoryScorer
# ---------------------------------------------------------------------------


class MemoryScorer:
    """Scores memory items based on outcome records."""

    def __init__(self, memory_dir: Path) -> None:
        self._dir = Path(memory_dir)
        self._outcomes_file = self._dir / "outcomes.jsonl"
        self._scores_file = self._dir / "item_scores.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_outcome(self, outcome: OutcomeRecord) -> None:
        """Append an outcome record to outcomes.jsonl."""
        self._dir.mkdir(parents=True, exist_ok=True)
        with self._outcomes_file.open("a", encoding="utf-8") as fh:
            fh.write(outcome.model_dump_json() + "\n")

    def update_scores(
        self,
        outcome: OutcomeRecord,
        active_item_ids: list[int],
        item_types: dict[int, str] | None = None,
    ) -> None:
        """Update per-item scores based on a new outcome record."""
        scores = self.load_item_scores()

        for item_id in active_item_ids:
            item = scores.get(item_id, _default_item_score())

            # Determine whether the failure is relevant for this item
            relevant = self._is_relevant(outcome, item_id, item_types)

            # Always increment appearances
            item["appearances"] = item.get("appearances", 0) + 1

            if relevant:
                old_score: float = item["score"]
                delta = self._delta_for_outcome(outcome.outcome)
                new_score = max(0.0, min(1.0, old_score + delta))

                # Surprise detection (evaluate before updating score)
                surprising = (
                    old_score > _SURPRISE_HIGH and outcome.outcome == "failure"
                ) or (old_score < _SURPRISE_LOW and outcome.outcome == "success")

                item["score"] = new_score

                trail_entry = TrailEntry(
                    issue=outcome.issue_id,
                    outcome=outcome.outcome,
                    delta=delta,
                    summary=outcome.summary,
                    surprising=surprising,
                ).model_dump()

                trail: list[dict[str, Any]] = item.get("trail", [])
                trail.append(trail_entry)

                if len(trail) > _TRAIL_MAX:
                    # Condense oldest entries into summary
                    condensed = trail[: len(trail) - _TRAIL_MAX]
                    item["condensed_summary"] = self._condense(
                        item.get("condensed_summary", ""), condensed
                    )
                    trail = trail[len(trail) - _TRAIL_MAX :]

                item["trail"] = trail

            scores[item_id] = item

        self._save_item_scores(scores)

    def apply_temporal_decay(self) -> None:
        """Apply exponential decay toward 0.5 for all item scores."""
        scores = self.load_item_scores()
        for _item_id, item in scores.items():
            item["score"] = item["score"] * 0.95 + 0.5 * 0.05
        self._save_item_scores(scores)

    def eviction_candidates(self) -> list[int]:
        """Return item IDs with score < 0.3 and appearances >= 5."""
        scores = self.load_item_scores()
        return [
            item_id
            for item_id, item in scores.items()
            if item["score"] < _EVICT_SCORE_THRESHOLD
            and item["appearances"] >= _EVICT_APPEARANCES_THRESHOLD
        ]

    def classify_for_compaction(self, item_id: int) -> str:
        """Classify an item as 'keep', 'needs_curation', or 'auto_evict'."""
        scores = self.load_item_scores()
        if item_id not in scores:
            return "keep"

        item = scores[item_id]
        score: float = item["score"]
        trail: list[dict[str, Any]] = item.get("trail", [])

        # Any surprising trail entry means human review is needed
        has_surprising = any(e.get("surprising", False) for e in trail)

        if score < _AUTO_EVICT_SCORE:
            return "auto_evict"
        if score < _NEEDS_CURATION_SCORE or has_surprising:
            return "needs_curation"
        return "keep"

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def load_item_scores(self) -> dict[int, ItemScore]:
        """Load item scores from JSON, keyed by integer item ID."""
        if not self._scores_file.exists():
            return {}
        raw: dict[str, Any] = json.loads(self._scores_file.read_text(encoding="utf-8"))
        return {int(k): v for k, v in raw.items()}

    def _save_item_scores(self, scores: dict[int, ItemScore]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        serialisable = {str(k): v for k, v in scores.items()}
        self._scores_file.write_text(
            json.dumps(serialisable, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _delta_for_outcome(outcome: str) -> float:
        if outcome == "success":
            return _DELTA_SUCCESS
        if outcome == "partial":
            return _DELTA_PARTIAL
        return _DELTA_FAILURE

    @staticmethod
    def _is_relevant(
        outcome: OutcomeRecord,
        item_id: int,
        item_types: dict[int, str] | None,
    ) -> bool:
        """Return True if the outcome should affect this item's score."""
        # Success always scores
        if outcome.outcome == "success":
            return True

        # No type information → always relevant
        if item_types is None:
            return True

        item_type = item_types.get(item_id)
        if item_type is None:
            return True

        relevant_categories = RELEVANCE_MATRIX.get(item_type)
        if relevant_categories is None:
            # instruction type — always relevant
            return True

        # Relevant only if the failure category is in the allowed set
        return outcome.failure_category in relevant_categories

    @staticmethod
    def _condense(existing_summary: str, entries: list[dict[str, Any]]) -> str:
        """Condense older trail entries into a short summary string."""
        parts = []
        if existing_summary:
            parts.append(existing_summary)
        for e in entries:
            parts.append(f"{e['outcome']}(issue={e['issue']},Δ={e['delta']:+.2f})")
        return "; ".join(parts)
