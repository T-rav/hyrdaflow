"""PreflightDecision — pure label-state mapping for AutoAgentPreflightLoop.

Spec §2.2, §2.3, §7. Translates a PreflightResult into label operations
applied via PRPort. Label operations are idempotent (GitHub dedup); comment
deduplication is the caller's responsibility — re-running apply_decision
on the same input WILL post a duplicate comment.
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
    prompt_hash: str = ""  # populated from PreflightSpawn for audit traceability


class _PRPort(Protocol):
    """Subset of PRPort used by apply_decision.

    Method names match the real PRManager / FakeGitHub surface:
    `add_labels` (plural), `remove_label` (singular — call once per label),
    `post_comment` (not `add_comment`). See `src/ports.py` lines 175-198.
    """

    async def add_labels(self, issue_number: int, labels: list[str]) -> None: ...
    async def remove_label(self, issue_number: int, label: str) -> None: ...
    async def post_comment(self, issue_number: int, body: str) -> None: ...


# Status → (labels-to-add, labels-to-remove)
#
# Note: `resolved` removes `human-required` as well as `hitl-escalation` so a
# previously-failed-then-re-submitted issue (operator manually reset state)
# doesn't stay in the human queue after a successful auto-fix.
_LABEL_MAP: dict[str, tuple[list[str], list[str]]] = {
    "resolved": ([], ["hitl-escalation", "human-required"]),
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
    for label in remove:
        await pr_port.remove_label(issue_number, label)

    comment = _format_comment(
        sub_label, result, current_attempts, exhausted, max_attempts
    )
    if comment:
        await pr_port.post_comment(issue_number, comment)

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
    max_attempts: int,
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
        f" — **{max_attempts} attempts exhausted, no further auto-agent retries**"
        if exhausted
        else ""
    )
    return (
        f"**Auto-Agent attempt {attempts} → `{result.status}`** "
        f"(sub-label `{sub_label}`, ${result.cost_usd:.2f}, "
        f"{result.wall_clock_s:.0f}s){suffix}.\n\n"
        f"**Diagnosis:**\n{result.diagnosis}"
    )
