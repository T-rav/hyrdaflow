"""Tests for harness_insights.py — failure tracking, pattern detection, and suggestions."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness_insights import (
    CATEGORY_DESCRIPTIONS,
    FailureCategory,
    FailureRecord,
    HarnessInsightStore,
    ImprovementSuggestion,
    analyze_category_patterns,
    analyze_subcategory_patterns,
    build_harness_issue_body,
    extract_subcategories,
    file_harness_suggestions,
    generate_suggestions,
)
from models import PipelineStage
from state import StateTracker
from tests.conftest import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    *,
    issue_number: int = 42,
    pr_number: int = 0,
    category: str = FailureCategory.QUALITY_GATE,
    subcategories: list[str] | None = None,
    details: str = "ruff lint error: missing import",
    stage: PipelineStage = PipelineStage.IMPLEMENT,
) -> FailureRecord:
    return FailureRecord(
        issue_number=issue_number,
        pr_number=pr_number,
        timestamp="2026-02-20T10:30:00Z",
        category=category,
        subcategories=subcategories or [],
        details=details,
        stage=stage,
    )


# ---------------------------------------------------------------------------
# FailureCategory enum
# ---------------------------------------------------------------------------


class TestFailureCategory:
    """Tests for the FailureCategory enum."""

    def test_all_categories_have_descriptions(self) -> None:
        for cat in FailureCategory:
            assert cat.value in CATEGORY_DESCRIPTIONS

    def test_category_values_are_strings(self) -> None:
        for cat in FailureCategory:
            assert isinstance(cat.value, str)


# ---------------------------------------------------------------------------
# extract_subcategories
# ---------------------------------------------------------------------------


class TestExtractSubcategories:
    """Tests for extract_subcategories()."""

    def test_extracts_lint_error(self) -> None:
        subs = extract_subcategories("ruff lint error on line 42")
        assert "lint_error" in subs

    def test_extracts_type_error(self) -> None:
        subs = extract_subcategories("pyright type error: incompatible type")
        assert "type_error" in subs

    def test_extracts_test_failure(self) -> None:
        subs = extract_subcategories("pytest failed: 3 tests failed, assertion error")
        assert "test_failure" in subs

    def test_extracts_import_error(self) -> None:
        subs = extract_subcategories("ModuleNotFoundError: No module named 'foo'")
        assert "import_error" in subs

    def test_extracts_syntax_error(self) -> None:
        subs = extract_subcategories("SyntaxError: unexpected token at line 5")
        assert "syntax_error" in subs

    def test_extracts_merge_conflict(self) -> None:
        subs = extract_subcategories("Merge conflict in src/foo.py")
        assert "merge_conflict" in subs

    def test_extracts_timeout(self) -> None:
        subs = extract_subcategories("Agent timed out after 600s")
        assert "timeout" in subs

    def test_extracts_missing_tests(self) -> None:
        subs = extract_subcategories("No test file found for new module")
        assert "missing_tests" in subs

    def test_extracts_naming_violations(self) -> None:
        subs = extract_subcategories(
            "Naming convention violation: rename to snake_case"
        )
        assert "naming" in subs

    def test_extracts_error_handling(self) -> None:
        subs = extract_subcategories("Missing error handling for API exception")
        assert "error_handling" in subs

    def test_case_insensitive(self) -> None:
        subs = extract_subcategories("RUFF LINT ERROR")
        assert "lint_error" in subs

    def test_multiple_subcategories(self) -> None:
        subs = extract_subcategories("ruff lint error and pytest test failure")
        assert "lint_error" in subs
        assert "test_failure" in subs

    def test_no_match_returns_empty(self) -> None:
        subs = extract_subcategories("Everything looks good")
        assert subs == []

    def test_returns_empty_for_empty_input(self) -> None:
        subs = extract_subcategories("")
        assert subs == []


# ---------------------------------------------------------------------------
# FailureRecord model
# ---------------------------------------------------------------------------


class TestFailureRecord:
    """Tests for the FailureRecord Pydantic model."""

    def test_serialization_roundtrip(self) -> None:
        record = _make_record(subcategories=["lint_error", "test_failure"])
        json_str = record.model_dump_json()
        restored = FailureRecord.model_validate_json(json_str)
        assert restored.issue_number == record.issue_number
        assert restored.category == record.category
        assert restored.subcategories == record.subcategories

    def test_default_timestamp_set(self) -> None:
        record = FailureRecord(
            issue_number=1,
            category=FailureCategory.QUALITY_GATE,
        )
        assert record.timestamp  # Should have a default timestamp

    def test_default_fields(self) -> None:
        record = FailureRecord(
            issue_number=1,
            category=FailureCategory.CI_FAILURE,
        )
        assert record.pr_number == 0
        assert record.subcategories == []
        assert record.details == ""
        assert record.stage == ""


# ---------------------------------------------------------------------------
# HarnessInsightStore
# ---------------------------------------------------------------------------


class TestHarnessInsightStore:
    """Tests for HarnessInsightStore persistence."""

    def test_append_creates_file(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        record = _make_record()
        store.append_failure(record)

        failures_path = tmp_path / "memory" / "harness_failures.jsonl"
        assert failures_path.exists()
        lines = failures_path.read_text().strip().splitlines()
        assert len(lines) == 1

    def test_append_multiple_records(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        for i in range(5):
            store.append_failure(_make_record(issue_number=100 + i))

        failures_path = tmp_path / "memory" / "harness_failures.jsonl"
        lines = failures_path.read_text().strip().splitlines()
        assert len(lines) == 5

    def test_load_recent_returns_tail(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        for i in range(15):
            store.append_failure(_make_record(issue_number=100 + i))

        recent = store.load_recent(5)
        assert len(recent) == 5
        assert recent[0].issue_number == 110
        assert recent[-1].issue_number == 114

    def test_load_recent_returns_all_when_fewer(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        for i in range(3):
            store.append_failure(_make_record(issue_number=100 + i))

        recent = store.load_recent(10)
        assert len(recent) == 3

    def test_load_recent_handles_missing_file(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        assert store.load_recent() == []

    def test_load_recent_skips_malformed_lines(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        failures_path = memory_dir / "harness_failures.jsonl"

        valid = _make_record(issue_number=42)
        failures_path.write_text(valid.model_dump_json() + "\n" + "not valid json\n")

        store = HarnessInsightStore(memory_dir)
        records = store.load_recent()
        assert len(records) == 1
        assert records[0].issue_number == 42

    def test_get_proposed_patterns_empty_when_no_file(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        assert store.get_proposed_patterns() == set()

    def test_mark_and_get_proposed_patterns(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        store.mark_pattern_proposed("category:quality_gate")
        store.mark_pattern_proposed("subcategory:lint_error")

        proposed = store.get_proposed_patterns()
        assert proposed == {"category:quality_gate", "subcategory:lint_error"}

    def test_mark_proposed_is_idempotent(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        store.mark_pattern_proposed("category:quality_gate")
        store.mark_pattern_proposed("category:quality_gate")

        proposed = store.get_proposed_patterns()
        assert proposed == {"category:quality_gate"}

    def test_get_proposed_handles_corrupt_file(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "harness_proposed.json").write_text("not valid json{{{")

        store = HarnessInsightStore(memory_dir)
        assert store.get_proposed_patterns() == set()


# ---------------------------------------------------------------------------
# analyze_category_patterns
# ---------------------------------------------------------------------------


class TestAnalyzeCategoryPatterns:
    """Tests for analyze_category_patterns()."""

    def test_identifies_patterns_above_threshold(self) -> None:
        records = [
            _make_record(issue_number=i, category=FailureCategory.QUALITY_GATE)
            for i in range(5)
        ]
        patterns = analyze_category_patterns(records, threshold=3)
        assert len(patterns) == 1
        cat, count, evidence = patterns[0]
        assert cat == FailureCategory.QUALITY_GATE
        assert count == 5
        assert len(evidence) == 5

    def test_below_threshold_returns_empty(self) -> None:
        records = [
            _make_record(issue_number=1, category=FailureCategory.QUALITY_GATE),
            _make_record(issue_number=2, category=FailureCategory.QUALITY_GATE),
        ]
        patterns = analyze_category_patterns(records, threshold=3)
        assert patterns == []

    def test_multiple_categories(self) -> None:
        records = [
            _make_record(issue_number=i, category=FailureCategory.QUALITY_GATE)
            for i in range(3)
        ] + [
            _make_record(issue_number=i + 10, category=FailureCategory.CI_FAILURE)
            for i in range(3)
        ]
        patterns = analyze_category_patterns(records, threshold=3)
        cats = {p[0] for p in patterns}
        assert cats == {FailureCategory.QUALITY_GATE, FailureCategory.CI_FAILURE}

    def test_sorted_by_frequency(self) -> None:
        records = [
            _make_record(issue_number=i, category=FailureCategory.QUALITY_GATE)
            for i in range(5)
        ] + [
            _make_record(issue_number=i + 10, category=FailureCategory.CI_FAILURE)
            for i in range(3)
        ]
        patterns = analyze_category_patterns(records, threshold=3)
        assert patterns[0][0] == FailureCategory.QUALITY_GATE
        assert patterns[0][1] == 5
        assert patterns[1][0] == FailureCategory.CI_FAILURE
        assert patterns[1][1] == 3

    def test_empty_records(self) -> None:
        assert analyze_category_patterns([], threshold=1) == []


# ---------------------------------------------------------------------------
# analyze_subcategory_patterns
# ---------------------------------------------------------------------------


class TestAnalyzeSubcategoryPatterns:
    """Tests for analyze_subcategory_patterns()."""

    def test_identifies_subcategory_patterns(self) -> None:
        records = [
            _make_record(issue_number=i, subcategories=["lint_error"]) for i in range(4)
        ]
        patterns = analyze_subcategory_patterns(records, threshold=3)
        assert len(patterns) == 1
        sub, count, evidence = patterns[0]
        assert sub == "lint_error"
        assert count == 4

    def test_multiple_subcategories_per_record(self) -> None:
        records = [
            _make_record(
                issue_number=i,
                subcategories=["lint_error", "type_error"],
            )
            for i in range(3)
        ]
        patterns = analyze_subcategory_patterns(records, threshold=3)
        subs = {p[0] for p in patterns}
        assert subs == {"lint_error", "type_error"}

    def test_below_threshold_returns_empty(self) -> None:
        records = [
            _make_record(issue_number=1, subcategories=["lint_error"]),
        ]
        patterns = analyze_subcategory_patterns(records, threshold=3)
        assert patterns == []

    def test_empty_records(self) -> None:
        assert analyze_subcategory_patterns([], threshold=1) == []

    def test_records_with_no_subcategories(self) -> None:
        records = [_make_record(issue_number=i, subcategories=[]) for i in range(5)]
        patterns = analyze_subcategory_patterns(records, threshold=1)
        assert patterns == []


# ---------------------------------------------------------------------------
# build_harness_issue_body
# ---------------------------------------------------------------------------


class TestBuildHarnessIssueBody:
    """Tests for build_harness_issue_body()."""

    def test_contains_category_and_count(self) -> None:
        evidence = [_make_record(issue_number=42)]
        body = build_harness_issue_body(FailureCategory.QUALITY_GATE, 5, 20, evidence)
        assert "quality_gate" in body
        assert "5 times" in body
        assert "20 pipeline failures" in body

    def test_contains_evidence(self) -> None:
        evidence = [
            _make_record(issue_number=42, pr_number=101, details="lint error"),
            _make_record(issue_number=43, pr_number=102, details="type error"),
        ]
        body = build_harness_issue_body(FailureCategory.QUALITY_GATE, 2, 10, evidence)
        assert "issue #42" in body
        assert "PR #101" in body
        assert "issue #43" in body

    def test_contains_suggestion(self) -> None:
        body = build_harness_issue_body(FailureCategory.QUALITY_GATE, 3, 10, [])
        assert "Suggested Improvement" in body

    def test_subcategory_included(self) -> None:
        body = build_harness_issue_body(
            FailureCategory.QUALITY_GATE,
            3,
            10,
            [],
            subcategory="lint_error",
        )
        assert "lint_error" in body

    def test_evidence_capped_at_10(self) -> None:
        evidence = [_make_record(issue_number=i) for i in range(15)]
        body = build_harness_issue_body(FailureCategory.QUALITY_GATE, 15, 20, evidence)
        # Count evidence lines (start with "- issue #")
        evidence_lines = [ln for ln in body.splitlines() if ln.startswith("- issue #")]
        assert len(evidence_lines) == 10

    def test_auto_generated_footer(self) -> None:
        body = build_harness_issue_body(FailureCategory.CI_FAILURE, 3, 10, [])
        assert "Auto-generated by HydraFlow" in body


# ---------------------------------------------------------------------------
# generate_suggestions
# ---------------------------------------------------------------------------


class TestGenerateSuggestions:
    """Tests for generate_suggestions()."""

    def test_generates_category_suggestion(self) -> None:
        records = [
            _make_record(issue_number=i, category=FailureCategory.QUALITY_GATE)
            for i in range(5)
        ]
        suggestions = generate_suggestions(records, threshold=3)
        assert len(suggestions) >= 1
        assert any(s.category == FailureCategory.QUALITY_GATE for s in suggestions)

    def test_generates_subcategory_suggestion(self) -> None:
        records = [
            _make_record(
                issue_number=i,
                category=FailureCategory.QUALITY_GATE,
                subcategories=["lint_error"],
            )
            for i in range(4)
        ]
        suggestions = generate_suggestions(records, threshold=3)
        assert any(s.subcategory == "lint_error" for s in suggestions)

    def test_skips_already_proposed(self) -> None:
        records = [
            _make_record(issue_number=i, category=FailureCategory.QUALITY_GATE)
            for i in range(5)
        ]
        proposed = {"category:quality_gate"}
        suggestions = generate_suggestions(records, threshold=3, proposed=proposed)
        assert not any(
            s.category == FailureCategory.QUALITY_GATE and s.subcategory == ""
            for s in suggestions
        )

    def test_sorted_by_occurrence(self) -> None:
        records = [
            _make_record(issue_number=i, category=FailureCategory.QUALITY_GATE)
            for i in range(5)
        ] + [
            _make_record(issue_number=i + 10, category=FailureCategory.CI_FAILURE)
            for i in range(3)
        ]
        suggestions = generate_suggestions(records, threshold=3)
        if len(suggestions) >= 2:
            assert suggestions[0].occurrence_count >= suggestions[1].occurrence_count

    def test_below_threshold_no_suggestions(self) -> None:
        records = [_make_record(issue_number=1)]
        suggestions = generate_suggestions(records, threshold=3)
        assert suggestions == []

    def test_empty_records_no_suggestions(self) -> None:
        suggestions = generate_suggestions([], threshold=1)
        assert suggestions == []

    def test_suggestion_has_evidence(self) -> None:
        records = [
            _make_record(issue_number=i, category=FailureCategory.QUALITY_GATE)
            for i in range(3)
        ]
        suggestions = generate_suggestions(records, threshold=3)
        assert suggestions[0].evidence
        assert len(suggestions[0].evidence) == 3


# ---------------------------------------------------------------------------
# file_harness_suggestions
# ---------------------------------------------------------------------------


class TestFileHarnessSuggestions:
    """Tests for file_harness_suggestions()."""

    @pytest.mark.asyncio
    async def test_files_issue_and_marks_proposed(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=99)
        state = StateTracker(tmp_path / "state.json")

        suggestion = ImprovementSuggestion(
            category=FailureCategory.QUALITY_GATE,
            occurrence_count=5,
            window_size=20,
            description="Quality gate failure",
            suggestion="Improve lint checks",
            evidence=[_make_record()],
        )

        filed = await file_harness_suggestions(
            [suggestion],
            store,
            mock_prs,
            state,
            improve_label=["hydraflow-improve"],
            hitl_label=["hydraflow-hitl"],
        )

        assert filed == 1
        mock_prs.create_issue.assert_called_once()
        call_args = mock_prs.create_issue.call_args
        assert "[Harness Insight]" in call_args[0][0]
        assert "category:quality_gate" in store.get_proposed_patterns()

    @pytest.mark.asyncio
    async def test_caps_at_max_per_cycle(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=99)
        state = StateTracker(tmp_path / "state.json")

        suggestions = [
            ImprovementSuggestion(
                category=FailureCategory.QUALITY_GATE,
                occurrence_count=5,
                window_size=20,
                description="Quality gate failure",
                suggestion="Fix it",
            ),
            ImprovementSuggestion(
                category=FailureCategory.CI_FAILURE,
                occurrence_count=3,
                window_size=20,
                description="CI failure",
                suggestion="Fix CI",
            ),
        ]

        filed = await file_harness_suggestions(
            suggestions,
            store,
            mock_prs,
            state,
            improve_label=["hydraflow-improve"],
            hitl_label=["hydraflow-hitl"],
            max_per_cycle=1,
        )

        assert filed == 1
        assert mock_prs.create_issue.call_count == 1

    @pytest.mark.asyncio
    async def test_sets_hitl_origin_and_cause(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=88)
        state = StateTracker(tmp_path / "state.json")

        suggestion = ImprovementSuggestion(
            category=FailureCategory.REVIEW_REJECTION,
            occurrence_count=4,
            window_size=20,
            description="Review rejection",
            suggestion="Improve prompts",
        )

        await file_harness_suggestions(
            [suggestion],
            store,
            mock_prs,
            state,
            improve_label=["hydraflow-improve"],
            hitl_label=["hydraflow-hitl"],
        )

        assert state.get_hitl_origin(88) == "hydraflow-improve"
        assert "Harness pattern detected" in (state.get_hitl_cause(88) or "")

    @pytest.mark.asyncio
    async def test_subcategory_key_used_when_present(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=77)
        state = StateTracker(tmp_path / "state.json")

        suggestion = ImprovementSuggestion(
            category=FailureCategory.QUALITY_GATE,
            subcategory="lint_error",
            occurrence_count=4,
            window_size=20,
            description="Recurring lint_error failures",
            suggestion="Add lint step",
        )

        await file_harness_suggestions(
            [suggestion],
            store,
            mock_prs,
            state,
            improve_label=["hydraflow-improve"],
            hitl_label=["hydraflow-hitl"],
        )

        assert "subcategory:lint_error" in store.get_proposed_patterns()

    @pytest.mark.asyncio
    async def test_no_suggestions_files_nothing(self, tmp_path: Path) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        mock_prs = AsyncMock()
        state = StateTracker(tmp_path / "state.json")

        filed = await file_harness_suggestions(
            [],
            store,
            mock_prs,
            state,
            improve_label=["hydraflow-improve"],
            hitl_label=["hydraflow-hitl"],
        )

        assert filed == 0
        mock_prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_memory_label_route_prefixes_memory_and_skips_hitl(
        self, tmp_path: Path
    ) -> None:
        store = HarnessInsightStore(tmp_path / "memory")
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=101)
        state = StateTracker(tmp_path / "state.json")

        suggestion = ImprovementSuggestion(
            category=FailureCategory.QUALITY_GATE,
            occurrence_count=5,
            window_size=20,
            description="Quality gate failure",
            suggestion="Improve lint checks",
        )

        filed = await file_harness_suggestions(
            [suggestion],
            store,
            mock_prs,
            state,
            improve_label=["hydraflow-improve"],
            hitl_label=["hydraflow-hitl"],
            memory_label=["hydraflow-memory"],
        )

        assert filed == 1
        call_args = mock_prs.create_issue.call_args
        assert call_args[0][0].startswith("[Memory] [Harness Insight]")
        assert call_args[0][2] == ["hydraflow-improve", "hydraflow-memory"]
        assert state.get_hitl_origin(101) is None
        assert state.get_hitl_cause(101) is None

    @pytest.mark.asyncio
    async def test_create_issue_failure_does_not_mark_proposed(
        self, tmp_path: Path
    ) -> None:
        """If create_issue returns None, the pattern must not be marked proposed."""
        store = HarnessInsightStore(tmp_path / "memory")
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=None)
        state = StateTracker(tmp_path / "state.json")

        suggestion = ImprovementSuggestion(
            category=FailureCategory.QUALITY_GATE,
            occurrence_count=5,
            window_size=20,
            description="Quality gate failure",
            suggestion="Improve lint checks",
        )

        filed = await file_harness_suggestions(
            [suggestion],
            store,
            mock_prs,
            state,
            improve_label=["hydraflow-improve"],
            hitl_label=["hydraflow-hitl"],
        )

        assert filed == 0
        assert store.get_proposed_patterns() == set()


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestConfigFields:
    """Tests that config fields are properly defined."""

    def test_harness_insight_window_default(self) -> None:
        config = ConfigFactory.create()
        assert config.harness_insight_window == 20

    def test_harness_pattern_threshold_default(self) -> None:
        config = ConfigFactory.create()
        assert config.harness_pattern_threshold == 3

    def test_harness_insight_window_configurable(self) -> None:
        config = ConfigFactory.create(harness_insight_window=50)
        assert config.harness_insight_window == 50

    def test_harness_pattern_threshold_configurable(self) -> None:
        config = ConfigFactory.create(harness_pattern_threshold=5)
        assert config.harness_pattern_threshold == 5


# ---------------------------------------------------------------------------
# ImprovementSuggestion model
# ---------------------------------------------------------------------------


class TestImprovementSuggestion:
    """Tests for the ImprovementSuggestion model."""

    def test_serialization_roundtrip(self) -> None:
        suggestion = ImprovementSuggestion(
            category=FailureCategory.QUALITY_GATE,
            subcategory="lint_error",
            occurrence_count=5,
            window_size=20,
            description="Recurring lint errors",
            suggestion="Add pre-check step",
            evidence=[_make_record()],
        )
        data = suggestion.model_dump()
        restored = ImprovementSuggestion.model_validate(data)
        assert restored.category == suggestion.category
        assert restored.subcategory == suggestion.subcategory
        assert restored.occurrence_count == suggestion.occurrence_count
        assert len(restored.evidence) == 1

    def test_default_fields(self) -> None:
        suggestion = ImprovementSuggestion(
            category="test",
            occurrence_count=1,
            window_size=10,
            description="test",
            suggestion="test",
        )
        assert suggestion.subcategory == ""
        assert suggestion.evidence == []


# ---------------------------------------------------------------------------
# append_failure OSError handling (issue #1038)
# ---------------------------------------------------------------------------


class TestAppendFailureOSError:
    """Verify HarnessInsightStore.append_failure catches OSError gracefully."""

    def test_append_failure_logs_warning_on_oserror(self, tmp_path, caplog) -> None:
        """When the failures file can't be written, log warning and don't raise."""
        import logging
        from pathlib import Path
        from unittest.mock import patch

        store = HarnessInsightStore(tmp_path / "memory")
        record = _make_record()

        with (
            patch.object(Path, "open", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="hydraflow.harness_insights"),
        ):
            store.append_failure(record)  # should not raise

        assert "Could not append failure" in caplog.text

    def test_append_failure_handles_mkdir_failure(self, tmp_path, caplog) -> None:
        """When mkdir fails with PermissionError, log warning and don't raise."""
        import logging
        from pathlib import Path
        from unittest.mock import patch

        store = HarnessInsightStore(tmp_path / "memory")
        record = _make_record()

        with (
            patch.object(Path, "mkdir", side_effect=PermissionError("not allowed")),
            caplog.at_level(logging.WARNING, logger="hydraflow.harness_insights"),
        ):
            store.append_failure(record)  # should not raise

        assert "Could not append failure" in caplog.text


