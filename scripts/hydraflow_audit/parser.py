"""Parse ADR-0044 check tables into `CheckSpec` rows.

The ADR is the source of truth. The parser walks its markdown, finds each
principle heading (`### P<n>. ...`), and extracts the five-column check
table that follows. A table row without the expected columns is skipped
silently — tables are authored by humans and drift has to fail open at the
parse layer (the audit later reports missing check_ids as FAIL, which is
the right place for that error).
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import CheckSpec, Severity

_PRINCIPLE_HEADING = re.compile(r"^###\s+(P\d+)\.\s+")
_TABLE_HEADER = re.compile(
    r"^\|\s*check_id\s*\|\s*type\s*\|\s*source\s*\|\s*what\s*\|\s*remediation\s*\|",
    re.IGNORECASE,
)


def parse_adr(path: Path) -> list[CheckSpec]:
    """Return all check specs in document order."""
    text = path.read_text(encoding="utf-8")
    return _parse_text(text)


def _parse_text(text: str) -> list[CheckSpec]:
    specs: list[CheckSpec] = []
    current_principle: str | None = None
    in_table = False

    for line in text.splitlines():
        heading = _PRINCIPLE_HEADING.match(line)
        if heading:
            current_principle = heading.group(1)
            in_table = False
            continue

        if _TABLE_HEADER.match(line):
            in_table = True
            continue

        if in_table:
            if not line.strip().startswith("|"):
                in_table = False
                continue
            if _is_alignment_row(line):
                continue
            spec = _parse_row(line, current_principle)
            if spec is not None:
                specs.append(spec)

    return specs


def _is_alignment_row(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(set(c.strip()) <= {"-", ":"} for c in cells)


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    inner = stripped.strip("|")
    return [c.strip() for c in inner.split("|")]


def _parse_row(line: str, principle: str | None) -> CheckSpec | None:
    if principle is None:
        return None
    cells = _cells(line)
    if len(cells) != 5:
        return None
    check_id, severity_raw, source, what, remediation = cells
    if not check_id or not severity_raw:
        return None
    try:
        severity = Severity(severity_raw.upper())
    except ValueError:
        return None
    return CheckSpec(
        check_id=check_id,
        severity=severity,
        source=source,
        what=what,
        remediation=remediation,
        principle=principle,
    )
