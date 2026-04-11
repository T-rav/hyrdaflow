"""Shared types for the Hindsight subsystem.

Extracted from ``hindsight.py`` and ``hindsight_wal.py`` to break the
circular import between those two modules.  Both modules re-export
these symbols for backward compatibility.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

__all__ = ["Bank", "HindsightMemory", "WALEntry"]

# ---------------------------------------------------------------------------
# Bank IDs
# ---------------------------------------------------------------------------


class Bank(StrEnum):
    """Hindsight memory bank identifiers."""

    TRIBAL = "hydraflow-tribal"
    RETROSPECTIVES = "hydraflow-retrospectives"
    REVIEW_INSIGHTS = "hydraflow-review-insights"
    HARNESS_INSIGHTS = "hydraflow-harness-insights"
    TROUBLESHOOTING = "hydraflow-troubleshooting"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class HindsightMemory(BaseModel):
    """A single memory item returned by Hindsight recall."""

    content: str = ""
    text: str = ""
    context: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = 0.0
    timestamp: str = ""

    @property
    def display_text(self) -> str:
        """Return the best available text (``text`` from API, or ``content``)."""
        return self.text or self.content


class WALEntry(BaseModel):
    """A single pending retain operation."""

    bank: str  # Bank enum value; kept as str for WAL transport flexibility
    content: str
    context: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    retries: int = 0
