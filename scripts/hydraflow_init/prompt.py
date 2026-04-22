"""Template the remediation prompt.

Output is plain markdown (no ANSI, no shell-specific escapes) so it can be
piped to a file or pasted into a Claude session.
"""

from __future__ import annotations

from collections import Counter

from .modes import Mode

_BAD_STATUSES = {"FAIL", "WARN", "NOT_IMPLEMENTED"}


def render(
    *,
    target: str,
    findings: list[dict],
    summary: dict,
    mode: Mode,
    principle_filter: str | None,
    skip_brainstorm: bool,
) -> str:
    actionable = [f for f in findings if f.get("status") in _BAD_STATUSES]
    if principle_filter:
        actionable = [f for f in actionable if f.get("principle") == principle_filter]

    lines: list[str] = []
    lines.extend(_header(target, summary, mode, principle_filter))
    lines.extend(_instructions(mode, skip_brainstorm))
    lines.extend(_remediations(actionable))
    lines.extend(_closing())
    return "\n".join(lines) + "\n"


def _header(
    target: str, summary: dict, mode: Mode, principle_filter: str | None
) -> list[str]:
    scope = f" (principle {principle_filter})" if principle_filter else ""
    return [
        f"# HydraFlow adoption plan — {target}{scope}",
        "",
        "Paste this into a Claude Code session.",
        "",
        "## Current state (ADR-0044)",
        "",
        f"- Target: `{target}`",
        f"- Mode: **{mode.value}**",
        f"- PASS: {summary.get('pass', 0)}",
        f"- WARN: {summary.get('warn', 0)}",
        f"- FAIL: {summary.get('fail', 0)}",
        f"- NOT_IMPLEMENTED: {summary.get('not_implemented', 0)}",
        f"- Total checks: {summary.get('total', 0)}",
        "",
        "> Every remediation cites the ADR or `docs/agents/` source. Read the",
        "> citation before editing — the paraphrase below is a pointer, not the spec.",
        "",
    ]


def _instructions(mode: Mode, skip_brainstorm: bool) -> list[str]:
    lines = ["## Workflow", ""]
    if mode is Mode.GREENFIELD and not skip_brainstorm:
        lines += [
            "1. Invoke `superpowers:brainstorming` to confirm the project shape",
            "   before writing any plan. What does this project need from the",
            "   HydraFlow principles? Which are load-bearing, which are N/A?",
            "2. Invoke `superpowers:writing-plans` to decompose the remediations",
            "   below into ordered, testable tasks.",
            "3. For each implementation step, follow `superpowers:test-driven-development`",
            "   (red → green → refactor) before committing.",
            "4. Before declaring the plan complete, invoke",
            "   `superpowers:verification-before-completion` — the exit bar is",
            "   `make audit` returning 0.",
        ]
    else:
        lines += [
            "1. Invoke `superpowers:writing-plans` and decompose only the failing",
            "   principles below — do not revisit passing ones.",
            "2. For each fix, write the failing test first",
            "   (`superpowers:test-driven-development`) so the remediation has an",
            "   objective success criterion.",
            "3. After implementation, invoke",
            "   `superpowers:verification-before-completion` and re-run",
            "   `make audit`. Target: the previously failing checks now PASS and",
            "   no previously passing checks regress.",
        ]
    lines.append("")
    return lines


def _remediations(actionable: list[dict]) -> list[str]:
    if not actionable:
        return ["## Remediations", "", "No actionable findings — audit is green.", ""]

    lines = ["## Remediations by principle", ""]
    by_principle: dict[str, list[dict]] = {}
    for f in actionable:
        by_principle.setdefault(f.get("principle", "?"), []).append(f)

    for principle in sorted(by_principle, key=_principle_sort_key):
        bucket = by_principle[principle]
        counts = Counter(f.get("status") for f in bucket)
        headline = ", ".join(
            f"{status} {count}" for status, count in counts.most_common()
        )
        lines.append(f"### {principle} — {headline}")
        lines.append("")
        for finding in bucket:
            lines.extend(_format_finding(finding))
        lines.append("")
    return lines


def _format_finding(f: dict) -> list[str]:
    check_id = f.get("check_id", "?")
    status = f.get("status", "?")
    what = f.get("what", "")
    message = f.get("message", "")
    source = f.get("source", "")
    remediation = f.get("remediation", "")
    severity = f.get("severity", "")

    lines = [
        f"- **{check_id} ({status}, {severity})** — {what}",
    ]
    if message:
        lines.append(f"  - Detail: {message}")
    lines.append(f"  - Source: {source}")
    lines.append(f"  - Fix: {remediation}")
    return lines


def _closing() -> list[str]:
    return [
        "## Exit criterion",
        "",
        "Run `make audit` in the target directory. The command must exit 0",
        "and the previously failing/warn/not-implemented checks must all be",
        "PASS (or NA, when a principle is legitimately not applicable to this",
        "project shape). A remaining CULTURAL WARN on branch protection or",
        "direct-push heuristics is acceptable; document the confirmation.",
        "",
    ]


def _principle_sort_key(principle: str) -> tuple[int, str]:
    try:
        return (int(principle.lstrip("P")), principle)
    except ValueError:
        return (9999, principle)
