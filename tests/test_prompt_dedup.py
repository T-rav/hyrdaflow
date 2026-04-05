"""Tests for PromptDeduplicator."""

from prompt_dedup import PromptDeduplicator, _split_paragraphs


def test_is_duplicate_first_seen():
    d = PromptDeduplicator()
    assert d.is_duplicate("hello world") is False


def test_is_duplicate_second_seen():
    d = PromptDeduplicator()
    d.is_duplicate("hello world")
    assert d.is_duplicate("hello world") is True


def test_is_duplicate_different_content():
    d = PromptDeduplicator()
    d.is_duplicate("hello world")
    assert d.is_duplicate("goodbye world") is False


def test_dedup_memories_removes_overlapping():
    d = PromptDeduplicator()
    memories = [
        "Always run lint before committing code changes",
        "Always run lint before committing code",  # >70% overlap with first
        "Use async for I/O bound operations",
    ]
    result = d.dedup_memories(memories)
    assert len(result) == 2
    assert "Always run lint" in result[0]
    assert "async" in result[1]


def test_dedup_memories_keeps_unique():
    d = PromptDeduplicator()
    memories = [
        "Always run lint before committing",
        "Use async for I/O operations",
        "Check security headers in API routes",
    ]
    result = d.dedup_memories(memories)
    assert len(result) == 3


def test_dedup_memories_empty():
    d = PromptDeduplicator()
    assert d.dedup_memories([]) == []


def test_dedup_memories_short_words_ignored():
    d = PromptDeduplicator()
    memories = [
        "a b c d e f",  # all short words
        "x y z w v u",
    ]
    result = d.dedup_memories(memories)
    assert len(result) == 2  # no overlap since no words >= 4 chars


# ------------------------------------------------------------------
# dedup_sections tests
# ------------------------------------------------------------------


def test_dedup_sections_no_overlap():
    """Distinct sections are kept intact."""
    d = PromptDeduplicator()
    sections, chars_saved = d.dedup_sections(
        (
            "Issue body",
            "This is a unique paragraph that describes the issue in detail and should not be deduplicated at all.",
        ),
        (
            "Plan",
            "This is the implementation plan with completely different content that does not overlap with other sections.",
        ),
    )
    assert len(sections) == 2
    assert chars_saved == 0
    assert sections[0][0] == "Issue body"
    assert sections[1][0] == "Plan"
    # Content should be unchanged
    assert "unique paragraph" in sections[0][1]
    assert "implementation plan" in sections[1][1]


def test_dedup_sections_duplicate_paragraph():
    """A paragraph duplicated across sections is replaced with a back-reference."""
    shared = "This is a long paragraph that appears in both the issue body and the plan section and should be deduplicated."
    d = PromptDeduplicator()
    sections, chars_saved = d.dedup_sections(
        ("Issue body", shared),
        ("Plan", f"Some unique intro.\n\n{shared}\n\nSome unique outro."),
    )
    assert chars_saved > 0
    # The first section keeps the paragraph
    assert "long paragraph" in sections[0][1]
    # The second section has a back-reference instead
    assert "Content already provided in Issue body" in sections[1][1]
    # The unique parts of the second section are kept
    assert "unique intro" in sections[1][1]
    assert "unique outro" in sections[1][1]


def test_dedup_sections_short_paragraphs_kept():
    """Paragraphs shorter than the threshold are never deduplicated."""
    short = "Short text."
    d = PromptDeduplicator()
    sections, chars_saved = d.dedup_sections(
        ("A", short),
        ("B", short),
    )
    assert chars_saved == 0
    assert sections[0][1] == short
    assert sections[1][1] == short


def test_dedup_sections_empty_content():
    """Empty sections pass through unchanged."""
    d = PromptDeduplicator()
    sections, chars_saved = d.dedup_sections(
        ("A", ""),
        (
            "B",
            "Some real content that is long enough to be considered for deduplication by the algorithm.",
        ),
    )
    assert chars_saved == 0
    assert sections[0][1] == ""
    assert "real content" in sections[1][1]


def test_dedup_sections_multiple_duplicates():
    """Multiple paragraphs can be deduped across several sections."""
    para1 = "First shared paragraph that is long enough to exceed the minimum character threshold for dedup processing."
    para2 = "Second shared paragraph that is also long enough to be considered a duplicate when seen in another section."
    d = PromptDeduplicator()
    sections, chars_saved = d.dedup_sections(
        ("Issue body", f"{para1}\n\n{para2}"),
        ("Plan", f"{para1}\n\nUnique plan content here."),
        ("Memory", f"{para2}\n\nUnique memory content here."),
    )
    assert chars_saved > 0
    # Plan's copy of para1 should be a back-reference
    assert "Content already provided in Issue body" in sections[1][1]
    # Memory's copy of para2 should be a back-reference
    assert "Content already provided in Issue body" in sections[2][1]
    # Unique content preserved
    assert "Unique plan content" in sections[1][1]
    assert "Unique memory content" in sections[2][1]


def test_dedup_sections_returns_chars_saved():
    """chars_saved reflects the total characters replaced."""
    shared = "A" * 100  # Exactly 100 chars, above the 80-char threshold
    d = PromptDeduplicator()
    _, chars_saved = d.dedup_sections(
        ("A", shared),
        ("B", shared),
    )
    assert chars_saved == 100


def test_split_paragraphs():
    """_split_paragraphs splits on blank lines and drops empties."""
    text = "para one\n\npara two\n\n\npara three"
    result = _split_paragraphs(text)
    assert result == ["para one", "para two", "para three"]


def test_split_paragraphs_empty():
    assert _split_paragraphs("") == []
    assert _split_paragraphs("\n\n\n") == []


# ------------------------------------------------------------------
# Architectural coverage: dedup is applied in base_runner for memory,
# and in agent/planner for cross-section paragraph dedup.
# ------------------------------------------------------------------


def test_base_runner_inject_calls_dedup(monkeypatch):
    """BaseRunner._inject_manifest_and_memory uses PromptDeduplicator.

    The base runner deduplicates memory items across Hindsight banks.
    """
    import inspect

    import base_runner as br_mod

    source = inspect.getsource(br_mod.BaseRunner._inject_manifest_and_memory)
    assert "PromptDeduplicator" in source
    assert "dedup_memories" in source


def test_agent_prompt_uses_section_dedup(monkeypatch):
    """AgentRunner._build_prompt_with_stats uses cross-section dedup.

    The agent deduplicates overlapping paragraphs across prompt sections
    (issue body, plan, review feedback, comments, memory) before assembly.
    """
    import inspect

    import agent as agent_mod

    source = inspect.getsource(agent_mod.AgentRunner._build_prompt_with_stats)
    assert "_inject_manifest_and_memory" in source
    assert "dedup_sections" in source


def test_planner_prompt_uses_section_dedup(monkeypatch):
    """PlannerRunner._build_prompt_with_stats uses cross-section dedup.

    The planner deduplicates overlapping paragraphs across prompt sections
    (issue body, comments, research, memory) before assembly.
    """
    import inspect

    import planner as planner_mod

    source = inspect.getsource(planner_mod.PlannerRunner._build_prompt_with_stats)
    assert "_inject_manifest_and_memory" in source
    assert "dedup_sections" in source
