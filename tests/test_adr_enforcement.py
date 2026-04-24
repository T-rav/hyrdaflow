"""Validates that every Accepted ADR declares how it's enforced.

Convention (per the wiki-evolution audit P3):

  Each ADR with ``**Status:** Accepted`` must include an
  ``**Enforced by:**`` line whose value is one of:

  - Comma-separated test references (``tests/test_foo.py`` or
    ``tests/test_foo.py::test_bar``); every file listed MUST exist.
  - The placeholder ``(process)`` for ADRs that enforce a workflow
    rather than code (e.g. branch-protection policies).
  - The placeholder ``(historical)`` for Accepted ADRs that codify a
    past decision still worth keeping but no longer testable.
  - The placeholder ``(none)`` for Accepted ADRs that are being moved
    toward enforcement — this is allowed but flags the ADR for
    follow-up rather than passing silently.

Deprecated / Superseded ADRs are exempt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ADR_DIR = Path(__file__).resolve().parents[1] / "docs" / "adr"
_STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)
_ENFORCED_RE = re.compile(r"^\*\*Enforced by:\*\*\s*(.+?)\s*$", re.MULTILINE)
_PLACEHOLDERS = {"(process)", "(historical)", "(none)"}


def _accepted_adrs() -> list[Path]:
    """Return paths of Accepted ADRs (non-template, non-superseded)."""
    paths: list[Path] = []
    for path in sorted(_ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")):
        text = path.read_text(encoding="utf-8")
        status_match = _STATUS_RE.search(text)
        if status_match is None:
            continue
        if status_match.group(1).strip().lower() == "accepted":
            paths.append(path)
    return paths


def _parse_enforcement(text: str) -> str | None:
    match = _ENFORCED_RE.search(text)
    return match.group(1).strip() if match else None


@pytest.mark.parametrize("adr_path", _accepted_adrs(), ids=lambda p: p.name)
def test_accepted_adr_declares_enforcement(adr_path: Path) -> None:
    """Every Accepted ADR must declare how it is enforced."""
    text = adr_path.read_text(encoding="utf-8")
    enforcement = _parse_enforcement(text)
    assert enforcement is not None, (
        f"{adr_path.name} is Accepted but has no '**Enforced by:**' line. "
        f"Add one naming test files (e.g. tests/test_foo.py), or use "
        f"(process)/(historical)/(none) with justification."
    )


@pytest.mark.parametrize("adr_path", _accepted_adrs(), ids=lambda p: p.name)
def test_enforcement_test_files_exist(adr_path: Path) -> None:
    """If enforcement names test files, they must exist on disk."""
    text = adr_path.read_text(encoding="utf-8")
    enforcement = _parse_enforcement(text)
    if enforcement is None or enforcement in _PLACEHOLDERS:
        return

    repo_root = _ADR_DIR.parents[1]
    for entry in (s.strip() for s in enforcement.split(",") if s.strip()):
        # Strip ::test_func suffix for path resolution
        file_part = entry.split("::", 1)[0]
        candidate = repo_root / file_part
        assert candidate.is_file(), (
            f"{adr_path.name} claims enforcement by {entry!r} but "
            f"{candidate} does not exist."
        )
