"""Tests for adr_utils.py — ADR utility functions extracted from phase_utils."""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adr_utils import (
    ADR_FILE_RE,
    adr_validation_reasons,
    check_adr_duplicate,
    extract_adr_section,
    is_adr_issue_title,
    load_existing_adr_topics,
    next_adr_number,
    normalize_adr_topic,
)

# ---------------------------------------------------------------------------
# is_adr_issue_title
# ---------------------------------------------------------------------------


class TestIsAdrIssueTitle:
    def test_matches_standard_adr_prefix(self) -> None:
        assert is_adr_issue_title("[ADR] Use event sourcing for state") is True

    def test_matches_case_insensitive(self) -> None:
        assert is_adr_issue_title("[adr] lowercase prefix") is True
        assert is_adr_issue_title("[Adr] mixed case") is True

    def test_matches_with_leading_whitespace(self) -> None:
        assert is_adr_issue_title("  [ADR] leading spaces") is True

    def test_rejects_non_adr_title(self) -> None:
        assert is_adr_issue_title("Fix broken tests") is False

    def test_rejects_adr_not_at_start(self) -> None:
        assert is_adr_issue_title("Issue about [ADR] formatting") is False

    def test_rejects_empty_string(self) -> None:
        assert is_adr_issue_title("") is False

    def test_rejects_partial_prefix(self) -> None:
        assert is_adr_issue_title("[AD] not quite") is False


# ---------------------------------------------------------------------------
# normalize_adr_topic
# ---------------------------------------------------------------------------


class TestNormalizeAdrTopic:
    def test_strips_memory_prefix(self) -> None:
        assert (
            normalize_adr_topic("[Memory] ADR test policy — only structural tests")
            == "adr test policy only structural tests"
        )

    def test_strips_adr_draft_prefix(self) -> None:
        assert (
            normalize_adr_topic(
                "[ADR] Draft decision from memory #123: Worker topology shift"
            )
            == "worker topology shift"
        )

    def test_lowercases_and_normalizes(self) -> None:
        assert normalize_adr_topic("Use Event Sourcing") == "use event sourcing"

    def test_strips_non_alphanumeric(self) -> None:
        assert normalize_adr_topic("foo--bar__baz") == "foo bar baz"

    def test_empty_string(self) -> None:
        assert normalize_adr_topic("") == ""

    def test_only_prefix(self) -> None:
        result = normalize_adr_topic("[Memory]")
        assert result == ""


# ---------------------------------------------------------------------------
# adr_validation_reasons
# ---------------------------------------------------------------------------


class TestAdrValidationReasons:
    def test_valid_adr_body_returns_empty(self) -> None:
        body = (
            "## Context\n\nWe need to decide on X.\n\n"
            "## Decision\n\nWe will do Y because of reasons.\n\n"
            "## Consequences\n\nThis means Z will change and we need to update docs. "
            "Additional detail here to meet length."
        )
        assert adr_validation_reasons(body) == []

    def test_too_short_body(self) -> None:
        body = "## Context\n## Decision\n## Consequences\nShort."
        reasons = adr_validation_reasons(body)
        assert any("too short" in r for r in reasons)

    def test_missing_context_heading(self) -> None:
        body = (
            "## Decision\n\nWe will do Y.\n\n"
            "## Consequences\n\nThis changes Z.\n" + "x" * 120
        )
        reasons = adr_validation_reasons(body)
        assert any("## Context" in r for r in reasons)

    def test_missing_decision_heading(self) -> None:
        body = (
            "## Context\n\nWe need to decide.\n\n"
            "## Consequences\n\nThis changes Z.\n" + "x" * 120
        )
        reasons = adr_validation_reasons(body)
        assert any("## Decision" in r for r in reasons)

    def test_missing_consequences_heading(self) -> None:
        body = (
            "## Context\n\nWe need to decide.\n\n"
            "## Decision\n\nWe will do Y.\n" + "x" * 120
        )
        reasons = adr_validation_reasons(body)
        assert any("## Consequences" in r for r in reasons)

    def test_multiple_failures(self) -> None:
        body = "Short"
        reasons = adr_validation_reasons(body)
        assert len(reasons) == 2  # too short + missing all headings


