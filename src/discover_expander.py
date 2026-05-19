"""Discover expander — autonomous context recovery for coherence failures.

ADR-0063 W3a. When the ``discover-completeness`` evaluator rejects a
research brief, the current behavior is to retry the same prompt up to
``max_discover_attempts`` and then escalate via ``hitl-escalation`` /
``discover-stuck``. Per ADR-0063 §"Decision" (`discover` row, CTX
mitigation), the autonomous recovery step inserted BEFORE escalation is
a subagent dispatch that proposes new research queries based on the
coherence-failure reason; the expanded brief is then re-fed to the
discover step.

This module is pure: it takes an async ``executor`` callable (matching
the ``BaseRunner._execute`` signature) so the runner stays the only
component that owns subprocess wiring. Tests pass a mock executor and
assert on the parsed expansion query list.

Output contract — the subagent emits structured markers:

    EXPANSION_QUERIES_START
    - <one new research query per bullet>
    - <...>
    EXPANSION_QUERIES_END

A missing marker block falls open with an empty list (the runner then
proceeds to its next regular retry attempt; expansion was tried, did
not produce queries, no harm done). The expander never raises on the
agent transcript — only on ``CreditExhaustedError`` propagated by the
executor (via ``reraise_on_credit_or_bug`` upstream).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Task

logger = logging.getLogger("hydraflow.discover_expander")


_QUERIES_BLOCK_RE = re.compile(
    r"EXPANSION_QUERIES_START\s*\n(.*?)\n\s*EXPANSION_QUERIES_END",
    re.DOTALL,
)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$")


# Type alias for the executor callable. Matches ``BaseRunner._execute``'s
# subset of arguments the expander needs.
Executor = Callable[..., Awaitable[str]]


def build_expander_prompt(
    *,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    original_brief: str,
    coherence_failure_reason: str,
    failure_findings: list[str] | None = None,
) -> str:
    """Build the prompt that asks an agent to propose new research queries.

    The prompt frames the task as "what would 30% more confidence
    require?" per ADR-0063, then asks for ≥3 specific new queries
    grounded in the coherence-failure reason.
    """
    findings_section = ""
    if failure_findings:
        bullet_lines = "\n".join(f"- {f}" for f in failure_findings[:10])
        findings_section = (
            f"\n## Specific Findings From The Coherence Evaluator\n\n{bullet_lines}\n"
        )

    return f"""You are the discover-expander subagent for HydraFlow's Discover
phase (ADR-0063 W3a). The discover-completeness evaluator just rejected
a research brief for issue #{issue_number}. Before escalating to a
human, the factory dispatches you to propose new research queries that,
if answered, would lift the brief past the rubric on the next attempt.

## Issue #{issue_number}: {issue_title}

```
{issue_body or "(No description provided)"}
```

## Research Brief That Was Rejected

```
{original_brief or "(empty brief)"}
```

## Coherence Failure Reason

{coherence_failure_reason or "(no summary provided)"}
{findings_section}
## Your Mission

Ask: "what would 30% more confidence require?" The original discover
agent produced the brief above and the rubric judged it insufficient.
Your job is NOT to rewrite the brief — it is to propose research
queries the next discovery attempt should answer.

Propose at least three (3) new research queries. Each query must:

- Be specific enough that a researcher could go investigate it
  (no "do better"). Name a competitor, a persona, a metric, an ADR,
  a file path, a market segment.
