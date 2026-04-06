"""Plan Compliance skill — verify implementation matches the planner's plan.

Compares the branch diff against planned file deltas and behavioral test specs
from the implementation plan. Flags scope creep (unplanned files), incomplete
implementation (missing planned files), and uncovered test specs.

Portable across Claude, Codex, and Pi backends. The skill is a pure prompt
executed by whichever agent CLI is configured; structured markers in the
transcript are parsed to determine pass/fail.
"""

from __future__ import annotations

import re


def build_plan_compliance_prompt(
    *, issue_number: int, issue_title: str, diff: str, plan_text: str = ""
) -> str:
    """Build a prompt that asks an agent to verify implementation matches the plan."""
    if not plan_text.strip():
        # Auto-pass when no plan is available — nothing to compare against.
        return ""

    return f"""You are running the Plan Compliance skill for issue #{issue_number}: {issue_title}.

Compare the implementation diff against the plan below and check for deviations.

## Implementation Plan

{plan_text}

## Branch Diff

```diff
{diff}
```

## Checks

1. **Scope creep** — Files modified or created in the diff that are NOT mentioned in the plan's file delta or implementation steps. Test files corresponding to planned production files are expected and NOT scope creep.
2. **Incomplete implementation** — Files listed in the plan's file delta (MODIFIED, ADDED) that do NOT appear in the diff. If the plan mentions a file should be modified but it is absent from the diff, flag it.
3. **Uncovered test specs** — Behavioral test specs or test requirements described in the plan that have no corresponding test in the diff. Look for test class names, test method names, or assertion patterns that match the plan's specs.

## Instructions

- Compare file paths from the plan's "File Delta" or "Implementation Steps" sections against files in the diff.
- For test coverage, match plan-described test behaviors against actual test code in the diff.
- Minor deviations are acceptable (e.g., a helper file needed for implementation). Use judgment.
- Do NOT modify any files. This is a read-only review.

## Required Output

If the implementation matches the plan:
PLAN_COMPLIANCE_RESULT: OK
SUMMARY: Implementation matches the plan
SCORE: <percentage 0-100>

If deviations are found:
PLAN_COMPLIANCE_RESULT: RETRY
SUMMARY: <comma-separated list of deviation categories>
SCORE: <percentage 0-100>
FINDINGS:
- <file_or_spec — description of deviation>
"""


def parse_plan_compliance_result(transcript: str) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a plan compliance transcript.

    Returns ``(passed, summary, findings)``.
    """
    # Defensive: if transcript is empty treat as pass. In production this path
    # is pre-empted by the empty-prompt early return in _run_skill(), but the
    # function is public and direct callers should still receive a safe result.
    if not transcript.strip():
        return True, "No plan available — skipped compliance check", []

    status_match = re.search(
        r"PLAN_COMPLIANCE_RESULT:\s*(OK|RETRY)", transcript, re.IGNORECASE
    )
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else ""

    findings: list[str] = []
    findings_match = re.search(
        r"FINDINGS:\s*\n((?:\s*-\s*.+\n?)+)", transcript, re.IGNORECASE
    )
    if findings_match:
        for line in findings_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                findings.append(stripped)

    return passed, summary, findings