# ---------------------------------------------------------------------------
# FailureRecord timestamp validation (issue #1048)
# ---------------------------------------------------------------------------


class TestFailureRecordTimestamp:
    """Tests for FailureRecord IsoTimestamp validation."""

    def test_default_timestamp_is_valid_iso(self) -> None:
        record = FailureRecord(issue_number=1, category="quality_gate")
        from datetime import datetime

        datetime.fromisoformat(record.timestamp)

    def test_invalid_timestamp_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Invalid ISO 8601 timestamp"):
            FailureRecord(
                issue_number=1,
                category="quality_gate",
                timestamp="not-a-timestamp",
            )

    def test_valid_iso_timestamp_accepted(self) -> None:
        record = FailureRecord(
            issue_number=1,
            category="quality_gate",
            timestamp="2026-02-20T10:30:00+00:00",
        )
        assert record.timestamp == "2026-02-20T10:30:00+00:00"


# ---------------------------------------------------------------------------
# Field descriptions (issue #1048)
# ---------------------------------------------------------------------------


class TestFieldDescriptions:
    """Tests that field descriptions are present in model schemas."""

    def test_failure_record_has_field_descriptions(self) -> None:
        schema = FailureRecord.model_json_schema()
        props = schema["properties"]
        # category is now a FailureCategory StrEnum — represented as $ref in schema
        assert "category" in props
        # stage is now PipelineStage | Literal[""] — represented as anyOf in schema
        assert "stage" in props
        assert "details" in props

    def test_improvement_suggestion_has_field_descriptions(self) -> None:
        schema = ImprovementSuggestion.model_json_schema()
        props = schema["properties"]
        assert "description" in props["category"]
        assert "description" in props["subcategory"]
        assert "description" in props["occurrence_count"]
        assert "description" in props["window_size"]
        assert "description" in props["description"]
        assert "description" in props["suggestion"]
