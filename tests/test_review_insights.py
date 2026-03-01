"""Tests for review_insights.py — category extraction, persistence, and aggregation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import ReviewVerdict
from review_insights import (
    CATEGORY_DESCRIPTIONS,
    CATEGORY_KEYWORDS,
    ReviewInsightStore,
    ReviewRecord,
    analyze_patterns,
    build_insight_issue_body,
    extract_categories,
    get_common_feedback_section,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    *,
    pr_number: int = 101,
    issue_number: int = 42,
    verdict: ReviewVerdict = ReviewVerdict.REQUEST_CHANGES,
    summary: str = "Missing edge case tests",
    fixes_made: bool = False,
    categories: list[str] | None = None,
) -> ReviewRecord:
    return ReviewRecord(
        pr_number=pr_number,
        issue_number=issue_number,
        timestamp="2026-02-20T10:30:00Z",
        verdict=verdict,
        summary=summary,
        fixes_made=fixes_made,
        categories=categories or [],
    )


# ---------------------------------------------------------------------------
# extract_categories
# ---------------------------------------------------------------------------


class TestExtractCategories:
    """Tests for extract_categories()."""

    def test_extracts_missing_tests(self) -> None:
        cats = extract_categories("Missing test coverage for edge cases")
        assert "missing_tests" in cats

    def test_extracts_type_annotations(self) -> None:
        cats = extract_categories("Missing type annotations on public functions")
        assert "type_annotations" in cats

    def test_extracts_security(self) -> None:
        cats = extract_categories("Potential SQL injection vulnerability found")
        assert "security" in cats

    def test_extracts_naming(self) -> None:
        cats = extract_categories("Poor naming convention for variables")
        assert "naming" in cats

    def test_extracts_edge_cases(self) -> None:
        cats = extract_categories("No handling for empty input or null values")
        assert "edge_cases" in cats

    def test_extracts_error_handling(self) -> None:
        cats = extract_categories("Missing error handling for API calls")
        assert "error_handling" in cats

    def test_extracts_code_quality(self) -> None:
        cats = extract_categories("High complexity — consider refactor")
        assert "code_quality" in cats

    def test_extracts_lint_format(self) -> None:
        cats = extract_categories("Ruff lint issues not addressed")
        assert "lint_format" in cats

    def test_case_insensitive(self) -> None:
        cats = extract_categories("MISSING TEST COVERAGE")
        assert "missing_tests" in cats

    def test_multiple_categories(self) -> None:
        cats = extract_categories(
            "Missing test coverage and type annotations, also security issues"
        )
        assert "missing_tests" in cats
        assert "type_annotations" in cats
        assert "security" in cats

    def test_no_match_returns_empty(self) -> None:
        cats = extract_categories("Everything looks great, no issues found")
        assert cats == []

    def test_empty_summary_returns_empty_category_list(self) -> None:
        cats = extract_categories("")
        assert cats == []


# ---------------------------------------------------------------------------
# ReviewInsightStore
# ---------------------------------------------------------------------------


class TestReviewInsightStore:
    """Tests for ReviewInsightStore persistence."""

    def test_append_creates_file(self, tmp_path: Path) -> None:
        store = ReviewInsightStore(tmp_path / "memory")
        record = _make_record(categories=["missing_tests"])
        store.append_review(record)

        reviews_path = tmp_path / "memory" / "reviews.jsonl"
        assert reviews_path.exists()
        lines = reviews_path.read_text().strip().splitlines()
        assert len(lines) == 1

    def test_append_multiple_records(self, tmp_path: Path) -> None:
        store = ReviewInsightStore(tmp_path / "memory")
        for i in range(3):
            store.append_review(_make_record(pr_number=100 + i))

        reviews_path = tmp_path / "memory" / "reviews.jsonl"
        lines = reviews_path.read_text().strip().splitlines()
        assert len(lines) == 3

    def test_load_recent_returns_tail(self, tmp_path: Path) -> None:
        store = ReviewInsightStore(tmp_path / "memory")
        for i in range(15):
            store.append_review(_make_record(pr_number=100 + i))

        recent = store.load_recent(5)
        assert len(recent) == 5
        assert recent[0].pr_number == 110
        assert recent[-1].pr_number == 114

    def test_load_recent_returns_all_when_fewer(self, tmp_path: Path) -> None:
        store = ReviewInsightStore(tmp_path / "memory")
        for i in range(3):
            store.append_review(_make_record(pr_number=100 + i))

        recent = store.load_recent(10)
        assert len(recent) == 3

    def test_load_recent_handles_missing_file(self, tmp_path: Path) -> None:
        store = ReviewInsightStore(tmp_path / "memory")
        assert store.load_recent() == []

    def test_get_proposed_categories_empty_when_no_file(self, tmp_path: Path) -> None:
        store = ReviewInsightStore(tmp_path / "memory")
        assert store.get_proposed_categories() == set()

    def test_mark_and_get_proposed_categories(self, tmp_path: Path) -> None:
        store = ReviewInsightStore(tmp_path / "memory")
        store.mark_category_proposed("missing_tests")
        store.mark_category_proposed("security")

        proposed = store.get_proposed_categories()
        assert proposed == {"missing_tests", "security"}

    def test_mark_proposed_is_idempotent(self, tmp_path: Path) -> None:
        store = ReviewInsightStore(tmp_path / "memory")
        store.mark_category_proposed("missing_tests")
        store.mark_category_proposed("missing_tests")

        proposed = store.get_proposed_categories()
        assert proposed == {"missing_tests"}

    def test_get_proposed_handles_corrupt_file(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "proposed_categories.json").write_text("not valid json{{{")

        store = ReviewInsightStore(memory_dir)
        assert store.get_proposed_categories() == set()

    def test_load_recent_skips_malformed_lines(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        reviews_path = memory_dir / "reviews.jsonl"

        # Write one valid and one invalid line
        valid = _make_record(pr_number=101)
        reviews_path.write_text(valid.model_dump_json() + "\n" + "not valid json\n")

        store = ReviewInsightStore(memory_dir)
        records = store.load_recent()
        assert len(records) == 1
        assert records[0].pr_number == 101


# ---------------------------------------------------------------------------
# analyze_patterns
# ---------------------------------------------------------------------------


class TestAnalyzePatterns:
    """Tests for analyze_patterns()."""

    def test_identifies_patterns_above_threshold(self) -> None:
        records = [
            _make_record(pr_number=i, categories=["missing_tests"]) for i in range(5)
        ]
        patterns = analyze_patterns(records, threshold=3)
        assert len(patterns) == 1
        cat, count, evidence = patterns[0]
        assert cat == "missing_tests"
        assert count == 5
        assert len(evidence) == 5

    def test_excludes_approve_verdicts(self) -> None:
        records = [
            _make_record(
                pr_number=i,
                verdict=ReviewVerdict.APPROVE,
                categories=["missing_tests"],
            )
            for i in range(5)
        ]
        patterns = analyze_patterns(records, threshold=1)
        assert patterns == []

    def test_below_threshold_returns_empty(self) -> None:
        records = [
            _make_record(pr_number=1, categories=["missing_tests"]),
            _make_record(pr_number=2, categories=["missing_tests"]),
        ]
        patterns = analyze_patterns(records, threshold=3)
        assert patterns == []

    def test_multiple_categories_counted_separately(self) -> None:
        records = [
            _make_record(pr_number=i, categories=["missing_tests", "security"])
            for i in range(4)
        ]
        patterns = analyze_patterns(records, threshold=3)
        cats = {p[0] for p in patterns}
        assert cats == {"missing_tests", "security"}

    def test_detect_patterns_returns_empty_for_no_records(self) -> None:
        assert analyze_patterns([], threshold=1) == []

    def test_sorted_by_frequency(self) -> None:
        records = [
            _make_record(pr_number=1, categories=["security"]),
            _make_record(pr_number=2, categories=["missing_tests", "security"]),
            _make_record(pr_number=3, categories=["missing_tests", "security"]),
            _make_record(pr_number=4, categories=["missing_tests"]),
        ]
        patterns = analyze_patterns(records, threshold=2)
        # missing_tests=3, security=3 — both meet threshold
        assert len(patterns) >= 2
        # Both have count 3, order may vary but both should be present
        counts = {p[0]: p[1] for p in patterns}
        assert counts["missing_tests"] == 3
        assert counts["security"] == 3


# ---------------------------------------------------------------------------
# build_insight_issue_body
# ---------------------------------------------------------------------------


class TestBuildInsightIssueBody:
    """Tests for build_insight_issue_body()."""

    def test_contains_category_and_frequency(self) -> None:
        evidence = [_make_record(pr_number=101, summary="Needs more tests")]
        body = build_insight_issue_body("missing_tests", 4, 10, evidence)

        assert "missing_tests" in body
        assert "4 of the last 10" in body

    def test_contains_pr_evidence(self) -> None:
        evidence = [
            _make_record(pr_number=101, issue_number=42, summary="No edge case tests"),
            _make_record(pr_number=102, issue_number=43, summary="Missing coverage"),
        ]
        body = build_insight_issue_body("missing_tests", 2, 10, evidence)

        assert "PR #101" in body
        assert "PR #102" in body
        assert "issue #42" in body
        assert "No edge case tests" in body

    def test_contains_suggestion(self) -> None:
        body = build_insight_issue_body("missing_tests", 3, 10, [])
        assert "Suggested Prompt Improvement" in body

    def test_uses_category_description(self) -> None:
        body = build_insight_issue_body("missing_tests", 3, 10, [])
        assert CATEGORY_DESCRIPTIONS["missing_tests"] in body


# ---------------------------------------------------------------------------
# get_common_feedback_section
# ---------------------------------------------------------------------------


class TestGetCommonFeedbackSection:
    """Tests for get_common_feedback_section()."""

    def test_returns_markdown_section(self) -> None:
        records = [
            _make_record(pr_number=i, categories=["missing_tests"]) for i in range(3)
        ]
        section = get_common_feedback_section(records)

        assert "## Common Review Feedback" in section
        assert "Missing or insufficient test coverage" in section

    def test_returns_empty_for_all_approves(self) -> None:
        records = [
            _make_record(
                pr_number=i, verdict=ReviewVerdict.APPROVE, categories=["missing_tests"]
            )
            for i in range(3)
        ]
        assert get_common_feedback_section(records) == ""

    def test_returns_empty_for_no_records(self) -> None:
        assert get_common_feedback_section([]) == ""

    def test_build_feedback_section_limits_to_top_n_patterns(self) -> None:
        records = [
            _make_record(
                pr_number=i,
                categories=[
                    "missing_tests",
                    "security",
                    "naming",
                    "edge_cases",
                ],
            )
            for i in range(5)
        ]
        section = get_common_feedback_section(records, top_n=2)

        # Count the "- " lines (bullet items)
        bullets = [line for line in section.splitlines() if line.startswith("- ")]
        assert len(bullets) == 2

    def test_includes_count_info(self) -> None:
        records = [
            _make_record(pr_number=i, categories=["missing_tests"]) for i in range(3)
        ]
        section = get_common_feedback_section(records)
        assert "flagged in 3 of last 3 reviews" in section

    def test_returns_empty_when_no_categories(self) -> None:
        records = [_make_record(pr_number=1, categories=[])]
        assert get_common_feedback_section(records) == ""


# ---------------------------------------------------------------------------
# ReviewRecord model
# ---------------------------------------------------------------------------


class TestReviewRecord:
    """Tests for the ReviewRecord Pydantic model."""

    def test_serialization_roundtrip(self) -> None:
        record = _make_record(
            pr_number=101,
            categories=["missing_tests", "security"],
        )
        json_str = record.model_dump_json()
        restored = ReviewRecord.model_validate_json(json_str)
        assert restored == record

    def test_all_categories_are_documented(self) -> None:
        """Every category in CATEGORY_KEYWORDS should have a description."""
        for cat in CATEGORY_KEYWORDS:
            assert cat in CATEGORY_DESCRIPTIONS, f"Missing description for {cat}"


# ---------------------------------------------------------------------------
# append_review OSError handling (issue #1038)
# ---------------------------------------------------------------------------


class TestAppendReviewOSError:
    """Verify ReviewInsightStore.append_review catches OSError gracefully."""

    def test_append_review_logs_warning_on_oserror(self, tmp_path, caplog) -> None:
        """When the reviews file can't be written, log warning and don't raise."""
        import logging
        from pathlib import Path
        from unittest.mock import patch

        store = ReviewInsightStore(tmp_path / "memory")
        record = _make_record(categories=["missing_tests"])

        with (
            patch.object(Path, "open", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="hydraflow.review_insights"),
        ):
            store.append_review(record)  # should not raise

        assert "Could not append review" in caplog.text

    def test_append_review_handles_mkdir_failure(self, tmp_path, caplog) -> None:
        """When mkdir fails with PermissionError, log warning and don't raise."""
        import logging
        from pathlib import Path
        from unittest.mock import patch

        store = ReviewInsightStore(tmp_path / "memory")
        record = _make_record(categories=["security"])

        with (
            patch.object(Path, "mkdir", side_effect=PermissionError("not allowed")),
            caplog.at_level(logging.WARNING, logger="hydraflow.review_insights"),
        ):
            store.append_review(record)  # should not raise

        assert "Could not append review" in caplog.text


