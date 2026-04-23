"""Small helpers shared by check modules."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Finding, Severity, Status


def finding(check_id: str, status: Status, message: str = "") -> Finding:
    """Build a Finding; runner backfills severity/principle/source/what/remediation."""
    return Finding(
        check_id=check_id,
        status=status,
        severity=Severity.STRUCTURAL,  # placeholder; runner backfills from spec
        principle="",
        source="",
        what="",
        remediation="",
        message=message,
    )


def exists(root: Path, relpath: str, check_id: str) -> Finding:
    path = root / relpath
    if path.exists():
        return finding(check_id, Status.PASS)
    return finding(check_id, Status.FAIL, f"missing: {relpath}")


def file_contains(
    root: Path,
    relpath: str,
    needle: str | re.Pattern[str],
    check_id: str,
    absent_message: str | None = None,
) -> Finding:
    path = root / relpath
    if not path.exists():
        return finding(check_id, Status.FAIL, f"missing: {relpath}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if isinstance(needle, re.Pattern):
        matched = bool(needle.search(text))
    else:
        matched = needle in text
    if matched:
        return finding(check_id, Status.PASS)
    return finding(
        check_id,
        Status.FAIL,
        absent_message or f"{relpath} missing expected content",
    )
