"""Tests for runner_constants module."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from runner_constants import MEMORY_SUGGESTION_PROMPT


class TestMemorySuggestionPrompt:
    """Tests for the MEMORY_SUGGESTION_PROMPT constant."""

    def test_contains_start_marker(self) -> None:
        assert "MEMORY_SUGGESTION_START" in MEMORY_SUGGESTION_PROMPT

    def test_contains_end_marker(self) -> None:
        assert "MEMORY_SUGGESTION_END" in MEMORY_SUGGESTION_PROMPT

    def test_contains_context_placeholder(self) -> None:
        assert "{context}" in MEMORY_SUGGESTION_PROMPT

    def test_format_with_implementation_context(self) -> None:
        result = MEMORY_SUGGESTION_PROMPT.format(context="implementation")
        assert "implementation" in result
        assert "{context}" not in result

    def test_format_with_planning_context(self) -> None:
        result = MEMORY_SUGGESTION_PROMPT.format(context="planning")
        assert "planning" in result

    def test_format_with_review_context(self) -> None:
        result = MEMORY_SUGGESTION_PROMPT.format(context="review")
        assert "review" in result

    def test_format_with_correction_context(self) -> None:
        result = MEMORY_SUGGESTION_PROMPT.format(context="correction")
        assert "correction" in result

    def test_contains_type_definitions(self) -> None:
        assert "knowledge" in MEMORY_SUGGESTION_PROMPT
        assert "config" in MEMORY_SUGGESTION_PROMPT
        assert "instruction" in MEMORY_SUGGESTION_PROMPT
        assert "code" in MEMORY_SUGGESTION_PROMPT

    def test_contains_field_definitions(self) -> None:
        assert "title:" in MEMORY_SUGGESTION_PROMPT
        assert "type:" in MEMORY_SUGGESTION_PROMPT
        assert "learning:" in MEMORY_SUGGESTION_PROMPT
        assert "context:" in MEMORY_SUGGESTION_PROMPT
