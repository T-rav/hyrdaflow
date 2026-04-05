"""MemoryScorer — outcome recording, item scoring with trails, and noise filtering."""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("hydraflow.memory_scoring")

# ---------------------------------------------------------------------------
# Module-level lock protecting read-modify-write on item_scores.json.
# File I/O is synchronous so threading.Lock is the correct primitive here.
# ---------------------------------------------------------------------------
_SCORES_LOCK = threading.Lock()

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

# Minimum word-overlap ratio to consider a failure "addressed" by a memory item.
_GAP_OVERLAP_THRESHOLD = 0.30
# Minimum occurrences before a gap becomes a suggestion.
_GAP_FREQUENCY_THRESHOLD = 3
# Maximum recent failures to inspect.
_GAP_WINDOW = 50


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
    context: str = "feature"
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


def _classify_context(tags: list[str]) -> str:
    """Classify task into a context bucket for scoring."""
    lower = {t.lower() for t in tags}
    if "bug" in lower or "fix" in lower or "bugfix" in lower:
        return "bugfix"
    if "refactor" in lower or "refactoring" in lower:
        return "refactor"
    if "docs" in lower or "documentation" in lower:
        return "docs"
    return "feature"


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
        logger.info(
            "Recorded outcome for issue #%d: %s (score=%.1f, context=%s, digest=%s)",
            outcome.issue_id,
            outcome.outcome,
            outcome.score,
            outcome.context,
            outcome.digest_hash[:8],
        )
        try:
            import sentry_sdk  # noqa: PLC0415

            sentry_sdk.add_breadcrumb(
                category="memory.outcome",
                message=f"Issue #{outcome.issue_id}: {outcome.outcome} (score={outcome.score})",
                level="info",
                data={
                    "issue_id": outcome.issue_id,
                    "outcome": outcome.outcome,
                    "context": outcome.context,
                },
            )
        except ImportError:
            pass

    def record_merge_outcome(
        self,
        *,
        issue_id: int,
        digest_hash: str,
        quality_fix_attempts: int,
        review_attempts: int,
        tags: list[str],
        issue_title: str = "",
    ) -> None:
        """Record outcome for a successfully merged PR.

        Encapsulates the scoring rule: clean merge (no quality fixes,
        ≤1 review round) scores 1.0/success; otherwise 0.5/partial.
        """
        if quality_fix_attempts == 0 and review_attempts <= 1:
            outcome, score = "success", 1.0
        else:
            outcome, score = "partial", 0.5
        context = _classify_context(tags)
        title_snippet = issue_title[:80] if issue_title else ""
        self.record_outcome(
            OutcomeRecord(
                issue_id=issue_id,
                outcome=outcome,
                score=score,
                digest_hash=digest_hash,
                failure_category=None,
                summary=f"Merged: {title_snippet}" if title_snippet else "Merged",
                context=context,
            )
        )

    def record_hitl_outcome(
        self,
        *,
        issue_id: int,
        digest_hash: str,
        cause: str,
        tags: list[str],
    ) -> None:
        """Record outcome for an issue escalated to HITL."""
        context = _classify_context(tags)
        self.record_outcome(
            OutcomeRecord(
                issue_id=issue_id,
                outcome="failure",
                score=-1.0,
                digest_hash=digest_hash,
                failure_category=cause or "hitl_escalation",
                summary=f"HITL escalation: {cause}",
                context=context,
            )
        )

    def record_failure_outcome(
        self,
        *,
        issue_id: int,
        digest_hash: str,
        failure_category: str,
        summary: str,
        tags: list[str],
    ) -> None:
        """Record outcome for a failed issue (e.g. max attempts exceeded)."""
        context = _classify_context(tags)
        self.record_outcome(
            OutcomeRecord(
                issue_id=issue_id,
                outcome="failure",
                score=-1.0,
                digest_hash=digest_hash,
                failure_category=failure_category,
                summary=summary,
                context=context,
            )
        )

    def update_scores(
        self,
        outcome: OutcomeRecord,
        active_item_ids: list[int],
        item_types: dict[int, str] | None = None,
    ) -> None:
        """Update per-item scores based on a new outcome record."""
        with _SCORES_LOCK:
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
                    logger.debug(
                        "Score update: item %d %s %.2f → %.2f (delta=%.2f, relevant=%s, surprising=%s)",
                        item_id,
                        outcome.outcome,
                        old_score,
                        new_score,
                        delta,
                        relevant,
                        surprising,
                    )

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

                    # Track per-context score in addition to the global score
                    context = outcome.context or "feature"
                    ctx_key = f"ctx_{context}"
                    if ctx_key not in item:
                        item[ctx_key] = {"score": 0.5, "appearances": 0}
                    item[ctx_key]["appearances"] += 1
                    item[ctx_key]["score"] = max(
                        0.0, min(1.0, item[ctx_key]["score"] + delta)
                    )

                scores[item_id] = item

            self._save_item_scores(scores)
            logger.info(
                "Updated scores for %d items on issue #%d outcome=%s",
                len(active_item_ids),
                outcome.issue_id,
                outcome.outcome,
            )

    def apply_temporal_decay(self) -> None:
        """Apply exponential decay toward 0.5 for all item scores."""
        with _SCORES_LOCK:
            scores = self.load_item_scores()
            for _item_id, item in scores.items():
                item["score"] = item["score"] * 0.95 + 0.5 * 0.05
            self._save_item_scores(scores)
        logger.info("Applied temporal decay to %d memory items", len(scores))

    def eviction_candidates(self) -> list[int]:
        """Return item IDs with score < 0.3 and appearances >= 5."""
        scores = self.load_item_scores()
        candidates = [
            item_id
            for item_id, item in scores.items()
            if item["score"] < _EVICT_SCORE_THRESHOLD
            and item["appearances"] >= _EVICT_APPEARANCES_THRESHOLD
        ]
        if candidates:
            logger.warning(
                "Eviction candidates: %s (score < %.2f, appearances >= %d)",
                candidates,
                _EVICT_SCORE_THRESHOLD,
                _EVICT_APPEARANCES_THRESHOLD,
            )
        return candidates

    def classify_for_compaction(self, item_id: int) -> str:
        """Classify an item as 'keep', 'needs_curation', or 'auto_evict'."""
        scores = self.load_item_scores()
        if item_id not in scores:
            return "keep"

        item = scores[item_id]
        score: float = item["score"]
        appearances: int = item.get("appearances", 0)
        trail: list[dict[str, Any]] = item.get("trail", [])

        # Any surprising trail entry means human review is needed
        has_surprising = any(e.get("surprising", False) for e in trail)

        if score < _AUTO_EVICT_SCORE:
            result = "auto_evict"
        elif score < _NEEDS_CURATION_SCORE or has_surprising:
            result = "needs_curation"
        else:
            result = "keep"

        logger.debug(
            "Compaction classification for item %d: %s (score=%.2f, appearances=%d)",
            item_id,
            result,
            score,
            appearances,
        )
        return result

    def get_item_score_for_context(
        self, item_id: int, context: str = "feature"
    ) -> float:
        """Get context-specific score, falling back to global."""
        data = self.load_item_scores()
        key = item_id
        if key not in data:
            return 0.5
        item = data[key]
        ctx_key = f"ctx_{context}"
        if ctx_key in item and item[ctx_key]["appearances"] >= 3:
            return item[ctx_key]["score"]
        return item["score"]  # fall back to global

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


