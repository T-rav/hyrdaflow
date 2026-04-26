"""PreflightDecision — pure label-state mapping for AutoAgentPreflightLoop.

Spec §2.2, §2.3, §7. Translates a PreflightResult into label operations
applied via PRPort. Idempotent: re-runs on the same input are no-ops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger("hydraflow.preflight.decision")


@dataclass(frozen=True)
class PreflightResult:
    status: str  # "resolved" | "needs_human" | "fatal" | "pr_failed" | "cost_exceeded" | "timeout"
    pr_url: str | None
    diagnosis: str
    cost_usd: float
    wall_clock_s: float
    tokens: int


class _PRPort(Protocol):
    async def add_labels(self, issue: int, labels: list[str]) -> None: ...
    async def remove_labels(self, issue: int, labels: list[str]) -> None: ...
    async def add_comment(self, issue: int, body: str) -> None: ...


# Status → (labels-to-add, labels-to-remove)
_LABEL_MAP: dict[str, tuple[list[str], list[str]]] = {
    "resolved": ([], ["hitl-escalation"]),
    "needs_human": (["human-required"], []),
    "fatal": (["human-required", "auto-agent-fatal"], []),
    "pr_failed": (["human-required", "auto-agent-pr-failed"], []),
    "cost_exceeded": (["human-required", "cost-exceeded"], []),
    "timeout": (["human-required", "timeout"], []),
}


async def apply_decision(
    *,
    issue_number: int,
    sub_label: str,
    result: PreflightResult,
    pr_port: _PRPort,
    state: Any,
    max_attempts: int,
) -> dict[str, Any]:
    """Apply labels + comment for a single attempt's result."""
    # Race-detection: re-read attempts to ensure no concurrent bumper.
    current_attempts = state.get_auto_agent_attempts(issue_number)

    add, remove = _LABEL_MAP.get(result.status, _LABEL_MAP["needs_human"])

    # Exhaustion check — if this attempt brought us to the cap and it didn't resolve,
    # flag as exhausted on top of the normal needs_human/fatal label set.
    exhausted = result.status != "resolved" and current_attempts >= max_attempts
    if exhausted:
        add = list(add) + ["auto-agent-exhausted"]

    if add:
        await pr_port.add_labels(issue_number, add)
    if remove:
        await pr_port.remove_labels(issue_number, remove)

    comment = _format_comment(sub_label, result, current_attempts, exhausted)
    if comment:
        await pr_port.add_comment(issue_number, comment)

    return {
        "issue": issue_number,
        "status": result.status,
        "exhausted": exhausted,
        "added": add,
        "removed": remove,
    }


def _format_comment(
    sub_label: str,
    result: PreflightResult,
    attempts: int,
    exhausted: bool,
) -> str:
    if result.status == "resolved":
        pr_link = f" PR: {result.pr_url}" if result.pr_url else ""
        return (
            f"**Auto-Agent resolved this issue** (attempt {attempts}, "
            f"sub-label `{sub_label}`, ${result.cost_usd:.2f}, "
            f"{result.wall_clock_s:.0f}s).{pr_link}\n\n"
            f"{result.diagnosis}"
        )
    suffix = (
        " — **3 attempts exhausted, no further auto-agent retries**"
        if exhausted
        else ""
    )
    return (
        f"**Auto-Agent attempt {attempts} → `{result.status}`** "
        f"(sub-label `{sub_label}`, ${result.cost_usd:.2f}, "
        f"{result.wall_clock_s:.0f}s){suffix}.\n\n"
        f"**Diagnosis:**\n{result.diagnosis}"
    )
