"""Tests for MemoryScorer — outcome recording, item scoring, noise filtering, compaction."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memory_scoring import (  # noqa: E402
    KnowledgeGap,
    MemoryScorer,
    OutcomeRecord,
    _failure_is_addressed,
    _word_overlap,
    detect_knowledge_gaps,
)

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


def _write_failures(path: Path, records: list[dict]) -> None:
    """Write a list of dicts as JSONL to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _failure_record(
    category: str = "quality_gate",
    subcategories: list[str] | None = None,
    details: str = "ruff lint error in module foo",
    issue_number: int = 1,
) -> dict:
    """Return a minimal FailureRecord-compatible dict."""
    return {
        "issue_number": issue_number,
        "pr_number": 0,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "category": category,
        "subcategories": subcategories or [],
        "details": details,
        "stage": "",
    }


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


# ---------------------------------------------------------------------------
# TestWordOverlap (unit tests for helper)
# ---------------------------------------------------------------------------


class TestWordOverlap:
    def test_identical_strings_overlap_one(self) -> None:
        assert _word_overlap("hello world foo", "hello world foo") == pytest.approx(1.0)

    def test_disjoint_strings_overlap_zero(self) -> None:
        assert _word_overlap("alpha beta", "gamma delta") == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        # "hello world" vs "hello there" → shared: {hello}, union: {hello, world, there}
        ratio = _word_overlap("hello world", "hello there")
        assert 0.0 < ratio < 1.0

    def test_empty_string_returns_zero(self) -> None:
        assert _word_overlap("", "some text") == pytest.approx(0.0)
        assert _word_overlap("some text", "") == pytest.approx(0.0)
        assert _word_overlap("", "") == pytest.approx(0.0)

    def test_case_insensitive(self) -> None:
        assert _word_overlap("Hello World", "hello world") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TestFailureIsAddressed
# ---------------------------------------------------------------------------


class TestFailureIsAddressed:
    def test_addressed_when_high_overlap(self) -> None:
        # Construct a memory text that shares many tokens with the failure details.
        details = "pyright type error in module bar annotation missing"
        memory = "pyright type error in module bar annotation missing return value"
        assert _failure_is_addressed(details, [memory]) is True

    def test_not_addressed_when_low_overlap(self) -> None:
        details = "completely unrelated failure about network timeout"
        memory = "pyright annotation type hint missing"
        assert _failure_is_addressed(details, [memory]) is False

    def test_addressed_by_any_item(self) -> None:
        details = "ruff lint format error in foo"
        irrelevant = "completely different topic"
        relevant = "ruff lint format error foo bar"
        assert _failure_is_addressed(details, [irrelevant, relevant]) is True

    def test_not_addressed_with_empty_memory(self) -> None:
        assert _failure_is_addressed("some failure details", []) is False


# ---------------------------------------------------------------------------
# TestDetectKnowledgeGaps
# ---------------------------------------------------------------------------