# ---------------------------------------------------------------------------
# Knowledge gap detection
# ---------------------------------------------------------------------------


@dataclass
class KnowledgeGap:
    """A recurring failure pattern not addressed by any existing memory item."""

    failure_category: str
    subcategory: str | None
    frequency: int
    sample_details: list[str] = field(default_factory=list)
    suggested_learning: str = ""


def _tokenize(text: str) -> set[str]:
    """Return the set of lowercased word tokens from *text*.

    Strips punctuation and ignores single-character tokens.
    """
    return {w for w in re.split(r"\W+", text.lower()) if len(w) > 1}


def _word_overlap(text_a: str, text_b: str) -> float:
    """Return the Jaccard-like overlap ratio between two text strings.

    Ratio = |intersection| / |union|. Returns 0.0 when both sets are empty.
    """
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _failure_is_addressed(details: str, memory_texts: list[str]) -> bool:
    """Return True if *details* has >30% word overlap with any memory item text."""
    for mem_text in memory_texts:
        if _word_overlap(details, mem_text) > _GAP_OVERLAP_THRESHOLD:
            return True
    return False


def _synthesize_suggestion(
    failure_category: str,
    subcategory: str | None,
    sample_details: list[str],
    frequency: int,
) -> str:
    """Produce a brief suggested-learning string for a knowledge gap."""
    sub_part = f" ({subcategory})" if subcategory else ""
    details_hint = sample_details[0][:120] if sample_details else ""
    return (
        f"Add a memory item addressing recurring '{failure_category}{sub_part}' failures "
        f"({frequency} unaddressed occurrences). "
        f"Example failure: {details_hint!r}"
    )


