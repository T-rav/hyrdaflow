"""Tests for the PromptBuilder utility."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from prompt_builder import PromptBuilder


def test_add_context_section_short_text_returned_unchanged() -> None:
    builder = PromptBuilder()
    result = builder.add_context_section("Issue body", "hello", 100)
    assert result == "hello"


def test_add_context_section_truncates_long_text() -> None:
    builder = PromptBuilder()
    long_text = "a" * 200
    result = builder.add_context_section("Issue body", long_text, 50)
    assert result.startswith("a" * 50)
    assert "truncated" in result.lower()
    assert len(result) > 50  # notice appended


def test_add_history_section_short_text_returned_unchanged() -> None:
    builder = PromptBuilder()
    result = builder.add_history_section("Cause", "error log", 500)
    assert result == "error log"


def test_add_history_section_truncates_long_text() -> None:
    builder = PromptBuilder()
    long_text = "b" * 300
    result = builder.add_history_section("Cause", long_text, 100)
    assert result.startswith("b" * 100)
    assert "truncated" in result.lower()


def test_build_stats_tracks_context_before_and_after() -> None:
    builder = PromptBuilder()
    body = "x" * 200
    builder.add_context_section("Issue body", body, 100)
    stats = builder.build_stats()
    assert stats["context_chars_before"] == 200
    assert stats["context_chars_after"] < 200
    assert stats["history_chars_before"] == 0
    assert stats["history_chars_after"] == 0


def test_build_stats_tracks_history_before_and_after() -> None:
    builder = PromptBuilder()
    builder.add_history_section("Cause", "c" * 500, 200)
    stats = builder.build_stats()
    assert stats["history_chars_before"] == 500
    assert stats["history_chars_after"] < 500
    assert stats["context_chars_before"] == 0
    assert stats["context_chars_after"] == 0


def test_build_stats_accumulates_multiple_sections() -> None:
    builder = PromptBuilder()
    builder.add_context_section("Issue body", "short", 100)
    builder.add_history_section("Cause", "d" * 300, 100)
    builder.add_history_section("Guidance", "e" * 200, 100)
    stats = builder.build_stats()
    assert stats["context_chars_before"] == 5  # "short"
    assert stats["history_chars_before"] == 500  # 300 + 200


def test_build_stats_computes_pruned_chars_total() -> None:
    builder = PromptBuilder()
    builder.add_context_section("Issue body", "f" * 1000, 100)
    stats = builder.build_stats()
    pruned = stats["pruned_chars_total"]
    assert isinstance(pruned, int)
    assert pruned > 0


def test_build_stats_includes_section_chars() -> None:
    builder = PromptBuilder()
    builder.add_context_section("Issue body", "hello", 100)
    stats = builder.build_stats()
    section_chars = stats["section_chars"]
    assert isinstance(section_chars, dict)
    assert "issue_body_before" in section_chars
    assert "issue_body_after" in section_chars


def test_empty_builder_returns_zero_stats() -> None:
    builder = PromptBuilder()
    stats = builder.build_stats()
    assert stats["history_chars_before"] == 0
    assert stats["history_chars_after"] == 0
    assert stats["context_chars_before"] == 0
    assert stats["context_chars_after"] == 0
    assert stats["pruned_chars_total"] == 0


def test_add_context_section_empty_string() -> None:
    builder = PromptBuilder()
    result = builder.add_context_section("Issue body", "", 100)
    assert result == ""
    stats = builder.build_stats()
    assert stats["context_chars_before"] == 0
    assert stats["context_chars_after"] == 0


def test_section_key_normalised_to_snake_case() -> None:
    builder = PromptBuilder()
    builder.add_context_section("Issue Body", "text", 100)
    stats = builder.build_stats()
    section_chars = stats["section_chars"]
    assert "issue_body_before" in section_chars
    assert "issue_body_after" in section_chars
