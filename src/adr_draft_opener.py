"""Agent-drafted ADR issue opener.

Creates a GitHub issue labeled ``adr-draft`` with the drafted context,
decision, consequences, and evidence. A human reviewer decides whether
to promote it to an Accepted ADR.

Invoked by the runner coordinator after WikiCompiler.judge_adr_draft
returns ``draft_ok=True``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from knowledge_metrics import metrics as _metrics

if TYPE_CHECKING:
    from wiki_compiler import ADRDraftDecision

logger = logging.getLogger("hydraflow.adr_draft_opener")


async def open_adr_draft_issue(
    *,
    suggestion: dict,
    decision: ADRDraftDecision,
    gh_client,  # duck-typed: must have async create_issue(title=, body=, labels=)
) -> int | None:
    """Open the GitHub ADR-draft issue. Returns the issue number, or None."""
    if not decision.draft_ok:
        return None

    title = f"ADR draft: {suggestion.get('title', 'unnamed')}"
    evidence_lines = []
    for issue in suggestion.get("evidence_issues", []):
        evidence_lines.append(f"- Issue #{issue}")
    for wid in suggestion.get("evidence_wiki_entries", []):
        evidence_lines.append(f"- Tribal wiki entry `{wid}`")
    evidence_block = "\n".join(evidence_lines) if evidence_lines else "- (none)"

    body = (
        "Automated draft by the HydraFlow librarian.\n\n"
        "## Context\n"
        f"{suggestion.get('context', '')}\n\n"
        "## Decision\n"
        f"{suggestion.get('decision', '')}\n\n"
        "## Consequences\n"
        f"{suggestion.get('consequences', '')}\n\n"
        "## Evidence\n"
        f"{evidence_block}\n\n"
        "## Librarian decision\n"
        f"- 2+ issues: {decision.two_plus_issues}\n"
        f"- In tribal: {decision.in_tribal}\n"
        f"- Architectural: {decision.architectural}\n"
        f"- Load-bearing: {decision.load_bearing}\n"
        f"- Reason: {decision.reason or '(none)'}\n"
    )

    try:
        response = await gh_client.create_issue(
            title=title,
            body=body,
            labels=["adr-draft"],
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to open ADR-draft issue", exc_info=True)
        return None

    if not isinstance(response, dict):
        return None
    _metrics.increment("adr_drafts_opened")
    number = response.get("number")
    return int(number) if number is not None else None
