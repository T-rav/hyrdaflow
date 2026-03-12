"""Troubleshooting pattern store — persists learned CI timeout fix patterns.

Successful CI timeout fixes can emit a structured block in their transcript.
This module extracts those patterns, persists them to Hindsight, and
formats them for injection into future fix prompts — creating a feedback loop
that makes the unsticker smarter with each resolved hang.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from models import IsoTimestamp

if TYPE_CHECKING:
    from hindsight import HindsightClient

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
    """Hindsight-backed store for learned troubleshooting patterns."""

    def __init__(self, hindsight: HindsightClient) -> None:
        self._hindsight = hindsight

    async def record_pattern(self, pattern: TroubleshootingPattern) -> None:
        """Record a troubleshooting pattern to Hindsight."""
        from hindsight import BANK_TROUBLESHOOTING, retain_safe

        content = (
            f"{pattern.pattern_name}: {pattern.description}\n"
            f"Fix: {pattern.fix_strategy}"
        )
        await retain_safe(
            self._hindsight,
            BANK_TROUBLESHOOTING,
            content,
            context=f"CI troubleshooting pattern ({pattern.language})",
            metadata={
                "source": "troubleshooting",
                "language": pattern.language,
                "pattern_name": pattern.pattern_name,
            },
        )

    async def load_patterns(
        self, *, language: str | None = None, limit: int | None = 10
    ) -> list[TroubleshootingPattern]:
        """Load patterns from Hindsight, optionally filtered by *language*.

        Returns up to *limit* patterns sorted by frequency descending.
        Pass ``limit=None`` to return all patterns without a cap.
        """
        from hindsight import BANK_TROUBLESHOOTING, recall_safe

        query = (
            f"troubleshooting patterns for {language}"
            if language
            else "troubleshooting patterns"
        )
        recall_limit = limit or 50
        memories = await recall_safe(
            self._hindsight, BANK_TROUBLESHOOTING, query, limit=recall_limit
        )
        patterns: list[TroubleshootingPattern] = []
        for m in memories:
            try:
                patterns.append(TroubleshootingPattern.model_validate_json(m.content))
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Skipping malformed troubleshooting pattern from Hindsight"
                )
        if language:
            lang_lower = language.lower()
            patterns = [
                p
                for p in patterns
                if p.language.lower() == lang_lower or p.language.lower() == "general"
            ]
        patterns.sort(key=lambda p: p.frequency, reverse=True)
        return patterns if limit is None else patterns[:limit]


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
