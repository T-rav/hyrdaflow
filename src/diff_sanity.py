"""Diff Sanity Check skill — reviews the working diff for common implementation mistakes.

Portable across Claude, Codex, and Pi backends. The skill is a pure prompt
executed by whichever agent CLI is configured; structured markers in the
transcript are parsed to determine pass/fail.
"""

from __future__ import annotations

import re


def build_diff_sanity_prompt(*, issue_number: int, issue_title: str, diff: str) -> str:
    """Build a prompt that asks an agent to review a diff for common mistakes."""
    return f"""You are running the Diff Sanity Check skill for issue #{issue_number}: {issue_title}.

Review the git diff below and check for the following problems:

1. **Accidental deletions** — unrelated code removed that should not have been
2. **Leftover debug code** — print(), console.log(), debugger, breakpoint(), commented-out code
3. **Missing imports** — new symbols referenced but not imported; removed code with stale imports
4. **Scope creep** — files changed that are unrelated to the issue
5. **Hardcoded secrets or credentials** — API keys, tokens, passwords in the diff
6. **Broken string literals** — unclosed quotes, malformed f-strings
7. **Obvious logic errors** — inverted conditions, off-by-one, unreachable code after return

## Diff

```diff
{diff}
```

## Instructions

- List each problem found with file path and line reference.
- If no problems are found, report OK.
- Do NOT modify any files. This is a read-only review.

## Required Output

If all checks pass:
DIFF_SANITY_RESULT: OK
SUMMARY: No issues found

If problems are found:
DIFF_SANITY_RESULT: RETRY
SUMMARY: <comma-separated list of problem categories found>
FINDINGS:
- <file:line — description>
"""


def parse_diff_sanity_result(transcript: str) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a diff sanity check transcript.

    Returns ``(passed, summary, findings)``.
    """
    status_match = re.search(
        r"DIFF_SANITY_RESULT:\s*(OK|RETRY)", transcript, re.IGNORECASE
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
