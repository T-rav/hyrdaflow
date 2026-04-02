"""ADR (Architecture Decision Record) utilities.

Extracted from ``phase_utils`` to break the circular dependency:

    phase_utils -> memory -> phase_utils (deferred import)

After extraction, ``memory.py`` imports directly from this module at the
top level instead of using a deferred import from ``phase_utils``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

__all__ = [
    "ADR_FILE_RE",
    "adr_validation_reasons",
    "is_adr_issue_title",
    "load_existing_adr_topics",
    "next_adr_number",
    "normalize_adr_topic",
]

logger = logging.getLogger("hydraflow.adr_utils")

_ADR_TITLE_RE = re.compile(r"^\s*\[ADR\]\s+", re.IGNORECASE)
_ADR_REQUIRED_HEADINGS = ("## Context", "## Decision", "## Consequences")

# Module-level set tracking ADR numbers already handed out in this process,
# so concurrent workers each get a unique number even before their files land.
_assigned_adr_numbers: set[int] = set()

ADR_FILE_RE = re.compile(r"^(\d{4})-.*\.md$")


def is_adr_issue_title(title: str) -> bool:
    """Return ``True`` when *title* starts with ``[ADR]`` (case-insensitive)."""
    return bool(_ADR_TITLE_RE.match(title))


def adr_validation_reasons(body: str) -> list[str]:
    """Return shape-validation failures for ADR markdown content."""
    reasons: list[str] = []
    text = body.strip()
    if len(text) < 120:
        reasons.append("ADR body is too short (minimum 120 characters)")
    lower = text.lower()
    missing = [h for h in _ADR_REQUIRED_HEADINGS if h.lower() not in lower]
    if missing:
        reasons.append("Missing required ADR sections: " + ", ".join(missing))
    return reasons


def normalize_adr_topic(title: str) -> str:
    """Extract a normalized topic key from a memory/ADR title for dedup.

    Strips prefixes like ``[Memory]``, ``[ADR] Draft decision from memory #N:``,
    lowercases, and removes non-alphanumeric characters.
    """
    cleaned = re.sub(
        r"^\[(?:Memory|ADR)\]\s*(?:Draft decision from memory #\d+:\s*)?",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    return re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()


def load_existing_adr_topics(repo_root: Path) -> set[str]:
    """Scan ``docs/adr/`` files and return normalized topic keys."""
    adr_dir = repo_root / "docs" / "adr"
    topics: set[str] = set()
    if not adr_dir.is_dir():
        return topics
    for path in adr_dir.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        stem = path.stem
        cleaned = re.sub(r"^\d+-", "", stem)
        topic = re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()
        if topic:
            topics.add(topic)
    return topics


def next_adr_number(
    adr_dir: Path,
    *,
    primary_adr_dir: Path | None = None,
) -> int:
    """Return the next available ADR number, unique across concurrent workers.

    Scans both the local *adr_dir* **and** the *primary_adr_dir* (the
    primary repo checkout, not a worktree copy) to find the highest
    existing number.  Also considers numbers already handed out via
    ``_assigned_adr_numbers`` so that concurrent workers in the same
    process each receive a distinct number.

    The returned number is recorded in ``_assigned_adr_numbers`` so
    subsequent calls will never return the same value.
    """
    highest = 0
    for d in (adr_dir, primary_adr_dir):
        if d is not None and d.is_dir():
            for f in d.iterdir():
                m = ADR_FILE_RE.match(f.name)
                if m:
                    highest = max(highest, int(m.group(1)))

    if _assigned_adr_numbers:
        highest = max(highest, *_assigned_adr_numbers)

    number = highest + 1
    _assigned_adr_numbers.add(number)
    return number