def detect_knowledge_gaps(
    failures_path: Path,
    memory_texts: list[str],
    *,
    window: int = _GAP_WINDOW,
    frequency_threshold: int = _GAP_FREQUENCY_THRESHOLD,
    overlap_threshold: float = _GAP_OVERLAP_THRESHOLD,
) -> list[KnowledgeGap]:
    """Detect recurring failure patterns not addressed by existing memory items.

    Args:
        failures_path: Path to ``harness_failures.jsonl``.
        memory_texts: List of text strings — one per memory item — used to
            determine whether a failure is already addressed. Callers may
            pass the full content of each memory item file, or extract the
            ``condensed_summary`` / ``learning`` fields from their storage.
        window: How many recent failures to examine (tail of the file).
        frequency_threshold: Minimum occurrence count for a gap to be returned.
        overlap_threshold: Word-overlap ratio above which a failure is
            considered addressed by an existing memory item.

    Returns:
        A list of :class:`KnowledgeGap` objects, one per
        ``(failure_category, subcategory)`` pair that appears at least
        *frequency_threshold* times without a matching memory item.
        Sorted by frequency descending.
    """
    # ------------------------------------------------------------------
    # 1. Load recent failures
    # ------------------------------------------------------------------
    if not failures_path.exists():
        return []

    try:
        lines = failures_path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []

    tail_lines = lines[-window:] if len(lines) > window else lines

    # Import locally to avoid circular dependency at module level; harness_insights
    # is a sibling module that does not import memory_scoring.
    from harness_insights import FailureRecord  # noqa: PLC0415

    records: list[FailureRecord] = []
    for line in tail_lines:
        try:
            records.append(FailureRecord.model_validate_json(line))
        except Exception:  # noqa: BLE001
            continue  # skip malformed records

    if not records:
        return []

    # ------------------------------------------------------------------
    # 2. Group unaddressed failures by (category, subcategory)
    # ------------------------------------------------------------------
    # key → (category, primary_subcategory | None)
    gap_counts: dict[tuple[str, str | None], int] = defaultdict(int)
    gap_details: dict[tuple[str, str | None], list[str]] = defaultdict(list)

    for record in records:
        if _failure_is_addressed(record.details, memory_texts):
            continue

        # Use the first subcategory (most specific), or None if absent
        primary_sub: str | None = (
            record.subcategories[0] if record.subcategories else None
        )
        key = (str(record.category), primary_sub)
        gap_counts[key] += 1
        if len(gap_details[key]) < 3 and record.details:
            gap_details[key].append(record.details)

    # ------------------------------------------------------------------
    # 3. Return gaps that meet the frequency threshold
    # ------------------------------------------------------------------
    gaps: list[KnowledgeGap] = []
    for (category, subcategory), count in gap_counts.items():
        if count < frequency_threshold:
            continue
        samples = gap_details[(category, subcategory)]
        suggestion = _synthesize_suggestion(category, subcategory, samples, count)
        gaps.append(
            KnowledgeGap(
                failure_category=category,
                subcategory=subcategory,
                frequency=count,
                sample_details=samples,
                suggested_learning=suggestion,
            )
        )

    gaps.sort(key=lambda g: g.frequency, reverse=True)
    if gaps:
        logger.warning(
            "Detected %d knowledge gaps (threshold=%d): %s",
            len(gaps),
            frequency_threshold,
            [g.failure_category for g in gaps],
        )
    return gaps
