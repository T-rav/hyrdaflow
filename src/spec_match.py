"""Spec-match evaluation — compare implementation against original requirements.

Used across the pipeline to ensure what was built matches what was asked:
- Post-implementation self-review (agent checks its own work)
- Review phase spec-match (reviewer compares PR against spec)
- Pre-merge quality gate (early verification judge)
- Requirements gap detection (flag missing scope during implementation)
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Task

logger = logging.getLogger("hydraflow.spec_match")

_SPEC_MATCH_START = "SPEC_MATCH_START"
_SPEC_MATCH_END = "SPEC_MATCH_END"
_REQ_GAP_START = "REQUIREMENTS_GAP_START"
_REQ_GAP_END = "REQUIREMENTS_GAP_END"


def build_spec_context(issue: Task) -> str:
    """Extract the full specification context from an issue and its comments.

    Looks for Shape conversation enrichment, discovery briefs, and
    decomposition guidance in the issue comments. Returns a structured
    context string suitable for injection into agent prompts.
    """
    parts = [f"## Original Issue\n\n**Title:** {issue.title}\n\n{issue.body or ''}"]

    for comment in issue.comments or []:
        if "## Product Discovery Brief" in comment:
            parts.append(f"## Discovery Research\n\n{comment}")
        elif "## Final Product Direction" in comment:
            parts.append(f"## Product Direction (from Shape)\n\n{comment}")
        elif "Selected Product Direction" in comment:
            parts.append(f"## Selected Direction\n\n{comment}")
        elif "DECOMPOSITION REQUIRED" in comment:
            parts.append(f"## Decomposition Guidance\n\n{comment}")
        elif "## Implementation Plan" in comment:
            parts.append(f"## Plan\n\n{comment}")

    return "\n\n---\n\n".join(parts)


def build_self_review_prompt(issue: Task, diff_summary: str) -> str:
    """Build a prompt for post-implementation self-review.

    The agent re-reads the original spec and evaluates whether the
    implementation matches what was asked.
    """
    spec_context = build_spec_context(issue)
    return f"""You are a quality assurance agent evaluating whether an implementation
matches its original specification.

{spec_context}

## Implementation Diff Summary

{diff_summary}

## Your Task

Compare the implementation against the original specification. Evaluate:

1. **Completeness**: Does the implementation cover ALL requirements from the
   issue and any Shape/Plan enrichment? List each requirement and whether
   it's addressed.

2. **Accuracy**: Does the implementation match the INTENT of the specification?
   Not just the letter, but the spirit of what was asked.

3. **Scope drift**: Has the implementation added anything NOT in the spec?
   Unnecessary features, over-engineering, or scope creep?

4. **Missing pieces**: What's in the spec but NOT in the implementation?
   Be specific about what's missing and why it matters.

## Required Output

{_SPEC_MATCH_START}
## Spec Match Assessment

**Overall verdict:** MATCH | PARTIAL | MISMATCH

### Requirements Coverage
- [x] Requirement 1 — addressed in file.py
- [ ] Requirement 2 — MISSING: not implemented
- [x] Requirement 3 — addressed but differs from spec: <explanation>

### Gaps Found
- <specific gap and its impact>

### Scope Drift
- <anything added beyond spec, if any>

### Recommendation
<specific action: proceed to review | fix gaps first | escalate>
{_SPEC_MATCH_END}
"""


def build_requirements_gap_prompt(issue: Task) -> str:
    """Build a prompt section for detecting requirements gaps during implementation.

    Injected into the implementation agent prompt so it can flag missing
    requirements as it works.
    """
    return f"""
## Requirements Gap Detection

As you implement, you may discover that the specification is incomplete —
a needed API isn't mentioned, a dependency wasn't considered, or a user
flow wasn't specified. When this happens:

1. STILL implement what you can with reasonable assumptions
2. Flag the gap using these markers:

{_REQ_GAP_START}
- gap: <what's missing from the spec>
  impact: <how this affects the implementation>
  assumption: <what you assumed to proceed>
{_REQ_GAP_END}

Only flag genuine gaps — things the spec SHOULD have covered but didn't.
Do not flag normal implementation details that don't need spec coverage.
"""


def build_reviewer_spec_section(issue: Task) -> str:
    """Build a spec-match section for the reviewer prompt.

    Extends the reviewer's evaluation to include specification matching,
    not just code quality.
    """
    spec_context = build_spec_context(issue)
    return f"""
## Specification Match (additional review dimension)

The original specification for this issue:

<details><summary>Full Spec Context</summary>

{spec_context}

</details>

In addition to code quality, evaluate whether the PR actually delivers
what the specification asked for. In your review, include a section:

### Spec Match
- Does the PR address the core requirement?
- Are any specified features missing?
- Has the implementation diverged from the spec in any way?

If the spec match is poor, this should be a REQUEST_CHANGES verdict
regardless of code quality.
"""


def extract_spec_match(transcript: str) -> dict:
    """Extract spec-match assessment from agent transcript."""
    start = transcript.find(_SPEC_MATCH_START)
    end = transcript.find(_SPEC_MATCH_END)
    if start == -1 or end == -1:
        return {}

    content = transcript[start + len(_SPEC_MATCH_START) : end].strip()

    # Extract verdict
    verdict = "unknown"
    verdict_match = re.search(r"\*\*Overall verdict:\*\*\s*(\w+)", content)
    if verdict_match:
        verdict = verdict_match.group(1).upper()

    # Extract gaps
    gaps = re.findall(r"- \[ \] (.+)", content)

    return {
        "verdict": verdict,
        "gaps": gaps,
        "content": content,
    }


def extract_requirements_gaps(transcript: str) -> list[dict]:
    """Extract requirements gaps flagged during implementation."""
    start = transcript.find(_REQ_GAP_START)
    end = transcript.find(_REQ_GAP_END)
    if start == -1 or end == -1:
        return []

    content = transcript[start + len(_REQ_GAP_START) : end].strip()
    gaps = []
    current: dict[str, str] = {}
    for raw_line in content.split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("- gap:"):
            if current:
                gaps.append(current)
            current = {"gap": stripped[6:].strip()}
        elif stripped.startswith("impact:"):
            current["impact"] = stripped[7:].strip()
        elif stripped.startswith("assumption:"):
            current["assumption"] = stripped[11:].strip()
    if current:
        gaps.append(current)
    return gaps
