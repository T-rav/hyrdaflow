"""Tests for troubleshooting pattern store (Hindsight-backed)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from troubleshooting_store import (
    TroubleshootingPattern,
    TroubleshootingPatternStore,
    extract_troubleshooting_pattern,
    format_patterns_for_prompt,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pattern(**overrides: object) -> TroubleshootingPattern:
    defaults: dict[str, object] = {
        "language": "python",
        "pattern_name": "truthy_asyncmock",
        "description": "AsyncMock without return_value",
        "fix_strategy": "Set return_value to falsy",
    }
    defaults.update(overrides)
    return TroubleshootingPattern(**defaults)  # type: ignore[arg-type]


def _make_hindsight_memory(content: str, **kwargs: object) -> MagicMock:
    """Create a mock HindsightMemory with the given content."""
    mem = MagicMock()
    mem.content = content
    for k, v in kwargs.items():
        setattr(mem, k, v)
    return mem


# ---------------------------------------------------------------------------
# TroubleshootingPattern model
# ---------------------------------------------------------------------------


class TestTroubleshootingPattern:
    def test_default_frequency_is_one(self) -> None:
        p = _make_pattern()
        assert p.frequency == 1

    def test_source_issues_default_empty(self) -> None:
        p = _make_pattern()
        assert p.source_issues == []


# ---------------------------------------------------------------------------
# TroubleshootingPatternStore — record_pattern
# ---------------------------------------------------------------------------


class TestRecordPattern:
    @pytest.mark.asyncio
    async def test_record_calls_retain_safe(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)
        pattern = _make_pattern(source_issues=[42])

        with patch("hindsight.retain_safe", new_callable=AsyncMock) as mock_retain:
            await store.record_pattern(pattern)

            mock_retain.assert_awaited_once()
            args, kwargs = mock_retain.call_args
            # First positional arg is the hindsight client
            assert args[0] is hindsight
            # Second is the bank name
            assert args[1] == "hydraflow-troubleshooting"
            # Third is the content string
            assert "truthy_asyncmock" in args[2]
            assert "Set return_value to falsy" in args[2]
            # Keyword args
            assert "context" in kwargs
            assert "python" in kwargs["context"]
            assert kwargs["metadata"]["language"] == "python"
            assert kwargs["metadata"]["pattern_name"] == "truthy_asyncmock"

    @pytest.mark.asyncio
    async def test_record_pattern_includes_description_in_content(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)
        pattern = _make_pattern(description="AsyncMock returns truthy")

        with patch("hindsight.retain_safe", new_callable=AsyncMock) as mock_retain:
            await store.record_pattern(pattern)

            content = mock_retain.call_args[0][2]
            assert "AsyncMock returns truthy" in content


# ---------------------------------------------------------------------------
# TroubleshootingPatternStore — load_patterns
# ---------------------------------------------------------------------------


class TestLoadPatterns:
    @pytest.mark.asyncio
    async def test_load_returns_empty_when_no_memories(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await store.load_patterns()
            assert result == []

    @pytest.mark.asyncio
    async def test_load_deserializes_patterns(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)
        pattern = _make_pattern(frequency=3)
        memory = _make_hindsight_memory(pattern.model_dump_json())

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=[memory],
        ):
            result = await store.load_patterns()
            assert len(result) == 1
            assert result[0].pattern_name == "truthy_asyncmock"
            assert result[0].frequency == 3

    @pytest.mark.asyncio
    async def test_load_filters_by_language(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)
        py_pattern = _make_pattern(language="python", pattern_name="py_pat")
        node_pattern = _make_pattern(language="node", pattern_name="node_pat")
        memories = [
            _make_hindsight_memory(py_pattern.model_dump_json()),
            _make_hindsight_memory(node_pattern.model_dump_json()),
        ]

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=memories,
        ):
            result = await store.load_patterns(language="python")
            names = [p.pattern_name for p in result]
            assert "py_pat" in names
            assert "node_pat" not in names

    @pytest.mark.asyncio
    async def test_load_includes_general_patterns(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)
        general = _make_pattern(language="general", pattern_name="generic_hang")
        py = _make_pattern(language="python", pattern_name="py_hang")
        memories = [
            _make_hindsight_memory(general.model_dump_json()),
            _make_hindsight_memory(py.model_dump_json()),
        ]

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=memories,
        ):
            result = await store.load_patterns(language="python")
            names = [p.pattern_name for p in result]
            assert "generic_hang" in names
            assert "py_hang" in names

    @pytest.mark.asyncio
    async def test_load_sorts_by_frequency_descending(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)
        rare = _make_pattern(pattern_name="rare", frequency=1)
        common = _make_pattern(pattern_name="common", frequency=5)
        memories = [
            _make_hindsight_memory(rare.model_dump_json()),
            _make_hindsight_memory(common.model_dump_json()),
        ]

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=memories,
        ):
            result = await store.load_patterns()
            assert result[0].pattern_name == "common"
            assert result[1].pattern_name == "rare"

    @pytest.mark.asyncio
    async def test_load_respects_limit(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)
        memories = [
            _make_hindsight_memory(
                _make_pattern(pattern_name=f"p{i}").model_dump_json()
            )
            for i in range(5)
        ]

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=memories,
        ):
            result = await store.load_patterns(limit=2)
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_load_skips_malformed_memories(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)
        valid = _make_pattern()
        memories = [
            _make_hindsight_memory("not valid json at all"),
            _make_hindsight_memory(valid.model_dump_json()),
        ]

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=memories,
        ):
            result = await store.load_patterns()
            assert len(result) == 1
            assert result[0].pattern_name == "truthy_asyncmock"

    @pytest.mark.asyncio
    async def test_load_builds_language_query(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_recall:
            await store.load_patterns(language="python")
            query = mock_recall.call_args[0][2]
            assert "python" in query

    @pytest.mark.asyncio
    async def test_load_without_language_uses_generic_query(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_recall:
            await store.load_patterns()
            query = mock_recall.call_args[0][2]
            assert "troubleshooting patterns" in query

    @pytest.mark.asyncio
    async def test_load_limit_none_returns_all(self) -> None:
        hindsight = AsyncMock()
        store = TroubleshootingPatternStore(hindsight)
        memories = [
            _make_hindsight_memory(
                _make_pattern(pattern_name=f"p{i}").model_dump_json()
            )
            for i in range(15)
        ]

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            return_value=memories,
        ):
            result = await store.load_patterns(limit=None)
            assert len(result) == 15


# ---------------------------------------------------------------------------
# format_patterns_for_prompt
# ---------------------------------------------------------------------------


class TestFormatPatternsForPrompt:
    def test_empty_returns_empty(self) -> None:
        assert format_patterns_for_prompt([]) == ""

    def test_renders_markdown(self) -> None:
        patterns = [_make_pattern(frequency=3, description="AsyncMock returns truthy")]
        result = format_patterns_for_prompt(patterns)
        assert "## Learned Patterns from Previous Fixes" in result
        assert "truthy_asyncmock" in result
        assert "python" in result
        assert "3x" in result
        assert "AsyncMock returns truthy" in result

    def test_respects_char_limit(self) -> None:
        patterns = [
            _make_pattern(
                pattern_name=f"pattern_{i}",
                description="A" * 200,
                fix_strategy="B" * 200,
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
