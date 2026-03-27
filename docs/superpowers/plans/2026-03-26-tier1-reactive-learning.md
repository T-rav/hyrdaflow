# Tier 1: Reactive Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the memory scoring foundation — outcome tracking, item confidence with score trails, noise filtering, and informed compaction. Also close 6 open feedback loops.

**Architecture:** New `src/memory_scoring.py` module handles all scoring logic. Outcome recording is called from 3 terminal-state sites (post-merge, HITL escalation, max attempts). The scorer updates per-item confidence on each outcome. Compaction integrates scores for keep/rephrase/evict decisions. Loop closures are independent modifications to existing modules.

**Tech Stack:** Python 3.11, Pydantic, asyncio, JSONL storage, existing HydraFlow patterns

**Spec:** `docs/superpowers/specs/2026-03-26-adaptive-memory-scoring-design.md` (Parts 1-10)

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/memory_scoring.py` | **Create** | MemoryScorer class — outcome recording, score updates, decay, eviction |
| `src/post_merge_handler.py` | Modify | Record outcome at merge (success/partial) |
| `src/review_phase.py` | Modify | Record outcome at HITL escalation + store raw feedback |
| `src/implement_phase.py` | Modify | Capture digest hash, record outcome at max attempts |
| `src/state/_issue.py` | Modify | Store digest_hash per issue in state tracker |
| `src/memory.py` | Modify | Integrate scoring into _compact_digest |
| `src/harness_insights.py` | Modify | Auto-file suggestions as issues |
| `src/base_runner.py` | Modify | Recall from all Hindsight banks |
| `src/hitl_phase.py` | Modify | Auto-file memory from correction text |
| `src/transcript_summarizer.py` | Modify | Parse and file patterns/insights |
| `src/models.py` | Modify | Add raw_feedback to ReviewRecord |
| `src/review_insights.py` | Modify | Verification tracking |
| `tests/test_memory_scoring.py` | **Create** | Full scorer test suite |
| `tests/test_memory_loops.py` | **Create** | Integration tests for loop closures |

---

### Task 1: Create MemoryScorer with Outcome Recording

**Bead:** ops-audit-fixes-0lm (P0)
**Files:**
- Create: `src/memory_scoring.py`
- Create: `tests/test_memory_scoring.py`

- [ ] **Step 1: Write failing tests for outcome recording**

```python
"""Tests for memory scoring system."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memory_scoring import MemoryScorer, OutcomeRecord


class TestRecordOutcome:
    def test_appends_to_outcomes_jsonl(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        scorer.record_outcome(OutcomeRecord(
            issue_id=42, outcome="success", score=1.0,
            digest_hash="abc123", failure_category=None,
            summary="PR merged first-pass",
        ))
        outcomes = scorer.load_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0]["issue_id"] == 42
        assert outcomes[0]["outcome"] == "success"

    def test_multiple_outcomes_append(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        scorer.record_outcome(OutcomeRecord(
            issue_id=42, outcome="success", score=1.0,
            digest_hash="abc", failure_category=None, summary="OK",
        ))
        scorer.record_outcome(OutcomeRecord(
            issue_id=43, outcome="failure", score=-1.0,
            digest_hash="abc", failure_category="quality_gate", summary="Failed",
        ))
        assert len(scorer.load_outcomes()) == 2

    def test_creates_memory_dir_if_missing(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "nonexistent" / "memory")
        scorer.record_outcome(OutcomeRecord(
            issue_id=1, outcome="success", score=1.0,
            digest_hash="x", failure_category=None, summary="OK",
        ))
        assert (tmp_path / "nonexistent" / "memory" / "outcomes.jsonl").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_scoring.py::TestRecordOutcome -v`

- [ ] **Step 3: Implement MemoryScorer and OutcomeRecord**

Create `src/memory_scoring.py`:

```python
"""Memory scoring system — tracks outcomes and scores memory items."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("hydraflow.memory_scoring")


