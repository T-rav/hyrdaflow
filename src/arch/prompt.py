from __future__ import annotations

from typing import Literal

from arch.models import AdrSummary

Framing = Literal["planner", "reviewer"]

PLANNER_HEADER = "## Accepted architecture decisions (respect these when planning)"
PLANNER_FOOTER = (
    "Follow these decisions. If a task requires overriding one, flag it in the "
    "plan and recommend a new ADR rather than contradicting the existing one."
)

REVIEWER_HEADER = "## Accepted architecture decisions (flag violations)"
REVIEWER_FOOTER = (
    "Flag any PR that violates or silently contradicts one of these decisions."
)


def _estimate_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def render_adr_section(
    adrs: list[AdrSummary],
    *,
    framing: Framing = "planner",
    token_budget: int = 2000,
) -> str:
    if not adrs:
        return ""

    header = PLANNER_HEADER if framing == "planner" else REVIEWER_HEADER
    footer = PLANNER_FOOTER if framing == "planner" else REVIEWER_FOOTER

    full_lines = [f"- {a.slug}: {a.title}: {a.one_line}" for a in adrs]
    full = "\n".join([header, "", *full_lines, "", footer])
    if _estimate_tokens(full) <= token_budget:
        return full

    terse_lines = [f"- {a.slug}: {a.title}" for a in adrs]
    return "\n".join([header, "", *terse_lines, "", footer])