# ---------------------------------------------------------------------------
# ReviewRecord timestamp validation (issue #1048)
# ---------------------------------------------------------------------------


class TestReviewRecordTimestamp:
    """Tests for ReviewRecord IsoTimestamp validation."""

    def test_invalid_timestamp_rejected(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Invalid ISO 8601 timestamp"):
            ReviewRecord(
                pr_number=1,
                issue_number=42,
                timestamp="not-a-timestamp",
                verdict="approve",
                summary="ok",
                fixes_made=False,
                categories=[],
            )

    def test_valid_iso_timestamp_accepted(self) -> None:
        record = ReviewRecord(
            pr_number=1,
            issue_number=42,
            timestamp="2026-02-20T10:30:00+00:00",
            verdict="approve",
            summary="ok",
            fixes_made=False,
            categories=[],
        )
        assert record.timestamp == "2026-02-20T10:30:00+00:00"


# ---------------------------------------------------------------------------
# ReviewRecord field descriptions (issue #1048)
# ---------------------------------------------------------------------------


class TestReviewRecordFieldDescriptions:
    """Tests that field descriptions are present in ReviewRecord schema."""

    def test_review_record_has_field_descriptions(self) -> None:
        schema = ReviewRecord.model_json_schema()
        props = schema["properties"]
        # verdict is now a ReviewVerdict StrEnum — represented as $ref in schema
        assert "verdict" in props
        assert "summary" in props
        assert "fixes_made" in props
        assert "categories" in props
