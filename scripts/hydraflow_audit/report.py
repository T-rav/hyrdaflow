"""Write the audit report as JSON and print a terminal summary."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .models import Finding, Status

_STATUS_GLYPH = {
    Status.PASS: "✓",
    Status.WARN: "!",
    Status.FAIL: "✗",
    Status.NA: "-",
    Status.NOT_IMPLEMENTED: "?",
}


def write_json(findings: list[Finding], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "summary": _summarise(findings),
        "findings": [f.to_dict() for f in findings],
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def format_terminal(findings: list[Finding]) -> str:
    lines: list[str] = ["HydraFlow Conformance Audit (ADR-0044)", "=" * 40, ""]
    by_principle: dict[str, list[Finding]] = {}
    for f in findings:
        by_principle.setdefault(f.principle, []).append(f)

    for principle in sorted(by_principle, key=_principle_sort_key):
        bucket = by_principle[principle]
        counts = Counter(f.status for f in bucket)
        headline = (
            f"{principle}  "
            f"PASS {counts[Status.PASS]} / "
            f"WARN {counts[Status.WARN]} / "
            f"FAIL {counts[Status.FAIL]} / "
            f"NA {counts[Status.NA]} / "
            f"?? {counts[Status.NOT_IMPLEMENTED]}"
        )
        lines.append(headline)
        for f in bucket:
            if f.status is Status.PASS:
                continue
            glyph = _STATUS_GLYPH[f.status]
            lines.append(f"  {glyph} {f.check_id}  {f.what}")
            if f.message:
                lines.append(f"      {f.message}")
            lines.append(f"      source: {f.source}  —  fix: {f.remediation}")
        lines.append("")

    summary = _summarise(findings)
    lines.append(
        f"Total: PASS {summary['pass']}  WARN {summary['warn']}  FAIL {summary['fail']}  "
        f"NA {summary['na']}  NOT_IMPLEMENTED {summary['not_implemented']}"
    )
    return "\n".join(lines)


def _summarise(findings: list[Finding]) -> dict[str, int]:
    counts = Counter(f.status for f in findings)
    return {
        "pass": counts[Status.PASS],
        "warn": counts[Status.WARN],
        "fail": counts[Status.FAIL],
        "na": counts[Status.NA],
        "not_implemented": counts[Status.NOT_IMPLEMENTED],
        "total": len(findings),
    }


def _principle_sort_key(principle: str) -> tuple[int, str]:
    try:
        return (int(principle.lstrip("P")), principle)
    except ValueError:
        return (9999, principle)
