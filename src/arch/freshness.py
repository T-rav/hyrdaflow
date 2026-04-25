"""Compute the freshness badge state for a generated artifact.

Pure read-side helper consumed by future site renderers (Plan C wires the
emoji+tooltip into the runner footer). The runner itself always writes
FRESH on emit; this function describes the badge state of a previously
emitted artifact relative to the current source SHA.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum


class FreshnessBadge(StrEnum):
    FRESH = "fresh"
    SOURCE_MOVED = "source-moved"
    STALE = "stale"
    NOT_GENERATED = "not-generated"


def compute_badge(
    artifact_name: str,
    *,
    meta: dict | None,
    current_source_sha: str,
    now: datetime | None = None,
) -> FreshnessBadge:
    """Return the badge for `artifact_name` given the previous-emit `meta`.

    Bootstrap: if `meta is None`, or the artifact entry is absent, returns
    NOT_GENERATED so the page footer can show 'not yet generated'.
    """
    if meta is None:
        return FreshnessBadge.NOT_GENERATED
    artifacts = meta.get("artifacts", {})
    entry = artifacts.get(artifact_name)
    if entry is None:
        return FreshnessBadge.NOT_GENERATED

    regen_iso = meta.get("regenerated_at")
    if not regen_iso:
        return FreshnessBadge.NOT_GENERATED
    regen_at = datetime.fromisoformat(regen_iso)
    if regen_at.tzinfo is None:
        regen_at = regen_at.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    age = now - regen_at

    if age > timedelta(days=7):
        return FreshnessBadge.STALE
    if entry.get("source_sha") != current_source_sha:
        return FreshnessBadge.SOURCE_MOVED
    return FreshnessBadge.FRESH
