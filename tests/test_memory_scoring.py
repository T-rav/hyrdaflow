"""Tests for MemoryScorer — outcome recording, item scoring, noise filtering, compaction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memory_scoring import MemoryScorer, OutcomeRecord  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outcome(
    issue_id: int = 1,
    outcome: str = "success",
    score: float = 1.0,
    digest_hash: str = "abc123",
    failure_category: str | None = None,
    summary: str = "PR merged",
) -> OutcomeRecord:
    return OutcomeRecord(
        issue_id=issue_id,
        outcome=outcome,  # type: ignore[arg-type]
        score=score,
        digest_hash=digest_hash,
        failure_category=failure_category,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# TestRecordOutcome
# ---------------------------------------------------------------------------


class TestRecordOutcome:
    def test_appends_jsonl(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / ".hydraflow" / "memory")
        rec = _make_outcome(issue_id=42)
        scorer.record_outcome(rec)

        out_file = tmp_path / ".hydraflow" / "memory" / "outcomes.jsonl"
        assert out_file.exists()
        lines = out_file.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["issue_id"] == 42
        assert data["outcome"] == "success"
        assert data["digest_hash"] == "abc123"

    def test_multiple_records_each_on_own_line(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / ".hydraflow" / "memory")
        scorer.record_outcome(_make_outcome(issue_id=1))
        scorer.record_outcome(_make_outcome(issue_id=2))
        scorer.record_outcome(_make_outcome(issue_id=3))

        lines = (
            (tmp_path / ".hydraflow" / "memory" / "outcomes.jsonl")
            .read_text()
            .strip()
            .splitlines()
        )
        assert len(lines) == 3
        ids = [json.loads(line)["issue_id"] for line in lines]
        assert ids == [1, 2, 3]

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c"
        scorer = MemoryScorer(deep)
        scorer.record_outcome(_make_outcome())
        assert (deep / "outcomes.jsonl").exists()

    def test_record_includes_timestamp(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer.record_outcome(_make_outcome())
        lines = (tmp_path / "mem" / "outcomes.jsonl").read_text().strip().splitlines()
        data = json.loads(lines[0])
        assert "timestamp" in data
        assert data["timestamp"]  # non-empty


# ---------------------------------------------------------------------------
# TestUpdateScores
# ---------------------------------------------------------------------------


class TestUpdateScores:
    def test_success_increases_score(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(issue_id=10, outcome="success")
        scorer.update_scores(rec, active_item_ids=[99])
        scores = scorer.load_item_scores()
        assert scores[99]["score"] > 0.5

    def test_failure_decreases_score(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(issue_id=10, outcome="failure")
        scorer.update_scores(rec, active_item_ids=[99])
        scores = scorer.load_item_scores()
        assert scores[99]["score"] < 0.5

    def test_partial_increases_score_less_than_success(self, tmp_path: Path) -> None:
        scorer_s = MemoryScorer(tmp_path / "mem_s")
        scorer_p = MemoryScorer(tmp_path / "mem_p")
        scorer_s.update_scores(_make_outcome(outcome="success"), active_item_ids=[1])
        scorer_p.update_scores(_make_outcome(outcome="partial"), active_item_ids=[1])
        s_score = scorer_s.load_item_scores()[1]["score"]
        p_score = scorer_p.load_item_scores()[1]["score"]
        assert s_score > p_score > 0.5

    def test_new_item_starts_at_half(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Load without any updates
        scores = scorer.load_item_scores()
        assert scores == {}

        # After update, item exists
        scorer.update_scores(_make_outcome(outcome="success"), active_item_ids=[7])
        scores = scorer.load_item_scores()
        # Score should be 0.5 + 0.1 = 0.6
        assert scores[7]["score"] == pytest.approx(0.6, abs=1e-9)

    def test_trail_recorded(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(issue_id=42, outcome="success", summary="Great")
        scorer.update_scores(rec, active_item_ids=[5])
        scores = scorer.load_item_scores()
        trail = scores[5]["trail"]
        assert len(trail) == 1
        assert trail[0]["issue"] == 42
        assert trail[0]["outcome"] == "success"
        assert trail[0]["delta"] == pytest.approx(0.1)

    def test_score_clamped_at_max(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        for _ in range(20):
            scorer.update_scores(_make_outcome(outcome="success"), active_item_ids=[1])
        scores = scorer.load_item_scores()
        assert scores[1]["score"] <= 1.0

    def test_score_clamped_at_min(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        for _ in range(20):
            scorer.update_scores(_make_outcome(outcome="failure"), active_item_ids=[1])
        scores = scorer.load_item_scores()
        assert scores[1]["score"] >= 0.0

    def test_surprise_flag_high_score_failure(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Pump score above 0.7
        for _ in range(3):
            scorer.update_scores(_make_outcome(outcome="success"), active_item_ids=[1])
        # Now fail
        scorer.update_scores(_make_outcome(outcome="failure"), active_item_ids=[1])
        scores = scorer.load_item_scores()
        trail = scores[1]["trail"]
        last_entry = trail[-1]
        assert last_entry["surprising"] is True

    def test_surprise_flag_low_score_success(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Pump score below 0.3
        for _ in range(3):
            scorer.update_scores(_make_outcome(outcome="failure"), active_item_ids=[1])
        # Now succeed
        scorer.update_scores(_make_outcome(outcome="success"), active_item_ids=[1])
        scores = scorer.load_item_scores()
        trail = scores[1]["trail"]
        last_entry = trail[-1]
        assert last_entry["surprising"] is True

    def test_trail_condensed_at_max_ten(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Add 15 entries
        for i in range(15):
            scorer.update_scores(
                _make_outcome(issue_id=i, outcome="success"), active_item_ids=[1]
            )
        scores = scorer.load_item_scores()
        trail = scores[1]["trail"]
        assert len(trail) <= 10

    def test_appearances_incremented(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer.update_scores(_make_outcome(outcome="success"), active_item_ids=[1])
        scorer.update_scores(_make_outcome(outcome="success"), active_item_ids=[1])
        scores = scorer.load_item_scores()
        assert scores[1]["appearances"] == 2

    def test_item_scores_persisted_to_json(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer.update_scores(_make_outcome(outcome="success"), active_item_ids=[1])
        scores_file = tmp_path / "mem" / "item_scores.json"
        assert scores_file.exists()
        raw = json.loads(scores_file.read_text())
        assert "1" in raw


# ---------------------------------------------------------------------------
# TestTemporalDecay
# ---------------------------------------------------------------------------


class TestTemporalDecay:
    def test_high_score_decays_down_toward_half(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Set item to high score
        for _ in range(5):
            scorer.update_scores(_make_outcome(outcome="success"), active_item_ids=[1])
        before = scorer.load_item_scores()[1]["score"]
        assert before > 0.5

        scorer.apply_temporal_decay()
        after = scorer.load_item_scores()[1]["score"]
        assert after < before
        assert after > 0.5  # still above midpoint

    def test_low_score_decays_up_toward_half(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        for _ in range(5):
            scorer.update_scores(_make_outcome(outcome="failure"), active_item_ids=[1])
        before = scorer.load_item_scores()[1]["score"]
        assert before < 0.5

        scorer.apply_temporal_decay()
        after = scorer.load_item_scores()[1]["score"]
        assert after > before
        assert after < 0.5

    def test_decay_formula(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Manually set a known score
        scorer._save_item_scores(
            {1: {"score": 0.8, "appearances": 1, "trail": [], "condensed_summary": ""}}
        )
        scorer.apply_temporal_decay()
        after = scorer.load_item_scores()[1]["score"]
        expected = 0.8 * 0.95 + 0.5 * 0.05
        assert after == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# TestEvictionCandidates
# ---------------------------------------------------------------------------


class TestEvictionCandidates:
    def test_low_score_enough_appearances_evicted(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.2,
                    "appearances": 5,
                    "trail": [],
                    "condensed_summary": "",
                },
            }
        )
        candidates = scorer.eviction_candidates()
        assert 1 in candidates

    def test_low_score_few_appearances_kept(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.2,
                    "appearances": 3,
                    "trail": [],
                    "condensed_summary": "",
                },
            }
        )
        candidates = scorer.eviction_candidates()
        assert 1 not in candidates

    def test_high_score_many_appearances_kept(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.8,
                    "appearances": 10,
                    "trail": [],
                    "condensed_summary": "",
                },
            }
        )
        candidates = scorer.eviction_candidates()
        assert 1 not in candidates

    def test_boundary_score_exactly_0_3_not_evicted(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.3,
                    "appearances": 5,
                    "trail": [],
                    "condensed_summary": "",
                },
            }
        )
        candidates = scorer.eviction_candidates()
        assert 1 not in candidates

    def test_boundary_appearances_exactly_5_evicted(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.29,
                    "appearances": 5,
                    "trail": [],
                    "condensed_summary": "",
                },
            }
        )
        candidates = scorer.eviction_candidates()
        assert 1 in candidates


# ---------------------------------------------------------------------------
# TestNoiseFiltering
# ---------------------------------------------------------------------------


class TestNoiseFiltering:
    def test_code_item_not_scored_on_ci_failure(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(outcome="failure", failure_category="ci_failure")
        scorer.update_scores(rec, active_item_ids=[1], item_types={1: "code"})
        scores = scorer.load_item_scores()
        # Score unchanged from 0.5 (no delta applied)
        assert scores[1]["score"] == pytest.approx(0.5, abs=1e-9)

    def test_code_item_scored_on_quality_gate(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(outcome="failure", failure_category="quality_gate")
        scorer.update_scores(rec, active_item_ids=[1], item_types={1: "code"})
        scores = scorer.load_item_scores()
        # Score decreased from 0.5
        assert scores[1]["score"] < 0.5

    def test_instruction_item_scored_on_everything(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # ci_failure is not in code's relevance but instruction is always relevant
        rec = _make_outcome(outcome="failure", failure_category="ci_failure")
        scorer.update_scores(rec, active_item_ids=[1], item_types={1: "instruction"})
        scores = scorer.load_item_scores()
        assert scores[1]["score"] < 0.5

    def test_success_always_scores_regardless_of_type(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Even with irrelevant failure_category on a success, it should score
        rec = _make_outcome(outcome="success", failure_category="ci_failure")
        scorer.update_scores(rec, active_item_ids=[1], item_types={1: "code"})
        scores = scorer.load_item_scores()
        assert scores[1]["score"] > 0.5

    def test_irrelevant_failure_still_increments_appearances(
        self, tmp_path: Path
    ) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(outcome="failure", failure_category="ci_failure")
        scorer.update_scores(rec, active_item_ids=[1], item_types={1: "code"})
        scores = scorer.load_item_scores()
        assert scores[1]["appearances"] == 1

    def test_knowledge_item_scored_on_plan_validation(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(outcome="failure", failure_category="plan_validation")
        scorer.update_scores(rec, active_item_ids=[1], item_types={1: "knowledge"})
        scores = scorer.load_item_scores()
        assert scores[1]["score"] < 0.5

    def test_knowledge_item_not_scored_on_implementation_error(
        self, tmp_path: Path
    ) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(outcome="failure", failure_category="implementation_error")
        scorer.update_scores(rec, active_item_ids=[1], item_types={1: "knowledge"})
        scores = scorer.load_item_scores()
        assert scores[1]["score"] == pytest.approx(0.5, abs=1e-9)

    def test_config_item_scored_on_ci_failure(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(outcome="failure", failure_category="ci_failure")
        scorer.update_scores(rec, active_item_ids=[1], item_types={1: "config"})
        scores = scorer.load_item_scores()
        assert scores[1]["score"] < 0.5

    def test_no_item_types_defaults_to_always_score(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome(outcome="failure", failure_category="ci_failure")
        # No item_types provided — should always score
        scorer.update_scores(rec, active_item_ids=[1])
        scores = scorer.load_item_scores()
        assert scores[1]["score"] < 0.5


# ---------------------------------------------------------------------------
# TestCompactionClassification
# ---------------------------------------------------------------------------


class TestCompactionClassification:
    def test_auto_evict_for_very_low_score(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.1,
                    "appearances": 10,
                    "trail": [],
                    "condensed_summary": "",
                },
            }
        )
        assert scorer.classify_for_compaction(1) == "auto_evict"

    def test_needs_curation_for_low_score(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.25,
                    "appearances": 3,
                    "trail": [],
                    "condensed_summary": "",
                },
            }
        )
        assert scorer.classify_for_compaction(1) == "needs_curation"

    def test_keep_for_good_score(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.8,
                    "appearances": 5,
                    "trail": [],
                    "condensed_summary": "",
                },
            }
        )
        assert scorer.classify_for_compaction(1) == "keep"

    def test_keep_for_midrange_score(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.5,
                    "appearances": 2,
                    "trail": [],
                    "condensed_summary": "",
                },
            }
        )
        assert scorer.classify_for_compaction(1) == "keep"

    def test_surprising_item_flagged_as_needs_curation(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # A surprising trail entry means the item needs human review
        trail = [
            {
                "issue": 1,
                "outcome": "failure",
                "delta": -0.1,
                "summary": "unexpected",
                "surprising": True,
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ]
        scorer._save_item_scores(
            {
                1: {
                    "score": 0.75,
                    "appearances": 3,
                    "trail": trail,
                    "condensed_summary": "",
                },
            }
        )
        assert scorer.classify_for_compaction(1) == "needs_curation"

    def test_unknown_item_id_returns_keep(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Item not in scores — treat as new/unknown
        assert scorer.classify_for_compaction(999) == "keep"