# ---------------------------------------------------------------------------
# load_existing_adr_topics
# ---------------------------------------------------------------------------


class TestLoadExistingAdrTopics:
    def test_loads_topics_from_adr_dir(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-five-concurrent-loops.md").write_text("# ADR\n")
        (adr_dir / "0002-labels-state-machine.md").write_text("# ADR\n")
        (adr_dir / "README.md").write_text("# Index\n")

        topics = load_existing_adr_topics(tmp_path)
        assert "five concurrent loops" in topics
        assert "labels state machine" in topics

    def test_skips_readme(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "README.md").write_text("# Index\n")

        topics = load_existing_adr_topics(tmp_path)
        assert len(topics) == 0

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        topics = load_existing_adr_topics(tmp_path)
        assert topics == set()

    def test_strips_numeric_prefix(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0042-adopt-pydantic.md").write_text("# ADR\n")

        topics = load_existing_adr_topics(tmp_path)
        assert "adopt pydantic" in topics


# ---------------------------------------------------------------------------
# next_adr_number
# ---------------------------------------------------------------------------


class TestNextAdrNumber:
    @pytest.fixture(autouse=True)
    def _clear_assigned(self) -> Generator[None, None, None]:
        """Reset the module-level assigned set before and after each test."""
        import adr_utils

        adr_utils._assigned_adr_numbers.clear()
        yield
        adr_utils._assigned_adr_numbers.clear()

    def test_returns_one_for_empty_dir(self, tmp_path: Path) -> None:
        assert next_adr_number(tmp_path) == 1

    def test_returns_one_for_missing_dir(self, tmp_path: Path) -> None:
        assert next_adr_number(tmp_path / "nonexistent") == 1

    def test_increments_past_highest(self, tmp_path: Path) -> None:
        (tmp_path / "0001-first.md").touch()
        (tmp_path / "0003-third.md").touch()
        assert next_adr_number(tmp_path) == 4

    def test_ignores_non_adr_files(self, tmp_path: Path) -> None:
        (tmp_path / "0005-fifth.md").touch()
        (tmp_path / "README.md").touch()
        (tmp_path / "template.md").touch()
        assert next_adr_number(tmp_path) == 6

    def test_concurrent_calls_return_unique_numbers(self, tmp_path: Path) -> None:
        (tmp_path / "0002-existing.md").touch()
        results = [next_adr_number(tmp_path) for _ in range(5)]
        assert results == [3, 4, 5, 6, 7]

    def test_scans_primary_adr_dir(self, tmp_path: Path) -> None:
        local = tmp_path / "worktree" / "docs" / "adr"
        local.mkdir(parents=True)
        (local / "0001-local.md").touch()

        primary = tmp_path / "primary" / "docs" / "adr"
        primary.mkdir(parents=True)
        (primary / "0010-primary.md").touch()

        result = next_adr_number(local, primary_adr_dir=primary)
        assert result == 11

    def test_persists_numbers_to_dotfile(self, tmp_path: Path) -> None:
        """Assigned numbers are saved to .adr_assigned_numbers.json."""
        import json

        (tmp_path / "0005-existing.md").touch()
        next_adr_number(tmp_path)

        dotfile = tmp_path / ".adr_assigned_numbers.json"
        assert dotfile.is_file()
        data = json.loads(dotfile.read_text())
        assert 6 in data

    def test_survives_restart_via_dotfile(self, tmp_path: Path) -> None:
        """After clearing in-memory set, persisted numbers prevent reuse."""

        import adr_utils

        (tmp_path / "0005-existing.md").touch()
        result1 = next_adr_number(tmp_path)
        assert result1 == 6

        # Simulate restart: clear in-memory set
        adr_utils._assigned_adr_numbers.clear()

        # Next call should read dotfile and not reissue 6
        result2 = next_adr_number(tmp_path)
        assert result2 == 7

    def test_corrupted_dotfile_is_ignored(self, tmp_path: Path) -> None:
        """Corrupted dotfile should not crash — falls back to directory scan."""
        dotfile = tmp_path / ".adr_assigned_numbers.json"
        dotfile.write_text("NOT VALID JSON")
        (tmp_path / "0003-existing.md").touch()

        result = next_adr_number(tmp_path)
        assert result == 4

    def test_empty_dotfile_is_ignored(self, tmp_path: Path) -> None:
        """Empty dotfile should not crash."""
        dotfile = tmp_path / ".adr_assigned_numbers.json"
        dotfile.write_text("")

        result = next_adr_number(tmp_path)
        assert result == 1

    def test_persists_to_primary_dir_when_available(self, tmp_path: Path) -> None:
        """When primary_adr_dir is provided, dotfile is written there."""
        local = tmp_path / "worktree"
        local.mkdir()
        primary = tmp_path / "primary"
        primary.mkdir()
        (primary / "0003-existing.md").touch()

        next_adr_number(local, primary_adr_dir=primary)

        assert (primary / ".adr_assigned_numbers.json").is_file()
        # Local dir should not get the dotfile
        assert not (local / ".adr_assigned_numbers.json").is_file()


# ---------------------------------------------------------------------------
# ADR_FILE_RE
# ---------------------------------------------------------------------------


class TestAdrFileRe:
    def test_matches_four_digit_prefix(self) -> None:
        m = ADR_FILE_RE.match("0023-some-title.md")
        assert m is not None
        assert m.group(1) == "0023"

    def test_rejects_non_adr_filenames(self) -> None:
        assert ADR_FILE_RE.match("README.md") is None
        assert ADR_FILE_RE.match("abc-title.md") is None
        assert ADR_FILE_RE.match("00-short.md") is None
        assert ADR_FILE_RE.match("023-title.md") is None


# ---------------------------------------------------------------------------
# check_adr_duplicate
# ---------------------------------------------------------------------------


class TestCheckAdrDuplicate:
    def test_returns_topic_key_when_duplicate_exists(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-use-event-sourcing.md").write_text("# ADR\n")

        result = check_adr_duplicate("[ADR] Use event sourcing", tmp_path)
        assert result == "use event sourcing"

    def test_returns_none_when_no_duplicate(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-use-event-sourcing.md").write_text("# ADR\n")

        result = check_adr_duplicate("[ADR] Adopt pydantic", tmp_path)
        assert result is None

    def test_returns_none_for_empty_topic(self, tmp_path: Path) -> None:
        result = check_adr_duplicate("[ADR]", tmp_path)
        assert result is None

    def test_returns_none_when_no_adr_dir(self, tmp_path: Path) -> None:
        result = check_adr_duplicate("[ADR] Some topic", tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# extract_adr_section
# ---------------------------------------------------------------------------


class TestExtractAdrSection:
    def test_extracts_decision_section(self) -> None:
        body = (
            "## Context\n\nSome context.\n\n"
            "## Decision\n\nWe will use X for Y reasons.\n\n"
            "## Consequences\n\nThis means Z.\n"
        )
        result = extract_adr_section(body, "decision")
        assert result == "We will use X for Y reasons."

    def test_extracts_context_section(self) -> None:
        body = "## Context\n\nBackground info here.\n\n## Decision\n\nWe decided.\n"
        result = extract_adr_section(body, "context")
        assert result == "Background info here."

    def test_returns_empty_for_missing_section(self) -> None:
        body = "## Context\n\nSome context.\n"
        result = extract_adr_section(body, "decision")
        assert result == ""

    def test_case_insensitive_heading_match(self) -> None:
        body = "## DECISION\n\nAll caps heading content.\n\n## Consequences\n\nEnd.\n"
        result = extract_adr_section(body, "decision")
        assert result == "All caps heading content."

    def test_extracts_last_section_at_eof(self) -> None:
        body = "## Context\n\nCtx.\n\n## Consequences\n\nFinal section content.\n"
        result = extract_adr_section(body, "consequences")
        assert result == "Final section content."

    def test_empty_body(self) -> None:
        assert extract_adr_section("", "decision") == ""


# ---------------------------------------------------------------------------
# Backward compatibility — phase_utils re-exports
# ---------------------------------------------------------------------------
