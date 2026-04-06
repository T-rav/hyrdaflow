"""Scope Check skill — verifies the diff only touches files listed in the plan.

Compares the actual changed files from the branch diff against the planned
file deltas extracted from the implementation plan.  Test files for planned
files are allowed; truly unrelated file changes are flagged as scope creep.
"""

from __future__ import annotations

import re

from delta_verifier import parse_file_delta


def build_scope_check_prompt(
    *,
    issue_number: int,
    issue_title: str,
    diff: str,
    plan_text: str = "",
) -> str:
    """Build a prompt that asks an agent to check diff scope against the plan.

    If *plan_text* is empty the prompt instructs the agent to auto-pass,
    since there is nothing to compare against.
    """
    if not plan_text.strip():
        return (
            f"You are running the Scope Check skill for issue #{issue_number}: "
            f"{issue_title}.\n\n"
            "No implementation plan is available — auto-pass.\n\n"
            "SCOPE_CHECK_RESULT: OK\n"
            "SUMMARY: No plan available for comparison"
        )

    planned_files = parse_file_delta(plan_text)
    planned_section = (
        "\n".join(f"- `{f}`" for f in planned_files)
        if planned_files
        else "_(none extracted)_"
    )

    return f"""You are running the Scope Check skill for issue #{issue_number}: {issue_title}.

Compare the git diff below against the implementation plan's file delta to detect scope creep.

## Planned Files

{planned_section}

## Diff

```diff
{diff}
```

## Classification Rules

For each file in the diff that is NOT in the planned files list, classify it:

- **OK** — Test file for a planned file (e.g. `tests/test_foo.py` for `src/foo.py`), \
import fix, lint auto-fix, `__init__.py` update, or config file touched by a planned change.
- **WARN** — Shared utility or type file touched as a side-effect of a planned change. \
Log but do not fail.
- **FAIL** — Different feature, different module, different concern. Unrelated scope creep.

## Instructions

- List every file from the diff.
- For files NOT in the planned list, provide a classification and reason.
- If any file is classified FAIL, the overall result is RETRY.
- If all unplanned files are OK or WARN, the overall result is OK.
- Do NOT modify any files. This is a read-only review.

## Required Output

SCOPE_CHECK_RESULT: OK|RETRY
SUMMARY: <one-line summary>
UNPLANNED_FILES:
- [OK|WARN|FAIL] path — reason
"""


def parse_scope_check_result(transcript: str) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a scope check transcript.

    Returns ``(passed, summary, unplanned_files)``.
    """
    status_match = re.search(
        r"SCOPE_CHECK_RESULT:\s*(OK|RETRY)", transcript, re.IGNORECASE
    )
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else ""

    unplanned: list[str] = []
    unplanned_match = re.search(
        r"UNPLANNED_FILES:\s*\n((?:\s*-\s*.+\n?)+)", transcript, re.IGNORECASE
    )
    if unplanned_match:
        for line in unplanned_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                unplanned.append(stripped)

    return passed, summary, unplanned
