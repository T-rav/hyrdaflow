"""Pure citation-intersection logic for `AdrTouchpointAuditorLoop` (ADR-0056).

Given an ADR index and a PR's file diff, returns a list of `DriftFinding`s
— one per Accepted/Proposed ADR whose cited `src/` modules changed without
the ADR's own markdown file being part of the same diff.

Kept pure (no I/O, no `gh` calls) so the loop can drive it from real
state and tests can drive it from stubbed inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from adr_index import ADR, ADRIndex


@dataclass(frozen=True)
class DriftFinding:
    """One PR×ADR pair where cited modules changed without the ADR being updated."""

    adr: ADR
    pr_number: int
    changed_cited_files: tuple[str, ...]


def _adr_file_in_diff(adr: ADR, changed_files: Iterable[str]) -> bool:
    """True iff the ADR's own markdown file appears in the diff.

    ADR file paths follow `docs/adr/<NNNN>-<slug>.md` — we match on the
    zero-padded number prefix to tolerate slug renames.
    """
    prefix = f"docs/adr/{adr.number:04d}-"
    return any(f.startswith(prefix) for f in changed_files)


def compute_drift(
    adr_index: ADRIndex,
    pr_number: int,
    changed_files: Iterable[str],
) -> list[DriftFinding]:
    """Return drift findings for one PR's file diff.

    Findings are sorted by ADR number for deterministic output.
    """
    files = list(changed_files)
    src_files = [f for f in files if f.startswith("src/")]
    if not src_files:
        return []
    by_path = adr_index.adrs_touching(src_files)

    adr_hits: dict[int, tuple[ADR, list[str]]] = {}
    for path, adrs in by_path.items():
        for adr in adrs:
            slot = adr_hits.setdefault(adr.number, (adr, []))
            slot[1].append(path)

    findings: list[DriftFinding] = []
    for number in sorted(adr_hits):
        adr, paths = adr_hits[number]
        if _adr_file_in_diff(adr, files):
            continue
        findings.append(
            DriftFinding(
                adr=adr,
                pr_number=pr_number,
                changed_cited_files=tuple(sorted(paths)),
            )
        )
    return findings
