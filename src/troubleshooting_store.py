"""Troubleshooting pattern store — persists learned CI timeout fix patterns.

Successful CI timeout fixes can emit a structured block in their transcript.
This module extracts those patterns, persists them to a JSONL store, and
formats them for injection into future fix prompts — creating a feedback loop
that makes the unsticker smarter with each resolved hang.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from models import IsoTimestamp

logger = logging.getLogger("hydraflow.troubleshooting_store")

# Delimiters the agent uses to emit a learned pattern
_PATTERN_START = "TROUBLESHOOTING_PATTERN_START"
_PATTERN_END = "TROUBLESHOOTING_PATTERN_END"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class TroubleshootingPattern(BaseModel):
    """A single learned troubleshooting pattern."""

    language: str = Field(description="Detected stack: python, node, general, etc.")
    pattern_name: str = Field(description="Short key, e.g. truthy_asyncmock")
    description: str = Field(description="What causes the hang")
    fix_strategy: str = Field(description="How to fix it")
    frequency: int = Field(default=1, ge=1, description="Times observed")
    source_issues: list[int] = Field(
        default_factory=list, description="Issue numbers where observed"
    )
    timestamp: IsoTimestamp = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class TroubleshootingPatternStore:
    """JSONL-backed store for learned troubleshooting patterns."""

    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir
        self._path = memory_dir / "troubleshooting_patterns.jsonl"

    def append_pattern(self, pattern: TroubleshootingPattern) -> None:
        """Append or merge *pattern* into the store.

        Deduplicates by ``(language, pattern_name)`` — on collision the
        existing record's frequency and source_issues are merged.
        """
        all_patterns = self._load_all()
        key = (pattern.language.lower(), pattern.pattern_name.lower())
        merged = False

        for i, existing in enumerate(all_patterns):
            if (existing.language.lower(), existing.pattern_name.lower()) == key:
                existing.frequency += pattern.frequency
                existing.source_issues = sorted(
                    set(existing.source_issues) | set(pattern.source_issues)
                )
                all_patterns[i] = existing
                merged = True
                break

        if not merged:
            all_patterns.append(pattern)

        self._write_all(all_patterns)

    def load_patterns(
        self, *, language: str | None = None, limit: int | None = 10
    ) -> list[TroubleshootingPattern]:
        """Load patterns filtered by *language* (always includes ``"general"``).

        Returns up to *limit* patterns sorted by frequency descending.
        Pass ``limit=None`` to return all patterns without a cap.
        """
        all_patterns = self._load_all()
        if language:
            lang_lower = language.lower()
            all_patterns = [
                p
                for p in all_patterns
                if p.language.lower() == lang_lower or p.language.lower() == "general"
            ]
        all_patterns.sort(key=lambda p: p.frequency, reverse=True)
        return all_patterns if limit is None else all_patterns[:limit]

    def increment_frequency(self, language: str, pattern_name: str) -> None:
        """Bump the frequency counter for an existing pattern."""
        all_patterns = self._load_all()
        key = (language.lower(), pattern_name.lower())
        for i, existing in enumerate(all_patterns):
            if (existing.language.lower(), existing.pattern_name.lower()) == key:
                existing.frequency += 1
                all_patterns[i] = existing
                self._write_all(all_patterns)
                return

    # -- internal ---------------------------------------------------------

    def _load_all(self) -> list[TroubleshootingPattern]:
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text().strip().splitlines()
        except OSError:
            return []
        patterns: list[TroubleshootingPattern] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                patterns.append(TroubleshootingPattern.model_validate_json(line))
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Skipping malformed troubleshooting pattern: %s", line[:80]
                )
        return patterns

    def _write_all(self, patterns: list[TroubleshootingPattern]) -> None:
        try:
            self._memory_dir.mkdir(parents=True, exist_ok=True)
            with self._path.open("w") as f:
                for p in patterns:
                    f.write(p.model_dump_json() + "\n")
        except OSError:
            logger.warning(
                "Could not write troubleshooting patterns to %s",
                self._path,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Prompt helper
# ---------------------------------------------------------------------------


def format_patterns_for_prompt(
    patterns: list[TroubleshootingPattern], max_chars: int = 3000
) -> str:
    """Render patterns as a markdown section for agent prompt injection.

    Returns an empty string when *patterns* is empty.
    """
    if not patterns:
        return ""

    lines = ["## Learned Patterns from Previous Fixes", ""]
    total = 0

    for included, p in enumerate(patterns):
        entry = (
            f"**{p.pattern_name}** ({p.language}, seen {p.frequency}x)\n"
            f"- Cause: {p.description}\n"
            f"- Fix: {p.fix_strategy}\n"
        )
        if total + len(entry) > max_chars:
            lines.append(
                f"\n_(truncated — {len(patterns) - included} more patterns omitted)_"
            )
            break
        lines.append(entry)
        total += len(entry)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Transcript extractor
# ---------------------------------------------------------------------------


def extract_troubleshooting_pattern(
    transcript: str, issue_number: int, language: str
) -> TroubleshootingPattern | None:
    """Extract a structured troubleshooting pattern from an agent transcript.

    Looks for a ``TROUBLESHOOTING_PATTERN_START`` / ``TROUBLESHOOTING_PATTERN_END``
    block and parses ``pattern_name:``, ``description:``, and ``fix_strategy:``
    fields from it.

    Returns ``None`` if no valid block is found or required fields are missing.
    """
    regex = rf"{_PATTERN_START}\s*\n(.*?)\n{_PATTERN_END}"
    match = re.search(regex, transcript, re.DOTALL)
    if not match:
        return None

    block = match.group(1)
    fields: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        for key in ("pattern_name", "description", "fix_strategy"):
            prefix = f"{key}:"
            if stripped.lower().startswith(prefix):
                fields[key] = stripped[len(prefix) :].strip()

    required = ("pattern_name", "description", "fix_strategy")
    if not all(fields.get(k) for k in required):
        return None

    return TroubleshootingPattern(
        language=language,
        pattern_name=fields["pattern_name"],
        description=fields["description"],
        fix_strategy=fields["fix_strategy"],
        source_issues=[issue_number],
    )