- Address the SPECIFIC failure mode named in the coherence summary.
  - `missing-section:*` → name what evidence the missing section would
    need to ground (e.g. "research three competing dark-mode toggles
    and quote the accessibility commitments each makes").
  - `shallow-section:*` → name the depth gap (e.g. "find at least
    five user reports of friction with current per-device theme
    persistence on G2 or Reddit").
  - `paraphrase-only` → propose queries that would add NEW information
    not in the issue body (competitors, constraints, code paths,
    measurable targets).
  - `vague-criterion` → propose queries that would yield observable
    outcomes (metrics, exit codes, UI states).
  - `hid-ambiguity` → propose open questions the brief failed to name.
- Be answerable in one research pass — do not propose multi-month
  studies.

## Required Output

EXPANSION_QUERIES_START
- <query 1, specific and answerable>
- <query 2, addresses the failure mode>
- <query 3, adds new information>
- <optional further queries>
EXPANSION_QUERIES_END

Do NOT modify files. Do NOT write a new brief. Only emit the bullet
list inside the markers above.
"""


def parse_expansion_queries(transcript: str) -> list[str]:
    """Parse new research queries from an expander transcript.

    Returns the bulleted queries between ``EXPANSION_QUERIES_START`` and
    ``EXPANSION_QUERIES_END``. Returns an empty list when markers are
    missing or no bullets are present — callers should treat that as
    "expansion produced nothing useful" rather than an error.
    """
    match = _QUERIES_BLOCK_RE.search(transcript)
    if not match:
        return []
    block = match.group(1)
    queries: list[str] = []
    for line in block.splitlines():
        m = _BULLET_RE.match(line)
        if m:
            text = m.group(1).strip()
            if text:
                queries.append(text)
    return queries


def format_queries_for_prompt(queries: list[str]) -> str:
    """Format expansion queries as a prompt-injection block for retry.

    The runner appends this block to the next discovery prompt so the
    next attempt explicitly answers each query. Empty list → empty
    string (no injection).
    """
    if not queries:
        return ""
    lines = [
        "## Expanded Research Queries (from discover-expander, ADR-0063 W3a)",
        "",
        (
            "The previous discovery brief was rejected by the coherence "
            "evaluator. The discover-expander subagent proposed the "
            "following new research queries; your next brief MUST answer "
            "each of them, citing evidence."
        ),
        "",
    ]
    for q in queries:
        lines.append(f"- {q}")
    return "\n".join(lines)


async def expand_research_brief(
    *,
    task: Task,
    original_brief: str,
    coherence_failure_reason: str,
    failure_findings: list[str] | None,
    executor: Executor,
    cmd: list[str],
    cwd: Path,
) -> list[str]:
    """Dispatch a subagent to propose new research queries.

    Parameters
    ----------
    task:
        The discover-phase ``Task`` whose brief was rejected.
    original_brief:
        The rejected brief text.
    coherence_failure_reason:
        The ``SUMMARY`` line from the discover-completeness evaluator
        (e.g. ``"paraphrase-only — brief restates issue body"``).
    failure_findings:
        Optional ``FINDINGS`` bullets from the evaluator transcript.
    executor:
        An async callable matching ``BaseRunner._execute``'s signature:
        ``(cmd, prompt, cwd, event_data, *, on_output=None) -> str``.
        Injected so the discover runner stays the only owner of
        subprocess wiring.
    cmd:
        The agent CLI invocation list (the runner builds this once).
    cwd:
        The working directory for the agent subprocess.

    Returns
    -------
    list[str]
        Parsed expansion queries. May be empty when the subagent
        produced no usable output — the caller should treat that as
        "expansion attempted, no signal" and fall through to the
        existing escalation path.
    """
    prompt = build_expander_prompt(
        issue_number=task.id,
        issue_title=task.title,
        issue_body=task.body or "",
        original_brief=original_brief,
        coherence_failure_reason=coherence_failure_reason,
        failure_findings=failure_findings,
    )
    try:
        transcript = await executor(
            cmd,
            prompt,
            cwd,
            {"issue": task.id, "source": "discover:expander"},
        )
    except Exception as exc:  # noqa: BLE001 — log and fall through
        # Do not call ``reraise_on_credit_or_bug`` here — the executor
        # (``BaseRunner._execute``) already classifies credit / programmer
        # bugs and re-raises them through ``stream_claude_process``. Any
        # exception that reaches here is a transient agent failure; log
        # it and return no queries so the runner continues to escalation.
        logger.warning(
            "discover-expander dispatch failed for #%d: %s — returning no queries",
            task.id,
            exc,
        )
        return []
    queries = parse_expansion_queries(transcript)
    if not queries:
        logger.info("discover-expander for #%d produced no parseable queries", task.id)
    else:
        logger.info(
            "discover-expander for #%d produced %d new research queries",
            task.id,
            len(queries),
        )
    return queries