class TestDetectKnowledgeGaps:
    def test_gaps_detected_when_no_matching_memory(self, tmp_path: Path) -> None:
        """Failures with no matching memory items should be reported as gaps."""
        failures_path = tmp_path / "harness_failures.jsonl"
        # Write 3 identical failures — no memory covers them
        records = [
            _failure_record(
                category="quality_gate",
                details="unique obscure failure about zztop module crash",
                issue_number=i,
            )
            for i in range(1, 4)
        ]
        _write_failures(failures_path, records)

        gaps = detect_knowledge_gaps(failures_path, memory_texts=[])
        assert len(gaps) == 1
        assert gaps[0].failure_category == "quality_gate"
        assert gaps[0].frequency == 3

    def test_no_gaps_when_all_failures_matched(self, tmp_path: Path) -> None:
        """Failures whose details overlap sufficiently with memory items are not gaps."""
        failures_path = tmp_path / "harness_failures.jsonl"
        detail = "ruff lint format error in module foo bar baz qux"
        records = [
            _failure_record(category="quality_gate", details=detail, issue_number=i)
            for i in range(1, 4)
        ]
        _write_failures(failures_path, records)

        # Memory item that covers the same words
        memory_texts = ["ruff lint format error module foo bar baz qux style issue"]
        gaps = detect_knowledge_gaps(failures_path, memory_texts=memory_texts)
        assert gaps == []

    def test_frequency_threshold_excludes_rare_gaps(self, tmp_path: Path) -> None:
        """Gaps appearing fewer than 3 times are not returned."""
        failures_path = tmp_path / "harness_failures.jsonl"
        records = [
            _failure_record(
                category="ci_failure",
                details="some exotic timeout zztop unreachable host xyz",
                issue_number=i,
            )
            for i in range(1, 3)  # only 2 occurrences
        ]
        _write_failures(failures_path, records)

        gaps = detect_knowledge_gaps(failures_path, memory_texts=[])
        assert gaps == []

    def test_frequency_threshold_includes_gaps_at_threshold(
        self, tmp_path: Path
    ) -> None:
        """Gaps at exactly the threshold (3) are returned."""
        failures_path = tmp_path / "harness_failures.jsonl"
        records = [
            _failure_record(
                category="review_rejection",
                details="missing docstring zztop function quux frob",
                issue_number=i,
            )
            for i in range(1, 4)  # exactly 3 occurrences
        ]
        _write_failures(failures_path, records)

        gaps = detect_knowledge_gaps(failures_path, memory_texts=[])
        assert len(gaps) == 1
        assert gaps[0].frequency == 3

    def test_gaps_grouped_by_category_and_subcategory(self, tmp_path: Path) -> None:
        """Failures with different (category, subcategory) keys produce separate gaps."""
        failures_path = tmp_path / "harness_failures.jsonl"
        quality_records = [
            _failure_record(
                category="quality_gate",
                subcategories=["lint_error"],
                details="ruff zztop obscure format fail alpha beta gamma",
                issue_number=i,
            )
            for i in range(1, 4)
        ]
        ci_records = [
            _failure_record(
                category="ci_failure",
                subcategories=["timeout"],
                details="pytest timeout frob quux unreachable zztop delta epsilon",
                issue_number=i + 10,
            )
            for i in range(1, 4)
        ]
        _write_failures(failures_path, quality_records + ci_records)

        gaps = detect_knowledge_gaps(failures_path, memory_texts=[])
        assert len(gaps) == 2
        categories = {g.failure_category for g in gaps}
        assert "quality_gate" in categories
        assert "ci_failure" in categories

    def test_gap_includes_up_to_three_sample_details(self, tmp_path: Path) -> None:
        """At most 3 sample_details strings are included per gap."""
        failures_path = tmp_path / "harness_failures.jsonl"
        records = [
            _failure_record(
                category="plan_validation",
                details=f"unique obscure zztop failure detail number {i}",
                issue_number=i,
            )
            for i in range(1, 6)  # 5 failures
        ]
        _write_failures(failures_path, records)

        gaps = detect_knowledge_gaps(failures_path, memory_texts=[])
        assert len(gaps) == 1
        assert len(gaps[0].sample_details) <= 3

    def test_returns_empty_list_when_no_failures_file(self, tmp_path: Path) -> None:
        """No crash when harness_failures.jsonl does not exist."""
        missing = tmp_path / "nonexistent" / "harness_failures.jsonl"
        gaps = detect_knowledge_gaps(missing, memory_texts=[])
        assert gaps == []

    def test_gaps_sorted_by_frequency_descending(self, tmp_path: Path) -> None:
        """Returned gaps are ordered from most frequent to least frequent."""
        failures_path = tmp_path / "harness_failures.jsonl"
        # 5 quality_gate failures, 3 ci_failure failures (distinct word sets)
        quality_records = [
            _failure_record(
                category="quality_gate",
                details="zztop alpha beta gamma delta epsilon frob",
                issue_number=i,
            )
            for i in range(1, 6)
        ]
        ci_records = [
            _failure_record(
                category="ci_failure",
                details="quux corge grault garply waldo fred plugh",
                issue_number=i + 20,
            )
            for i in range(1, 4)
        ]
        _write_failures(failures_path, quality_records + ci_records)

        gaps = detect_knowledge_gaps(failures_path, memory_texts=[])
        assert len(gaps) >= 2
        # Most frequent gap should be first
        assert gaps[0].frequency >= gaps[-1].frequency

    def test_suggested_learning_references_category(self, tmp_path: Path) -> None:
        """suggested_learning text mentions the failure category."""
        failures_path = tmp_path / "harness_failures.jsonl"
        records = [
            _failure_record(
                category="hitl_escalation",
                details="zztop unique obscure hitl escalation detail quux",
                issue_number=i,
            )
            for i in range(1, 4)
        ]
        _write_failures(failures_path, records)

        gaps = detect_knowledge_gaps(failures_path, memory_texts=[])
        assert len(gaps) == 1
        assert "hitl_escalation" in gaps[0].suggested_learning

    def test_knowledge_gap_is_dataclass(self) -> None:
        """KnowledgeGap can be instantiated as a plain dataclass."""
        gap = KnowledgeGap(
            failure_category="ci_failure",
            subcategory="timeout",
            frequency=5,
            sample_details=["detail one"],
            suggested_learning="Add memory item.",
        )
        assert gap.failure_category == "ci_failure"
        assert gap.subcategory == "timeout"
        assert gap.frequency == 5


