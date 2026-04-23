"""Staleness evaluator for wiki entries.

Pure functions — no I/O, no LLM calls. Resolves valid_to expressions
and classifies entries as current / expired / superseded.

valid_to grammar (V1 — intentionally minimal, no DSL):
  - ISO8601 date (2026-12-31) or datetime (2026-12-31T00:00:00+00:00)
  - Relative duration: Nd (days), Nmo (months≈30d), Ny (years≈365d)
  - None — indefinite
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from repo_wiki import WikiEntry


class ParseError(ValueError):
    """Raised when valid_to cannot be parsed."""


_DURATION_RE = re.compile(r"^(\d+)(d|mo|y)$")


def parse_valid_to(raw: str | None, *, now: datetime) -> str | None:
    """Resolve a valid_to expression to an absolute ISO8601 string.

    Returns None if raw is None or empty (indefinite).
    Raises ParseError if raw cannot be parsed.
    """
    if raw is None or raw == "":
        return None

    match = _DURATION_RE.match(raw)
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        if n <= 0:
            raise ParseError(f"valid_to duration must be positive: {raw!r}")
        days = {"d": n, "mo": n * 30, "y": n * 365}[unit]
        return (now + timedelta(days=days)).isoformat()

    # Try parsing as ISO8601
    try:
        candidate = raw
        # Accept plain date (2026-12-31) by appending midnight UTC
        if "T" not in candidate and len(candidate) == 10:
            candidate = f"{candidate}T00:00:00+00:00"
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.isoformat()
    except ValueError as exc:
        raise ParseError(f"valid_to must be ISO8601 or duration: {raw!r}") from exc


Status = Literal["current", "pending", "expired", "superseded"]


def evaluate(entry: WikiEntry, *, now: datetime) -> Status:
    """Classify an entry's validity at ``now``.

    Precedence (highest first):
      1. superseded_by set → "superseded"
      2. now < valid_from → "pending"
      3. valid_to set and now >= valid_to → "expired"
      4. otherwise → "current"

    ``pending`` and ``expired`` entries are excluded from prompt injection
    but kept on disk for audit. ``superseded`` entries are likewise excluded
    but may be browsed in the wiki UI with a badge.
    """
    if entry.superseded_by:
        return "superseded"

    if entry.valid_from:
        valid_from = _parse_iso(entry.valid_from)
        if valid_from is not None and now < valid_from:
            return "pending"

    if entry.valid_to:
        valid_to = _parse_iso(entry.valid_to)
        if valid_to is not None and now >= valid_to:
            return "expired"

    return "current"


def _parse_iso(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
