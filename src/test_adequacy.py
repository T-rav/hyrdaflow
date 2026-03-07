"""Test Adequacy skill — verifies changed code has sufficient test coverage.

Portable across Claude, Codex, and Pi backends. The skill is a pure prompt
executed by whichever agent CLI is configured; structured markers in the
transcript are parsed to determine pass/fail.
"""

from __future__ import annotations

import re


def build_test_adequacy_prompt(
    *, issue_number: int, issue_title: str, diff: str
) -> str:
    """Build a prompt that asks an agent to assess test coverage of a diff."""
    return f"""You are running the Test Adequacy skill for issue #{issue_number}: {issue_title}.

Review the git diff below and assess whether the changed production code has adequate test coverage.

## Diff

```diff
{diff}
```

## Checks

For each changed or added production function/method/class, verify:

1. **Has a corresponding test** — at least one test exercises the new/changed path
2. **Edge cases covered** — empty inputs, None values, boundary conditions, error paths
3. **Regression safety** — if existing behavior changed, tests verify the new behavior
4. **No test-only gaps** — new test utilities or fixtures are themselves tested if non-trivial

## Instructions

- List each gap found with the production file:function and what test is missing.
- If coverage is adequate, report OK.
- Do NOT modify any files. This is a read-only assessment.
- Ignore test file changes when assessing adequacy — focus on whether production code is tested.

## Required Output

If coverage is adequate:
TEST_ADEQUACY_RESULT: OK
SUMMARY: All changed code has adequate test coverage

If gaps exist:
TEST_ADEQUACY_RESULT: RETRY
SUMMARY: <comma-separated list of gap categories>
GAPS:
- <production_file:function — what test is missing>
"""


def parse_test_adequacy_result(transcript: str) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a test adequacy transcript.

    Returns ``(passed, summary, gaps)``.
    """
    status_match = re.search(
        r"TEST_ADEQUACY_RESULT:\s*(OK|RETRY)", transcript, re.IGNORECASE
    )
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else ""

    gaps: list[str] = []
    gaps_match = re.search(r"GAPS:\s*\n((?:\s*-\s*.+\n?)+)", transcript, re.IGNORECASE)
    if gaps_match:
        for line in gaps_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                gaps.append(stripped)

    return passed, summary, gaps
