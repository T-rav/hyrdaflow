"""Tests for troubleshooting pattern store."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from troubleshooting_store import (
    TroubleshootingPattern,
    TroubleshootingPatternStore,
    extract_troubleshooting_pattern,
    format_patterns_for_prompt,
)

# ---------------------------------------------------------------------------
# TroubleshootingPattern model
# ---------------------------------------------------------------------------


class TestTroubleshootingPattern:
    def test_default_frequency_is_one(self) -> None:
        p = TroubleshootingPattern(
            language="python",
            pattern_name="truthy_asyncmock",
            description="AsyncMock without return_value",
            fix_strategy="Set return_value to falsy",
        )
        assert p.frequency == 1

    def test_source_issues_default_empty(self) -> None:
        p = TroubleshootingPattern(
            language="python",
            pattern_name="truthy_asyncmock",
            description="d",
            fix_strategy="f",
        )
        assert p.source_issues == []


# ---------------------------------------------------------------------------
# TroubleshootingPatternStore
# ---------------------------------------------------------------------------


class TestTroubleshootingPatternStore:
    def test_append_creates_file(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        p = TroubleshootingPattern(
            language="python",
            pattern_name="test_pattern",
            description="desc",
            fix_strategy="fix",
            source_issues=[42],
        )
        store.append_pattern(p)
        assert (tmp_path / "memory" / "troubleshooting_patterns.jsonl").exists()

    def test_store_roundtrip_preserves_data(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        p = TroubleshootingPattern(
            language="python",
            pattern_name="truthy_asyncmock",
            description="AsyncMock returns truthy",
            fix_strategy="Set return_value",
            source_issues=[42],
        )
        store.append_pattern(p)

        loaded = store.load_patterns()
        assert len(loaded) == 1
        assert loaded[0].pattern_name == "truthy_asyncmock"
        assert loaded[0].description == "AsyncMock returns truthy"
        assert loaded[0].source_issues == [42]

    def test_dedup_increments_frequency(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        p1 = TroubleshootingPattern(
            language="python",
            pattern_name="truthy_asyncmock",
            description="d",
            fix_strategy="f",
            source_issues=[10],
        )
        p2 = TroubleshootingPattern(
            language="python",
            pattern_name="truthy_asyncmock",
            description="d",
            fix_strategy="f",
            source_issues=[20],
        )
        store.append_pattern(p1)
        store.append_pattern(p2)

        loaded = store.load_patterns()
        assert len(loaded) == 1
        assert loaded[0].frequency == 2

    def test_dedup_merges_source_issues(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        p1 = TroubleshootingPattern(
            language="python",
            pattern_name="hang",
            description="d",
            fix_strategy="f",
            source_issues=[10, 20],
        )
        p2 = TroubleshootingPattern(
            language="python",
            pattern_name="hang",
            description="d",
            fix_strategy="f",
            source_issues=[20, 30],
        )
        store.append_pattern(p1)
        store.append_pattern(p2)

        loaded = store.load_patterns()
        assert loaded[0].source_issues == [10, 20, 30]

    def test_filter_by_language(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        store.append_pattern(
            TroubleshootingPattern(
                language="python",
                pattern_name="py_pattern",
                description="d",
                fix_strategy="f",
            )
        )
        store.append_pattern(
            TroubleshootingPattern(
                language="node",
                pattern_name="node_pattern",
                description="d",
                fix_strategy="f",
            )
        )

        loaded = store.load_patterns(language="python")
        names = [p.pattern_name for p in loaded]
        assert "py_pattern" in names
        assert "node_pattern" not in names

    def test_includes_general_patterns(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        store.append_pattern(
            TroubleshootingPattern(
                language="general",
                pattern_name="generic_hang",
                description="d",
                fix_strategy="f",
            )
        )
        store.append_pattern(
            TroubleshootingPattern(
                language="python",
                pattern_name="py_hang",
                description="d",
                fix_strategy="f",
            )
        )

        loaded = store.load_patterns(language="python")
        names = [p.pattern_name for p in loaded]
        assert "generic_hang" in names
        assert "py_hang" in names

    def test_sort_by_frequency(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        store.append_pattern(
            TroubleshootingPattern(
                language="python",
                pattern_name="rare",
                description="d",
                fix_strategy="f",
                frequency=1,
            )
        )
        store.append_pattern(
            TroubleshootingPattern(
                language="python",
                pattern_name="common",
                description="d",
                fix_strategy="f",
                frequency=5,
            )
        )

        loaded = store.load_patterns()
        assert loaded[0].pattern_name == "common"
        assert loaded[1].pattern_name == "rare"

    def test_respects_limit(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        for i in range(5):
            store.append_pattern(
                TroubleshootingPattern(
                    language="python",
                    pattern_name=f"pattern_{i}",
                    description="d",
                    fix_strategy="f",
                )
            )

        loaded = store.load_patterns(limit=2)
        assert len(loaded) == 2

    def test_increment_frequency(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        store.append_pattern(
            TroubleshootingPattern(
                language="python",
                pattern_name="test_pat",
                description="d",
                fix_strategy="f",
            )
        )
        store.increment_frequency("python", "test_pat")

        loaded = store.load_patterns()
        assert loaded[0].frequency == 2

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        assert store.load_patterns() == []

    def test_malformed_line_skipped(self, tmp_path: Path) -> None:
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir(parents=True)
        jsonl = mem_dir / "troubleshooting_patterns.jsonl"
        jsonl.write_text("not valid json\n")

        store = TroubleshootingPatternStore(mem_dir)
        loaded = store.load_patterns()
        assert loaded == []

    def test_dedup_case_insensitive(self, tmp_path: Path) -> None:
        store = TroubleshootingPatternStore(tmp_path / "memory")
        store.append_pattern(
            TroubleshootingPattern(
                language="Python",
                pattern_name="Truthy_AsyncMock",
                description="d",
                fix_strategy="f",
                source_issues=[1],
            )
        )
        store.append_pattern(
            TroubleshootingPattern(
                language="python",
                pattern_name="truthy_asyncmock",
                description="d",
                fix_strategy="f",
                source_issues=[2],
            )
        )

        loaded = store.load_patterns()
        assert len(loaded) == 1
        assert loaded[0].frequency == 2


# ---------------------------------------------------------------------------
# format_patterns_for_prompt
# ---------------------------------------------------------------------------


class TestFormatPatternsForPrompt:
    def test_empty_returns_empty(self) -> None:
        assert format_patterns_for_prompt([]) == ""

    def test_renders_markdown(self) -> None:
        patterns = [
            TroubleshootingPattern(
                language="python",
                pattern_name="truthy_asyncmock",
                description="AsyncMock returns truthy",
                fix_strategy="Set return_value",
                frequency=3,
            )
        ]
        result = format_patterns_for_prompt(patterns)
        assert "## Learned Patterns from Previous Fixes" in result
        assert "truthy_asyncmock" in result
        assert "python" in result
        assert "3x" in result
        assert "AsyncMock returns truthy" in result
        assert "Set return_value" in result

    def test_respects_char_limit(self) -> None:
        patterns = [
            TroubleshootingPattern(
                language="python",
                pattern_name=f"pattern_{i}",
                description="A" * 200,
                fix_strategy="B" * 200,
                frequency=1,
            )
            for i in range(20)
        ]
        result = format_patterns_for_prompt(patterns, max_chars=500)
        assert "truncated" in result
        assert "omitted" in result


# ---------------------------------------------------------------------------
# extract_troubleshooting_pattern
# ---------------------------------------------------------------------------


class TestExtractTroubleshootingPattern:
    def test_extracts_structured_block(self) -> None:
        transcript = """Some agent output here...

