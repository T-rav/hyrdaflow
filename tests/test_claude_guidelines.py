from __future__ import annotations

from pathlib import Path


def _quality_before_completion_section() -> str:
    """Extract the Quality Before Completion section from CLAUDE.md."""
    content = Path("CLAUDE.md").read_text()
    marker = "## Quality Before Completion"
    start = content.index(marker) + len(marker)
    remainder = content[start:]
    # Section ends at next level-2 heading or EOF.
    end = remainder.find("\n## ")
    if end == -1:
        return remainder
    return remainder[:end]


def test_quality_section_mentions_redundant_guard_merge_instruction():
    section = _quality_before_completion_section()
    assert (
        "Merge consecutive identical if-conditions so the shared guard is evaluated once"
        in section
    ), section


def test_quality_section_includes_example_patterns():
    section = _quality_before_completion_section()
    assert "`if A and B: ... elif A and not B: ...`" in section
    assert "`if A: if B: ... else: ...`" in section