# ---------------------------------------------------------------------------
# TestClassifyContext
# ---------------------------------------------------------------------------


class TestClassifyContext:
    def test_bug_tag_returns_bugfix(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context(["bug"]) == "bugfix"

    def test_fix_tag_returns_bugfix(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context(["fix"]) == "bugfix"

    def test_bugfix_tag_returns_bugfix(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context(["bugfix"]) == "bugfix"

    def test_refactor_tag_returns_refactor(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context(["refactor"]) == "refactor"

    def test_refactoring_tag_returns_refactor(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context(["refactoring"]) == "refactor"

    def test_docs_tag_returns_docs(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context(["docs"]) == "docs"

    def test_documentation_tag_returns_docs(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context(["documentation"]) == "docs"

    def test_unknown_tags_returns_feature(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context(["enhancement", "performance"]) == "feature"

    def test_empty_tags_returns_feature(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context([]) == "feature"

    def test_case_insensitive_bug(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        assert _classify_context(["BUG", "Enhancement"]) == "bugfix"

    def test_bug_takes_priority_over_docs(self) -> None:
        from memory_scoring import _classify_context  # noqa: PLC0415

        # bug check comes first in the function
        assert _classify_context(["bug", "docs"]) == "bugfix"


# ---------------------------------------------------------------------------
# TestPerContextScoring
# ---------------------------------------------------------------------------


def _make_outcome_with_context(
    issue_id: int = 1,
    outcome: str = "success",
    score: float = 1.0,
    digest_hash: str = "abc123",
    summary: str = "PR merged",
    context: str = "feature",
    failure_category: str | None = None,
) -> OutcomeRecord:
    return OutcomeRecord(
        issue_id=issue_id,
        outcome=outcome,  # type: ignore[arg-type]
        score=score,
        digest_hash=digest_hash,
        failure_category=failure_category,
        summary=summary,
        context=context,
    )


class TestPerContextScoring:
    def test_context_field_stored_in_outcome_record(self) -> None:
        rec = _make_outcome_with_context(context="bugfix")
        assert rec.context == "bugfix"

    def test_context_defaults_to_feature(self) -> None:
        rec = OutcomeRecord(
            issue_id=1,
            outcome="success",
            score=1.0,
            digest_hash="x",
        )
        assert rec.context == "feature"

    def test_context_key_created_on_first_update(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome_with_context(context="bugfix")
        scorer.update_scores(rec, active_item_ids=[1])
        scores = scorer.load_item_scores()
        assert "ctx_bugfix" in scores[1]

    def test_context_score_starts_at_half_plus_delta(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome_with_context(context="bugfix", outcome="success")
        scorer.update_scores(rec, active_item_ids=[1])
        scores = scorer.load_item_scores()
        # 0.5 + 0.1 = 0.6
        assert scores[1]["ctx_bugfix"]["score"] == pytest.approx(0.6, abs=1e-9)

    def test_context_appearances_incremented(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        rec = _make_outcome_with_context(context="bugfix")
        scorer.update_scores(rec, active_item_ids=[1])
        scorer.update_scores(rec, active_item_ids=[1])
        scores = scorer.load_item_scores()
        assert scores[1]["ctx_bugfix"]["appearances"] == 2

    def test_different_contexts_tracked_separately(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        scorer.update_scores(
            _make_outcome_with_context(context="bugfix", outcome="success"),
            active_item_ids=[1],
        )
        scorer.update_scores(
            _make_outcome_with_context(context="docs", outcome="failure"),
            active_item_ids=[1],
        )
        scores = scorer.load_item_scores()
        assert scores[1]["ctx_bugfix"]["score"] > 0.5
        assert scores[1]["ctx_docs"]["score"] < 0.5

    def test_get_item_score_for_context_returns_half_for_unknown_item(
        self, tmp_path: Path
    ) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        assert scorer.get_item_score_for_context(999, "bugfix") == pytest.approx(0.5)

    def test_get_item_score_for_context_falls_back_to_global_below_threshold(
        self, tmp_path: Path
    ) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Only 2 appearances — below the threshold of 3
        rec = _make_outcome_with_context(context="bugfix", outcome="success")
        scorer.update_scores(rec, active_item_ids=[1])
        scorer.update_scores(rec, active_item_ids=[1])
        global_score = scorer.load_item_scores()[1]["score"]
        result = scorer.get_item_score_for_context(1, "bugfix")
        assert result == pytest.approx(global_score, abs=1e-9)

    def test_get_item_score_for_context_uses_ctx_score_at_threshold(
        self, tmp_path: Path
    ) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # 3 appearances — at the threshold
        rec = _make_outcome_with_context(context="refactor", outcome="success")
        scorer.update_scores(rec, active_item_ids=[1])
        scorer.update_scores(rec, active_item_ids=[1])
        scorer.update_scores(rec, active_item_ids=[1])
        ctx_score = scorer.load_item_scores()[1]["ctx_refactor"]["score"]
        result = scorer.get_item_score_for_context(1, "refactor")
        assert result == pytest.approx(ctx_score, abs=1e-9)

    def test_get_item_score_for_context_falls_back_when_ctx_key_missing(
        self, tmp_path: Path
    ) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # Record with feature context, then ask for bugfix context
        rec = _make_outcome_with_context(context="feature", outcome="success")
        scorer.update_scores(rec, active_item_ids=[1])
        scorer.update_scores(rec, active_item_ids=[1])
        scorer.update_scores(rec, active_item_ids=[1])
        global_score = scorer.load_item_scores()[1]["score"]
        result = scorer.get_item_score_for_context(1, "bugfix")
        assert result == pytest.approx(global_score, abs=1e-9)

    def test_context_not_written_for_irrelevant_failure(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path / "mem")
        # ci_failure is not relevant for "code" type items
        rec = _make_outcome_with_context(
            outcome="failure",
            failure_category="ci_failure",
            context="bugfix",
        )
        scorer.update_scores(rec, active_item_ids=[1], item_types={1: "code"})
        scores = scorer.load_item_scores()
        assert "ctx_bugfix" not in scores[1]


# ---------------------------------------------------------------------------
# Sentry breadcrumb tests for record_outcome
# ---------------------------------------------------------------------------


class TestRecordOutcomeSentryBreadcrumb:
    """Tests for Sentry breadcrumb emission in record_outcome."""

    def test_record_outcome_emits_breadcrumb(self, tmp_path: Path) -> None:
        """record_outcome adds a Sentry breadcrumb when sentry_sdk is available."""
        mock_sentry = MagicMock()
        scorer = MemoryScorer(tmp_path / "mem")
        record = OutcomeRecord(
            issue_id=7,
            outcome="success",
            score=1.0,
            digest_hash="abc123",
            context="bugfix",
        )

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            scorer.record_outcome(record)

        mock_sentry.add_breadcrumb.assert_called_once()
        call_kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert call_kwargs["category"] == "memory.outcome"
        assert call_kwargs["level"] == "info"
        assert "#7" in call_kwargs["message"]
        assert "success" in call_kwargs["message"]
        data = call_kwargs["data"]
        assert data["issue_id"] == 7
        assert data["outcome"] == "success"
        assert data["context"] == "bugfix"

    def test_record_outcome_no_error_when_sentry_unavailable(
        self, tmp_path: Path
    ) -> None:
        """record_outcome does not raise when sentry_sdk is missing."""
        scorer = MemoryScorer(tmp_path / "mem")
        record = OutcomeRecord(
            issue_id=1,
            outcome="failure",
            score=0.0,
            digest_hash="xyz",
        )
        original = sys.modules.pop("sentry_sdk", None)
        try:
            scorer.record_outcome(record)  # should not raise
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original

    def test_record_outcome_still_writes_file_when_sentry_available(
        self, tmp_path: Path
    ) -> None:
        """Sentry breadcrumb does not prevent file write."""
        mock_sentry = MagicMock()
        scorer = MemoryScorer(tmp_path / "mem")
        record = OutcomeRecord(
            issue_id=5,
            outcome="partial",
            score=0.55,
            digest_hash="hash5",
        )

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            scorer.record_outcome(record)

        lines = scorer._outcomes_file.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["issue_id"] == 5


# ---------------------------------------------------------------------------
# TestRecordMergeOutcome
# ---------------------------------------------------------------------------


class TestRecordMergeOutcome:
    """Tests for MemoryScorer.record_merge_outcome."""

    def test_clean_merge_records_success(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_merge_outcome(
            issue_id=10,
            digest_hash="abc123",
            quality_fix_attempts=0,
            review_attempts=0,
            tags=["enhancement"],
            issue_title="Add widget",
        )
        lines = scorer._outcomes_file.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["outcome"] == "success"
        assert data["score"] == 1.0
        assert data["context"] == "feature"
        assert data["summary"] == "Merged: Add widget"

    def test_one_review_round_still_success(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_merge_outcome(
            issue_id=11,
            digest_hash="def456",
            quality_fix_attempts=0,
            review_attempts=1,
            tags=["bug"],
            issue_title="Fix crash",
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["outcome"] == "success"
        assert data["score"] == 1.0
        assert data["context"] == "bugfix"

    def test_quality_fixes_records_partial(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_merge_outcome(
            issue_id=12,
            digest_hash="ghi789",
            quality_fix_attempts=2,
            review_attempts=0,
            tags=["refactor"],
            issue_title="Clean up module",
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["outcome"] == "partial"
        assert data["score"] == 0.5
        assert data["context"] == "refactor"

    def test_multiple_review_rounds_records_partial(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_merge_outcome(
            issue_id=13,
            digest_hash="jkl012",
            quality_fix_attempts=0,
            review_attempts=3,
            tags=[],
            issue_title="",
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["outcome"] == "partial"
        assert data["score"] == 0.5
        assert data["summary"] == "Merged"

    def test_empty_tags_defaults_to_feature(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_merge_outcome(
            issue_id=14,
            digest_hash="mno345",
            quality_fix_attempts=0,
            review_attempts=0,
            tags=[],
            issue_title="Something",
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["context"] == "feature"


# ---------------------------------------------------------------------------
# TestRecordHitlOutcome
# ---------------------------------------------------------------------------


class TestRecordHitlOutcome:
    """Tests for MemoryScorer.record_hitl_outcome."""

    def test_hitl_records_failure(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_hitl_outcome(
            issue_id=20,
            digest_hash="abc",
            cause="ci_failure",
            tags=["bug"],
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["outcome"] == "failure"
        assert data["score"] == -1.0
        assert data["failure_category"] == "ci_failure"
        assert data["context"] == "bugfix"
        assert "HITL escalation" in data["summary"]

    def test_hitl_empty_cause_defaults(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_hitl_outcome(
            issue_id=21,
            digest_hash="def",
            cause="",
            tags=[],
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["failure_category"] == "hitl_escalation"

    def test_hitl_empty_tags_defaults_to_feature(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_hitl_outcome(
            issue_id=22,
            digest_hash="ghi",
            cause="timeout",
            tags=[],
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["context"] == "feature"


# ---------------------------------------------------------------------------
# TestRecordFailureOutcome
# ---------------------------------------------------------------------------


class TestRecordFailureOutcome:
    """Tests for MemoryScorer.record_failure_outcome."""

    def test_failure_records_correctly(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_failure_outcome(
            issue_id=30,
            digest_hash="xyz",
            failure_category="max_attempts_exceeded",
            summary="Max attempts exceeded: Fix the widget",
            tags=["enhancement"],
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["outcome"] == "failure"
        assert data["score"] == -1.0
        assert data["failure_category"] == "max_attempts_exceeded"
        assert data["summary"] == "Max attempts exceeded: Fix the widget"
        assert data["context"] == "feature"

    def test_failure_with_bug_tags(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_failure_outcome(
            issue_id=31,
            digest_hash="abc",
            failure_category="implementation_error",
            summary="Failed to implement",
            tags=["bug", "critical"],
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["context"] == "bugfix"

    def test_failure_empty_tags(self, tmp_path: Path) -> None:
        scorer = MemoryScorer(tmp_path)
        scorer.record_failure_outcome(
            issue_id=32,
            digest_hash="def",
            failure_category="timeout",
            summary="Timed out",
            tags=[],
        )
        data = json.loads(scorer._outcomes_file.read_text().strip())
        assert data["context"] == "feature"