TROUBLESHOOTING_PATTERN_START
pattern_name: truthy_asyncmock
description: AsyncMock without return_value returns truthy MagicMock
fix_strategy: Set return_value to a falsy value matching the return type
TROUBLESHOOTING_PATTERN_END

More output..."""

        result = extract_troubleshooting_pattern(transcript, 42, "python")
        assert result is not None
        assert result.pattern_name == "truthy_asyncmock"
        assert (
            result.description
            == "AsyncMock without return_value returns truthy MagicMock"
        )
        assert (
            result.fix_strategy
            == "Set return_value to a falsy value matching the return type"
        )
        assert result.language == "python"
        assert result.source_issues == [42]

    def test_returns_none_when_no_block(self) -> None:
        transcript = "Just regular output with no pattern block."
        result = extract_troubleshooting_pattern(transcript, 42, "python")
        assert result is None

    def test_returns_none_when_missing_required_fields(self) -> None:
        transcript = """
TROUBLESHOOTING_PATTERN_START
pattern_name: incomplete
TROUBLESHOOTING_PATTERN_END
"""
        result = extract_troubleshooting_pattern(transcript, 42, "python")
        assert result is None

    def test_sets_language_from_parameter(self) -> None:
        transcript = """
TROUBLESHOOTING_PATTERN_START
pattern_name: channel_deadlock
description: Unbuffered channel causes deadlock
fix_strategy: Use buffered channel or separate goroutine
TROUBLESHOOTING_PATTERN_END
"""
        result = extract_troubleshooting_pattern(transcript, 10, "go")
        assert result is not None
        assert result.language == "go"
        assert result.source_issues == [10]

    def test_handles_extra_whitespace(self) -> None:
        transcript = """
TROUBLESHOOTING_PATTERN_START
  pattern_name:   spaced_pattern
  description:   some description with spaces
  fix_strategy:   some fix strategy
TROUBLESHOOTING_PATTERN_END
"""
        result = extract_troubleshooting_pattern(transcript, 1, "python")
        assert result is not None
        assert result.pattern_name == "spaced_pattern"
