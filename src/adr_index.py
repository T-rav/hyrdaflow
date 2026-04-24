"""ADR runtime indexer.

Parses docs/adr/*.md at runtime, renders compact summaries for prompt
injection. Load-bearing facts — we want agents to know what's been
decided before they plan.

File format (from docs/adr/0001-five-concurrent-async-loops.md):

    # ADR-0001: Five Concurrent Async Loops

    **Status:** Accepted
    **Date:** 2026-02-26

    ## Context

    HydraFlow must process GitHub issues through five distinct stages...

Status is normalized to one of: "Accepted", "Proposed", "Superseded",
"Deprecated". "Superseded by ADR-NNNN" populates ``superseded_by``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TITLE_RE = re.compile(r"^#\s*ADR-(\d{4}):\s*(.+?)\s*$", re.MULTILINE)
_STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)
_CONTEXT_RE = re.compile(r"##\s+Context\s*\n\s*\n(.+?)(?=\n\s*\n|\n##\s|\Z)", re.DOTALL)
_SUPERSEDED_RE = re.compile(r"Superseded\s+by\s+(ADR-\d{4})", re.IGNORECASE)
# Matches `src/some/path.py` or `src/some/path.py:Symbol` citations.
# Shared with adr_pre_validator._SOURCE_SYMBOL_RE. Used for
# ADR↔source-file inverse indexing so the CI gate can flag PRs
# touching files cited in Accepted ADRs. The ``:Symbol`` tail is
# optional so umbrella ADRs that cite files in prose (without a
# specific symbol) also satisfy the gate.
_SOURCE_FILE_CITATION_RE = re.compile(r"`(src/[^`:\s]+\.py)(?::[A-Za-z_]\w*)?`")


@dataclass(frozen=True)
class ADR:
    number: int
    title: str
    status: str  # normalized: Accepted | Proposed | Superseded | Deprecated | Unknown
    summary: str  # first paragraph of ## Context, flattened
    superseded_by: str | None = None
    source_files: frozenset[str] = frozenset()
    """Set of `src/...` paths cited anywhere in the ADR body — used by
    the P2 CI gate to flag PRs touching files under Accepted ADRs."""


def parse_adr_file(path: Path) -> ADR:
    """Parse a single ADR markdown file. Never raises on malformed input."""
    text = path.read_text()

    title_match = _TITLE_RE.search(text)
    if title_match is None:
        # Fallback: use filename stem
        number = _extract_number_from_filename(path)
        title = path.stem
    else:
        number = int(title_match.group(1))
        title = title_match.group(2)

    status_raw = ""
    status_match = _STATUS_RE.search(text)
    if status_match:
        status_raw = status_match.group(1).strip()

    superseded_by = None
    sup_match = _SUPERSEDED_RE.search(status_raw)
    if sup_match:
        superseded_by = sup_match.group(1)
        status_norm = "Superseded"
    else:
        status_norm = _normalize_status(status_raw)

    summary = ""
    ctx_match = _CONTEXT_RE.search(text)
    if ctx_match:
        summary = " ".join(ctx_match.group(1).split())[:300]

    source_files = frozenset(_SOURCE_FILE_CITATION_RE.findall(text))

    return ADR(
        number=number,
        title=title,
        status=status_norm,
        summary=summary,
        superseded_by=superseded_by,
        source_files=source_files,
    )


def scan_adr_directory(adr_dir: Path) -> list[ADR]:
    """Parse every ADR file in the directory, sorted by number."""
    if not adr_dir.exists() or not adr_dir.is_dir():
        return []
    adrs: list[ADR] = []
    for p in adr_dir.iterdir():
        if p.is_file() and p.suffix == ".md" and _TITLE_RE.search(p.read_text()):
            adrs.append(parse_adr_file(p))
    return sorted(adrs, key=lambda a: a.number)


def _normalize_status(raw: str) -> str:
    low = raw.lower()
    if "accepted" in low:
        return "Accepted"
    if "proposed" in low or "draft" in low:
        return "Proposed"
    if "superseded" in low:
        return "Superseded"
    if "deprecated" in low:
        return "Deprecated"
    return "Unknown"


def _extract_number_from_filename(path: Path) -> int:
    m = re.match(r"(\d{4})-", path.name)
    return int(m.group(1)) if m else 0


def render_full(adrs: list[ADR]) -> str:
    """Render the full ADR index for injection into plan-phase prompts."""
    if not adrs:
        return ""

    accepted = [a for a in adrs if a.status == "Accepted"]
    proposed = [a for a in adrs if a.status == "Proposed"]
    superseded = [a for a in adrs if a.status == "Superseded"]

    parts: list[str] = ["# Architecture Decisions (ADRs)"]

    if accepted:
        parts.append("\n## Accepted (load-bearing)")
        for a in accepted:
            parts.append(f"- ADR-{a.number:04d} {a.title} — {a.summary}")

    if proposed:
        parts.append("\n## Proposed (drafted, not yet accepted)")
        for a in proposed:
            parts.append(f"- ADR-{a.number:04d} {a.title} — {a.summary}")

    if superseded:
        parts.append("\n## Superseded")
        for a in superseded:
            ref = f" (superseded by {a.superseded_by})" if a.superseded_by else ""
            parts.append(f"- ADR-{a.number:04d} {a.title}{ref}")

    return "\n".join(parts)


def render_titles_only(adrs: list[ADR]) -> str:
    """Titles-only view for implement/review prompts (prompt-size conscious).

    Excludes Superseded entries to reduce noise. Agents working in
    implement/review shouldn't be reminded of rules that have been replaced.
    """
    accepted = [a for a in adrs if a.status == "Accepted"]
    proposed = [a for a in adrs if a.status == "Proposed"]
    visible = accepted + proposed
    if not visible:
        return ""
    lines = ["# Architecture Decisions (titles only)"]
    for a in visible:
        lines.append(f"- ADR-{a.number:04d} {a.title}")
    return "\n".join(lines)


class ADRIndex:
    """Mtime-based cache over the ADR directory.

    Scans lazily on first ``adrs()`` call. Re-scans only when the directory
    or any ADR file's mtime has changed. Cheap for hot callers.
    """

    def __init__(self, adr_dir: Path) -> None:
        self._adr_dir = adr_dir
        self._cached: list[ADR] | None = None
        self._fingerprint: tuple[float, ...] = ()

    def adrs(self) -> list[ADR]:
        fingerprint = self._compute_fingerprint()
        if self._cached is None or fingerprint != self._fingerprint:
            self._cached = scan_adr_directory(self._adr_dir)
            self._fingerprint = fingerprint
        return self._cached

    def adrs_touching(self, paths: list[str] | tuple[str, ...]) -> dict[str, list[ADR]]:
        """Return a mapping of input paths → ADRs that cite each.

        Includes Accepted and Proposed ADRs — Superseded / Deprecated
        don't trigger the P2 gate. Proposed ADRs count because a PR
        that adds a Proposed ADR citing the touched file IS the author's
        statement of responsibility for the change; the ADR's status
        will be bumped to Accepted when the PR merges and the decision
        takes effect.

        Paths with no hits are omitted from the result.
        """
        if not paths:
            return {}
        live = [a for a in self.adrs() if a.status in ("Accepted", "Proposed")]
        result: dict[str, list[ADR]] = {}
        for path in paths:
            hits = [a for a in live if path in a.source_files]
            if hits:
                result[path] = hits
        return result

    def _compute_fingerprint(self) -> tuple[float, ...]:
        if not self._adr_dir.exists():
            return ()
        mtimes: list[float] = [self._adr_dir.stat().st_mtime]
        for p in self._adr_dir.iterdir():
            if p.is_file() and p.suffix == ".md":
                mtimes.append(p.stat().st_mtime)
        return tuple(sorted(mtimes))
