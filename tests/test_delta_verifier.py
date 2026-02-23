"""Tests for delta_verifier.py — structured plan delta verification."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from delta_verifier import parse_file_delta, verify_delta

# ---------------------------------------------------------------------------
# parse_file_delta
# ---------------------------------------------------------------------------


class TestParseFileDelta:
    """Tests for parsing the ## File Delta section from plans."""

    def test_parses_all_change_types(self) -> None:
        plan = (
            "## File Delta\n"
            "MODIFIED: src/config.py\n"
            "ADDED: src/new_module.py\n"
            "REMOVED: src/old_module.py\n"
            "\n"
            "## Implementation Steps\n"
        )
        result = parse_file_delta(plan)
        assert result == ["src/config.py", "src/new_module.py", "src/old_module.py"]

    def test_handles_backtick_wrapped_paths(self) -> None:
        plan = "## File Delta\nMODIFIED: `src/config.py`\nADDED: `src/new_module.py`\n"
        result = parse_file_delta(plan)
        assert "src/config.py" in result
        assert "src/new_module.py" in result

    def test_case_insensitive_prefixes(self) -> None:
        plan = (
            "## File Delta\n"
            "modified: src/foo.py\n"
            "Added: src/bar.py\n"
            "REMOVED: src/baz.py\n"
        )
        result = parse_file_delta(plan)
        assert len(result) == 3

    def test_returns_empty_when_no_delta_section(self) -> None:
        plan = "## Files to Modify\n- src/config.py\n"
        assert parse_file_delta(plan) == []

    def test_returns_empty_when_section_has_no_entries(self) -> None:
        plan = "## File Delta\n\nNo file changes planned.\n\n## Implementation Steps\n"
        assert parse_file_delta(plan) == []

    def test_deduplicates_paths(self) -> None:
        plan = "## File Delta\nMODIFIED: src/config.py\nMODIFIED: src/config.py\n"
        result = parse_file_delta(plan)
        assert result == ["src/config.py"]

    def test_handles_colon_with_spaces(self) -> None:
        plan = "## File Delta\nMODIFIED :  src/config.py  \n"
        result = parse_file_delta(plan)
        assert result == ["src/config.py"]


# ---------------------------------------------------------------------------
# verify_delta
# ---------------------------------------------------------------------------


class TestVerifyDelta:
    """Tests for comparing planned vs actual file changes."""

    def test_no_drift_when_match(self) -> None:
        planned = ["src/a.py", "src/b.py"]
        actual = ["src/a.py", "src/b.py"]
        report = verify_delta(planned, actual)
        assert not report.has_drift
        assert report.missing == []
        assert report.unexpected == []

    def test_missing_files_detected(self) -> None:
        planned = ["src/a.py", "src/b.py", "src/c.py"]
        actual = ["src/a.py"]
        report = verify_delta(planned, actual)
        assert report.has_drift
        assert "src/b.py" in report.missing
        assert "src/c.py" in report.missing

    def test_unexpected_files_detected(self) -> None:
        planned = ["src/a.py"]
        actual = ["src/a.py", "src/extra.py"]
        report = verify_delta(planned, actual)
        assert report.has_drift
        assert "src/extra.py" in report.unexpected

    def test_mixed_drift_reports_missing_and_unexpected_files(self) -> None:
        planned = ["src/a.py", "src/b.py"]
        actual = ["src/a.py", "src/c.py"]
        report = verify_delta(planned, actual)
        assert report.has_drift
        assert report.missing == ["src/b.py"]
        assert report.unexpected == ["src/c.py"]

    def test_empty_planned_treats_all_actual_as_unexpected(self) -> None:
        report = verify_delta([], ["src/a.py"])
        assert report.has_drift
        assert report.unexpected == ["src/a.py"]

    def test_empty_actual_treats_all_planned_as_missing(self) -> None:
        report = verify_delta(["src/a.py"], [])
        assert report.has_drift
        assert report.missing == ["src/a.py"]

    def test_both_empty_reports_no_drift(self) -> None:
        report = verify_delta([], [])
        assert not report.has_drift

    def test_format_summary_no_drift(self) -> None:
        report = verify_delta(["src/a.py"], ["src/a.py"])
        summary = report.format_summary()
        assert "No drift" in summary

    def test_format_summary_with_drift(self) -> None:
        report = verify_delta(["src/a.py"], ["src/b.py"])
        summary = report.format_summary()
        assert "Missing" in summary
        assert "Unexpected" in summary
