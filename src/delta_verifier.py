"""Delta verification — compare planned file changes against actual git diff."""

from __future__ import annotations

import logging
import re

from models import DeltaReport

logger = logging.getLogger("hydra.delta_verifier")


def parse_file_delta(plan_text: str) -> list[str]:
    """Extract file paths from the ``## File Delta`` section of a plan.

    Recognises lines starting with ``MODIFIED:``, ``ADDED:``, or ``REMOVED:``.
    Returns a sorted, deduplicated list of file paths.
    """
    section_match = re.search(
        r"## File Delta\s*\n(.*?)(?=\n## |\Z)",
        plan_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return []

    body = section_match.group(1)
    paths: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        match = re.match(
            r"(?:MODIFIED|ADDED|REMOVED)\s*:\s*(.+)", stripped, re.IGNORECASE
        )
        if match:
            path = match.group(1).strip().strip("`")
            if path:
                paths.add(path)
    return sorted(paths)


def verify_delta(planned_files: list[str], actual_files: list[str]) -> DeltaReport:
    """Compare planned file paths against actual changed files.

    *planned_files* comes from :func:`parse_file_delta`.
    *actual_files* comes from ``git diff --name-only`` against the base branch.

    Returns a :class:`DeltaReport` with planned, actual, missing, and unexpected.
    """
    planned_set = set(planned_files)
    actual_set = set(actual_files)

    missing = sorted(planned_set - actual_set)
    unexpected = sorted(actual_set - planned_set)

    report = DeltaReport(
        planned=sorted(planned_set),
        actual=sorted(actual_set),
        missing=missing,
        unexpected=unexpected,
    )

    if report.has_drift:
        logger.warning(
            "Delta drift detected: %d missing, %d unexpected",
            len(missing),
            len(unexpected),
        )
    else:
        logger.info(
            "Delta verification passed: %d planned == %d actual",
            len(planned_set),
            len(actual_set),
        )

    return report