class OutcomeRecord(BaseModel):
    """A terminal outcome for an issue."""
    issue_id: int
    outcome: Literal["success", "partial", "failure"]
    score: float
    digest_hash: str
    failure_category: str | None = None
    summary: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class TrailEntry(BaseModel):
    """A single score update in an item's trail."""
    issue: int
    outcome: str
    delta: float
    summary: str
    surprising: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ItemScore(BaseModel):
    """Confidence score for a single memory item."""
    score: float = 0.5
    appearances: int = 0
    last_updated: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    memory_type: str = "knowledge"
    trail: list[dict[str, Any]] = Field(default_factory=list)


class MemoryScorer:
    """Tracks memory item confidence based on pipeline outcomes."""

    _OUTCOMES_FILE = "outcomes.jsonl"
    _SCORES_FILE = "item_scores.json"
    _MAX_TRAIL = 10
    _DECAY_FACTOR = 0.95
    _DECAY_CENTER = 0.5

    def __init__(self, memory_dir: Path) -> None:
        self._dir = memory_dir

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    # --- Outcome recording ---

    def record_outcome(self, record: OutcomeRecord) -> None:
        """Append an outcome record to outcomes.jsonl."""
        self._ensure_dir()
        path = self._dir / self._OUTCOMES_FILE
        with path.open("a") as f:
            f.write(record.model_dump_json() + "\n")
        logger.info(
            "Recorded outcome for issue #%d: %s (score=%.1f)",
            record.issue_id, record.outcome, record.score,
        )

    def load_outcomes(self, limit: int = 0) -> list[dict[str, Any]]:
        """Load outcome records from JSONL. If limit > 0, return last N."""
        path = self._dir / self._OUTCOMES_FILE
        if not path.exists():
            return []
        lines = path.read_text().strip().splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        if limit > 0:
            records = records[-limit:]
        return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_scoring.py::TestRecordOutcome -v`

- [ ] **Step 5: Lint and commit**

```bash
make lint
bd update ops-audit-fixes-0lm --status in_progress
git add src/memory_scoring.py tests/test_memory_scoring.py
git commit -m "Add MemoryScorer with outcome recording (Tier 1, Part 1)"
```

---

### Task 2: Item Score Updates with Trail

**Bead:** ops-audit-fixes-6l1 (P0)
**Files:**
- Modify: `src/memory_scoring.py`
- Modify: `tests/test_memory_scoring.py`

- [ ] **Step 1: Write failing tests for score updates**

```python
class TestUpdateScores:
    def test_success_increases_score(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        outcome = OutcomeRecord(
            issue_id=42, outcome="success", score=1.0,
            digest_hash="abc", failure_category=None, summary="OK",
        )
        scorer.update_scores(outcome, active_item_ids=[1, 2])
        assert scorer.get_item_score(1) > 0.5  # default is 0.5

    def test_failure_decreases_score(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        outcome = OutcomeRecord(
            issue_id=42, outcome="failure", score=-1.0,
            digest_hash="abc", failure_category="quality_gate", summary="Failed",
        )
        scorer.update_scores(outcome, active_item_ids=[1])
        assert scorer.get_item_score(1) < 0.5

    def test_trail_records_entry(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        outcome = OutcomeRecord(
            issue_id=42, outcome="success", score=1.0,
            digest_hash="abc", failure_category=None, summary="Merged OK",
        )
        scorer.update_scores(outcome, active_item_ids=[1])
        trail = scorer.get_score_trail(1)
        assert len(trail) == 1
        assert trail[0]["issue"] == 42
        assert trail[0]["summary"] == "Merged OK"

    def test_score_clamped_to_bounds(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        # Push score to max
        for i in range(20):
            scorer.update_scores(OutcomeRecord(
                issue_id=i, outcome="success", score=1.0,
                digest_hash="abc", failure_category=None, summary="OK",
            ), active_item_ids=[1])
        assert scorer.get_item_score(1) <= 1.0

    def test_surprise_flag_on_high_score_failure(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        # Build up high score first
        for i in range(10):
            scorer.update_scores(OutcomeRecord(
                issue_id=i, outcome="success", score=1.0,
                digest_hash="abc", failure_category=None, summary="OK",
            ), active_item_ids=[1])
        # Now a failure should be surprising
        scorer.update_scores(OutcomeRecord(
            issue_id=99, outcome="failure", score=-1.0,
            digest_hash="abc", failure_category="quality_gate", summary="Failed",
        ), active_item_ids=[1])
        trail = scorer.get_score_trail(1)
        last = trail[-1]
        assert last["surprising"] is True

    def test_trail_condensed_at_max(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        for i in range(15):
            scorer.update_scores(OutcomeRecord(
                issue_id=i, outcome="success", score=1.0,
                digest_hash="abc", failure_category=None, summary=f"Issue {i}",
            ), active_item_ids=[1])
        trail = scorer.get_score_trail(1)
        # Should have condensed entry + recent entries, total <= MAX_TRAIL + 1
        assert len(trail) <= scorer._MAX_TRAIL + 1
        assert any(e.get("condensed") for e in trail)


class TestTemporalDecay:
    def test_decay_moves_toward_center(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        # Set up a high-scoring item
        for i in range(10):
            scorer.update_scores(OutcomeRecord(
                issue_id=i, outcome="success", score=1.0,
                digest_hash="abc", failure_category=None, summary="OK",
            ), active_item_ids=[1])
        before = scorer.get_item_score(1)
        scorer.apply_temporal_decay()
        after = scorer.get_item_score(1)
        assert after < before  # moved toward 0.5
        assert after > 0.5  # but still above center

    def test_decay_on_low_score_moves_up(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        for i in range(10):
            scorer.update_scores(OutcomeRecord(
                issue_id=i, outcome="failure", score=-1.0,
                digest_hash="abc", failure_category="quality_gate", summary="Failed",
            ), active_item_ids=[1])
        before = scorer.get_item_score(1)
        scorer.apply_temporal_decay()
        after = scorer.get_item_score(1)
        assert after > before  # moved toward 0.5


class TestEvictionCandidates:
    def test_low_score_with_enough_appearances(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        for i in range(6):
            scorer.update_scores(OutcomeRecord(
                issue_id=i, outcome="failure", score=-1.0,
                digest_hash="abc", failure_category="quality_gate", summary="Failed",
            ), active_item_ids=[1])
        candidates = scorer.get_eviction_candidates()
        assert 1 in candidates

    def test_low_score_insufficient_appearances_not_evicted(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        for i in range(3):
            scorer.update_scores(OutcomeRecord(
                issue_id=i, outcome="failure", score=-1.0,
                digest_hash="abc", failure_category="quality_gate", summary="Failed",
            ), active_item_ids=[1])
        candidates = scorer.get_eviction_candidates()
        assert 1 not in candidates

    def test_high_score_not_evicted(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        for i in range(10):
            scorer.update_scores(OutcomeRecord(
                issue_id=i, outcome="success", score=1.0,
                digest_hash="abc", failure_category=None, summary="OK",
            ), active_item_ids=[1])
        candidates = scorer.get_eviction_candidates()
        assert 1 not in candidates
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement update_scores, get_item_score, apply_temporal_decay, get_eviction_candidates, get_score_trail**

Add to `MemoryScorer` in `src/memory_scoring.py`:

```python
    # --- Score management ---

    def _load_scores(self) -> dict[str, Any]:
        path = self._dir / self._SCORES_FILE
        if not path.exists():
            return {"items": {}}
        return json.loads(path.read_text())

    def _save_scores(self, data: dict[str, Any]) -> None:
        self._ensure_dir()
        path = self._dir / self._SCORES_FILE
        path.write_text(json.dumps(data, indent=2))

    def _get_or_create_item(self, data: dict, item_id: int) -> dict:
        key = str(item_id)
        if key not in data["items"]:
            data["items"][key] = ItemScore().model_dump()
        return data["items"][key]

    def update_scores(
        self, outcome: OutcomeRecord, active_item_ids: list[int],
    ) -> None:
        """Update scores for all items that were in the digest during this outcome."""
        data = self._load_scores()
        delta_map = {"success": 0.1, "partial": 0.05, "failure": -0.1}
        delta = delta_map.get(outcome.outcome, 0.0)

        for item_id in active_item_ids:
            item = self._get_or_create_item(data, item_id)
            item["appearances"] += 1

            old_score = item["score"]
            new_score = max(0.0, min(1.0, old_score + delta))
            item["score"] = new_score
            item["last_updated"] = datetime.now(UTC).isoformat()

            surprising = (
                (old_score > 0.7 and outcome.outcome == "failure")
                or (old_score < 0.3 and outcome.outcome == "success")
            )

            entry = TrailEntry(
                issue=outcome.issue_id,
                outcome=outcome.outcome,
                delta=delta,
                summary=outcome.summary,
                surprising=surprising,
            ).model_dump()

            item["trail"].append(entry)
            self._condense_trail(item)

        self._save_scores(data)

    def _condense_trail(self, item: dict) -> None:
        trail = item["trail"]
        if len(trail) <= self._MAX_TRAIL:
            return
        # Condense oldest entries into a summary
        to_condense = trail[: len(trail) - self._MAX_TRAIL + 1]
        remaining = trail[len(trail) - self._MAX_TRAIL + 1 :]
        successes = sum(1 for e in to_condense if e.get("outcome") == "success")
        failures = sum(1 for e in to_condense if e.get("outcome") == "failure")
        partials = sum(1 for e in to_condense if e.get("outcome") == "partial")
        issues = [e.get("issue", 0) for e in to_condense]
        condensed = {
            "condensed": True,
            "successes": successes,
            "failures": failures,
            "partials": partials,
            "period": f"issues #{min(issues)}-#{max(issues)}" if issues else "",
        }
        item["trail"] = [condensed] + remaining

    def get_item_score(self, item_id: int) -> float:
        data = self._load_scores()
        key = str(item_id)
        if key not in data["items"]:
            return 0.5
        return data["items"][key]["score"]

    def get_score_trail(self, item_id: int) -> list[dict[str, Any]]:
        data = self._load_scores()
        key = str(item_id)
        if key not in data["items"]:
            return []
        return data["items"][key]["trail"]

    def apply_temporal_decay(self) -> None:
        """Decay all scores toward center (0.5)."""
        data = self._load_scores()
        for item in data["items"].values():
            item["score"] = (
                item["score"] * self._DECAY_FACTOR
                + self._DECAY_CENTER * (1 - self._DECAY_FACTOR)
            )
        self._save_scores(data)

    def get_eviction_candidates(
        self, min_appearances: int = 5, threshold: float = 0.3,
    ) -> list[int]:
        """Return item IDs eligible for eviction."""
        data = self._load_scores()
        candidates = []
        for key, item in data["items"].items():
            if item["appearances"] >= min_appearances and item["score"] < threshold:
                candidates.append(int(key))
        return candidates
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_memory_scoring.py -v`

- [ ] **Step 5: Lint and commit**

```bash
make lint
bd update ops-audit-fixes-0lm --status closed
bd update ops-audit-fixes-6l1 --status closed
git add src/memory_scoring.py tests/test_memory_scoring.py
git commit -m "Add item confidence scoring with trails, decay, and eviction (Tier 1, Parts 1-2)"
```

---

### Task 3: Noise Filtering Matrix

**Bead:** ops-audit-fixes-1cz (P0)
**Files:**
- Modify: `src/memory_scoring.py`
- Modify: `tests/test_memory_scoring.py`

- [ ] **Step 1: Write failing tests**

```python
class TestNoiseFiltering:
    def test_code_item_not_scored_on_ci_failure(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        outcome = OutcomeRecord(
            issue_id=42, outcome="failure", score=-1.0,
            digest_hash="abc", failure_category="ci_failure", summary="CI broke",
        )
        scorer.update_scores(outcome, active_item_ids=[1], item_types={1: "code"})
        # Score should remain at default (0.5) — ci_failure is irrelevant to code items
        assert scorer.get_item_score(1) == 0.5

    def test_code_item_scored_on_quality_gate(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        outcome = OutcomeRecord(
            issue_id=42, outcome="failure", score=-1.0,
            digest_hash="abc", failure_category="quality_gate", summary="Lint failed",
        )
        scorer.update_scores(outcome, active_item_ids=[1], item_types={1: "code"})
        assert scorer.get_item_score(1) < 0.5  # was scored

    def test_instruction_item_scored_on_everything(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        outcome = OutcomeRecord(
            issue_id=42, outcome="failure", score=-1.0,
            digest_hash="abc", failure_category="ci_failure", summary="CI broke",
        )
        scorer.update_scores(outcome, active_item_ids=[1], item_types={1: "instruction"})
        assert scorer.get_item_score(1) < 0.5  # instructions are always scored

    def test_success_always_scores_regardless_of_type(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        outcome = OutcomeRecord(
            issue_id=42, outcome="success", score=1.0,
            digest_hash="abc", failure_category=None, summary="OK",
        )
        scorer.update_scores(outcome, active_item_ids=[1], item_types={1: "code"})
        assert scorer.get_item_score(1) > 0.5

    def test_irrelevant_failure_still_increments_appearances(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        outcome = OutcomeRecord(
            issue_id=42, outcome="failure", score=-1.0,
            digest_hash="abc", failure_category="ci_failure", summary="CI",
        )
        scorer.update_scores(outcome, active_item_ids=[1], item_types={1: "code"})
        data = scorer._load_scores()
        assert data["items"]["1"]["appearances"] == 1  # appeared but not judged
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Add item_types parameter and RELEVANCE_MATRIX to update_scores**

Add to `src/memory_scoring.py`:

```python
RELEVANCE_MATRIX: dict[str, set[str] | None] = {
    "code": {"quality_gate", "review_rejection", "implementation_error"},
    "config": {"ci_failure", "quality_gate"},
    "instruction": None,  # scored on everything
    "knowledge": {"plan_validation", "review_rejection"},
}

def _is_relevant(self, item_type: str, failure_category: str | None) -> bool:
    """Check if a failure category is relevant to a memory type."""
    if failure_category is None:  # success — always relevant
        return True
    relevant = RELEVANCE_MATRIX.get(item_type)
    if relevant is None:  # instruction type or unknown — always relevant
        return True
    return failure_category in relevant
```

Update `update_scores` signature to accept `item_types: dict[int, str] | None = None` and use `_is_relevant` to gate the delta application (but always increment appearances).

- [ ] **Step 4: Run tests**
- [ ] **Step 5: Lint and commit**

```bash
bd update ops-audit-fixes-1cz --status closed
git add src/memory_scoring.py tests/test_memory_scoring.py
git commit -m "Add noise filtering matrix — memory type x failure category (Tier 1, Part 3)"
```

---

### Task 4: Wire Outcome Recording into Pipeline

**Bead:** ops-audit-fixes-0lm (P0) — wiring
**Files:**
- Modify: `src/post_merge_handler.py`
- Modify: `src/review_phase.py`
- Modify: `src/implement_phase.py`
- Modify: `src/state/_issue.py`

- [ ] **Step 1: Add digest_hash storage to state tracker**

In `src/state/_issue.py`, add methods to store/retrieve the digest hash per issue:

```python
def set_digest_hash(self, issue_number: int, digest_hash: str) -> None:
    """Store the memory digest hash active when this issue started implementation."""
    ...

def get_digest_hash(self, issue_number: int) -> str:
    """Retrieve the memory digest hash for this issue."""
    ...
```

- [ ] **Step 2: Capture digest hash in implement_phase.py**

Before calling the agent, hash digest.md and store via state tracker.

- [ ] **Step 3: Record outcome in post_merge_handler.py**

After successful merge, compute outcome from quality_fix_rounds and review cycles:

```python
from memory_scoring import MemoryScorer, OutcomeRecord

quality_fix_rounds = result.quality_fix_attempts or 0
review_cycles = result.pre_quality_review_attempts or 0
if quality_fix_rounds == 0 and review_cycles <= 1:
    outcome, score = "success", 1.0
else:
    outcome, score = "partial", 0.5

scorer = MemoryScorer(self._config.memory_dir)
scorer.record_outcome(OutcomeRecord(
    issue_id=pr.issue_number,
    outcome=outcome,
    score=score,
    digest_hash=self._state.get_digest_hash(pr.issue_number),
    failure_category=None,
    summary=f"Merged: {issue.title[:80]}",
))
```

- [ ] **Step 4: Record outcome in review_phase.py at HITL escalation**

In `_escalate_to_hitl()`:

```python
scorer = MemoryScorer(self._config.memory_dir)
scorer.record_outcome(OutcomeRecord(
    issue_id=esc.issue_number,
    outcome="failure",
    score=-1.0,
    digest_hash=self._state.get_digest_hash(esc.issue_number),
    failure_category=esc.cause,
    summary=f"HITL escalation: {esc.cause}",
))
```

- [ ] **Step 5: Record outcome in implement_phase.py at max attempts**

When max_issue_attempts is exceeded.

- [ ] **Step 6: Write integration tests**
- [ ] **Step 7: Lint and commit**

```bash
git add src/post_merge_handler.py src/review_phase.py src/implement_phase.py src/state/_issue.py
git commit -m "Wire outcome recording into pipeline terminal states (Tier 1, Part 1 wiring)"
```

---

### Task 5: Informed Compaction

**Bead:** ops-audit-fixes-1sx (P0)
**Files:**
- Modify: `src/memory.py`
- Modify: `src/memory_scoring.py`
- Modify: `tests/test_memory_scoring.py`

- [ ] **Step 1: Write tests for curation logic**

```python
class TestInformedCompaction:
    def test_auto_evict_very_low_score_high_appearances(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "memory")
        # Simulate item with score < 0.15 and 10+ appearances
        # Should be auto-evicted without model call
        ...

    def test_low_score_sends_to_curation(self, tmp_path: Path) -> None:
        # score < 0.3, appearances >= 5
        # Should return "needs_curation" not "auto_evict"
        ...

    def test_high_score_kept(self, tmp_path: Path) -> None:
        # score > 0.3
        # Should return "keep"
        ...

    def test_surprising_items_flagged_for_curation(self, tmp_path: Path) -> None:
        # Item with surprising=True in recent trail
        # Should be flagged even if score is OK
        ...
```

- [ ] **Step 2: Implement curation classification in MemoryScorer**

```python
def classify_for_compaction(self, item_id: int) -> str:
    """Return 'keep', 'needs_curation', or 'auto_evict'."""
    data = self._load_scores()
    key = str(item_id)
    if key not in data["items"]:
        return "keep"
    item = data["items"][key]
    score = item["score"]
    appearances = item["appearances"]
    trail = item["trail"]

    # Auto-evict: confidently useless
    if score < 0.15 and appearances >= 10:
        return "auto_evict"

    # Needs curation: low score with enough data
    if score < 0.3 and appearances >= 5:
        return "needs_curation"

    # Needs curation: surprising recent outcomes
    recent = [e for e in trail[-3:] if not e.get("condensed")]
    if any(e.get("surprising") for e in recent):
        return "needs_curation"

    return "keep"

def build_curation_prompt(self, item_id: int, item_content: str) -> str:
    """Build a prompt for the curation model to decide keep/rephrase/evict."""
    ...
```

- [ ] **Step 3: Integrate into memory.py _compact_digest**

In `src/memory.py`, in `_compact_digest()`, after keyword dedup and before model summarization, add the curation step that calls `MemoryScorer.classify_for_compaction()` for each item.

- [ ] **Step 4: Run tests, lint, commit**

```bash
bd update ops-audit-fixes-1sx --status closed
git add src/memory.py src/memory_scoring.py tests/test_memory_scoring.py
git commit -m "Add informed compaction with score-based curation (Tier 1, Part 4)"
```

---

### Task 6: Close Loop — Harness Insights Auto-File

**Bead:** ops-audit-fixes-arn (P1)
**Files:**
- Modify: `src/harness_insights.py`
- Create or modify: `tests/test_memory_loops.py`

- [ ] **Step 1: Write test**

```python
class TestHarnessInsightsAutoFile:
    @pytest.mark.asyncio
    async def test_files_suggestion_as_issue(self, tmp_path: Path) -> None:
        # Setup harness store with enough failures to generate a suggestion
        # Mock prs.create_issue
        # Call the auto-file function
        # Assert create_issue was called with [Harness Insight] title
        ...

    @pytest.mark.asyncio
    async def test_dedup_prevents_refiling(self, tmp_path: Path) -> None:
        # File once, then try again
        # Assert create_issue only called once
        ...
```

- [ ] **Step 2: Add auto_file_suggestions() to harness_insights.py**
- [ ] **Step 3: Wire into the metrics sync loop or a dedicated call site**
- [ ] **Step 4: Test, lint, commit**

```bash
bd update ops-audit-fixes-arn --status closed
git commit -m "Close loop: auto-file harness insight suggestions as GitHub issues"
```

---

### Task 7: Close Loop — Hindsight Recall All 5 Banks

**Bead:** ops-audit-fixes-o06 (P1)
**Files:**
- Modify: `src/base_runner.py`

- [ ] **Step 1: Write test**
- [ ] **Step 2: Add recall for retrospectives + troubleshooting banks in _inject_manifest_and_memory()**
- [ ] **Step 3: Cap total at max_memory_prompt_chars with priority ordering**
- [ ] **Step 4: Test, lint, commit**

```bash
bd update ops-audit-fixes-o06 --status closed
git commit -m "Close loop: recall from all 5 Hindsight banks in prompt injection"
```

---

### Task 8: Close Loop — HITL Correction Learning

**Bead:** ops-audit-fixes-0n1 (P1)
**Files:**
- Modify: `src/hitl_phase.py`

- [ ] **Step 1: Write test — successful HITL correction files memory issue**
- [ ] **Step 2: After HITL success, call safe_file_memory_suggestion with correction text**
- [ ] **Step 3: Test, lint, commit**

```bash
bd update ops-audit-fixes-0n1 --status closed
git commit -m "Close loop: auto-file memory from HITL correction text"
```

---

### Task 9: Close Loop — Transcript Summary Parsing

**Bead:** ops-audit-fixes-btn (P2)
**Files:**
- Modify: `src/transcript_summarizer.py`

- [ ] **Step 1: Write test — extract Patterns Discovered and file as memory**
- [ ] **Step 2: Parse structured sections from summary, file as [Memory] issues**
- [ ] **Step 3: Rate-limit to max 3 items per transcript**
- [ ] **Step 4: Test, lint, commit**

```bash
bd update ops-audit-fixes-btn --status closed
git commit -m "Close loop: extract transcript insights into memory items"
```

---

### Task 10: Close Loop — Review Rejection Detail Capture

**Bead:** ops-audit-fixes-du2 (P2)
**Files:**
- Modify: `src/models.py`
- Modify: `src/review_phase.py`

- [ ] **Step 1: Add raw_feedback field to ReviewRecord**
- [ ] **Step 2: Populate in _record_review_insight()**
- [ ] **Step 3: Test, lint, commit**

```bash
bd update ops-audit-fixes-du2 --status closed
git commit -m "Close loop: store raw reviewer feedback text in ReviewRecord"
```

---

### Task 11: Close Loop — Improvement Proposal Verification

**Bead:** ops-audit-fixes-vo3 (P2)
**Files:**
- Modify: `src/review_insights.py`

- [ ] **Step 1: Store pre_count at filing time in proposed_categories.json**
- [ ] **Step 2: During analysis, check if pattern frequency decreased since proposal**
- [ ] **Step 3: Re-file as HITL if unchanged after 30 days**
- [ ] **Step 4: Test, lint, commit**

```bash
bd update ops-audit-fixes-vo3 --status closed
git commit -m "Close loop: verify improvement proposals reduced pattern frequency"
```

---

## Verification

After all tasks:

- [ ] Run `make quality` — full suite
- [ ] Run `bd list` — all Tier 1 beads closed
- [ ] Verify outcomes.jsonl created after mock pipeline run
- [ ] Verify item_scores.json updated after outcome recording
- [ ] Verify eviction candidates identified for low-scoring items
