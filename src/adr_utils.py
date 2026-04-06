"""ADR (Architecture Decision Record) utilities.

Extracted from ``phase_utils`` to break the circular dependency:

    phase_utils -> memory -> phase_utils (deferred import)

After extraction, ``memory.py`` imports directly from this module at the
top level instead of using a deferred import from ``phase_utils``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

__all__ = [
    "ADR_FILE_RE",
    "adr_validation_reasons",
    "check_adr_duplicate",
    "extract_adr_section",
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

# Dotfile in the ADR directory that persists assigned numbers across restarts.
_ASSIGNED_NUMBERS_FILE = ".adr_assigned_numbers.json"


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


def check_adr_duplicate(title: str, repo_root: Path) -> str | None:
    """Check if an ADR topic already exists in ``docs/adr/``.

    Returns the normalized topic key if a duplicate is found, ``None`` otherwise.
    """
    topic_key = normalize_adr_topic(title)
    if not topic_key:
        return None
    existing = load_existing_adr_topics(repo_root)
    if topic_key in existing:
        return topic_key
    return None


def extract_adr_section(body: str, heading: str) -> str:
    """Extract a markdown section body by heading name (case-insensitive)."""
    pattern = (
        r"(?ims)^##\s+" + re.escape(heading) + r"\s*\n(?P<section>.*?)(?=^##\s+|\Z)"
    )
    match = re.search(pattern, body)
    return match.group("section").strip() if match else ""


def _load_persisted_numbers(adr_dir: Path) -> set[int]:
    """Load previously assigned ADR numbers from the persistent dotfile."""
    path = adr_dir / _ASSIGNED_NUMBERS_FILE
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {int(n) for n in data}
    except (OSError, json.JSONDecodeError, ValueError):
        logger.warning("Failed to read %s — ignoring", path)
    return set()


def _save_persisted_numbers(adr_dir: Path, numbers: set[int]) -> None:
    """Persist assigned ADR numbers to the dotfile."""
    path = adr_dir / _ASSIGNED_NUMBERS_FILE
    try:
        adr_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(numbers), indent=2) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("Failed to write %s — number may be reused on restart", path)


def next_adr_number(
    adr_dir: Path,
    *,
    primary_adr_dir: Path | None = None,
) -> int:
    """Return the next available ADR number, unique across concurrent workers.

    Scans both the local *adr_dir* **and** the *primary_adr_dir* (the
    primary repo checkout, not a worktree copy) to find the highest
    existing number.  Also considers numbers already handed out via
    ``_assigned_adr_numbers`` (in-memory) and the persistent dotfile
    ``.adr_assigned_numbers.json`` so that numbers survive process
    restarts.

    The returned number is recorded in both the in-memory set and the
    persistent dotfile so subsequent calls — even after restart — will
    never return the same value.
    """
    # Merge persisted numbers from both directories into the in-memory set
    for d in (adr_dir, primary_adr_dir):
        if d is not None and d.is_dir():
            _assigned_adr_numbers.update(_load_persisted_numbers(d))

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

    # Persist to the primary ADR directory (or the local one if no primary)
    persist_dir = (
        primary_adr_dir if primary_adr_dir and primary_adr_dir.is_dir() else adr_dir
    )
    _save_persisted_numbers(persist_dir, _assigned_adr_numbers)

    return number
