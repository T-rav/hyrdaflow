"""Plan constants — shared definitions for plan structure and validation."""

from __future__ import annotations

from typing import Literal

PlanScale = Literal["lite", "full"]

# Canonical section descriptions — single source of truth for prompt generation.
# Each entry is (header, description).  Order matches the desired prompt order.
PLAN_SECTION_DESCRIPTIONS: tuple[tuple[str, str], ...] = (
    (
        "## Files to Modify",
        "list each existing file and what changes are needed "
        "(must reference at least one file path)",
    ),
    (
        "## New Files",
        'list new files to create, or state "None" if no new files needed',
    ),
    (
        "## File Delta",
        "structured list of all planned file changes using this exact format:\n"
        "  ```\n"
        "  MODIFIED: path/to/file.py\n"
        "  ADDED: path/to/new_file.py\n"
        "  REMOVED: path/to/old_file.py\n"
        "  ```\n"
        "  Each line must start with MODIFIED:, ADDED:, or REMOVED: "
        "followed by the file path.",
    ),
    (
        "## Task Graph",
        "dependency-ordered implementation phases using `### P{N} — Name` subsections. "
        "Each phase lists **Files:** (paths to create/modify), "
        "**Tests:** (behavioral specs — observable outcomes, not test code), "
        "and **Depends on:** (prior phase numbers or 'none'). "
        "Lower-numbered phases execute first; independent phases at the same level "
        "can run in parallel. Max 6 phases per plan.",
    ),
    (
        "## Implementation Steps",
        "actionable implementation checklist/steps (numbered, bulleted, checkbox, or heading-style) "
        "with concrete code targets and at least one verification step",
    ),
    (
        "## Testing Strategy",
        "what tests to write and what to verify "
        "(must reference specific test file paths or patterns; do NOT defer testing)",
    ),
    (
        "## Acceptance Criteria",
        "extracted or synthesized from the issue",
    ),
    (
        "## Key Considerations",
        "edge cases, backward compatibility, dependencies",
    ),
)

REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Files to Modify",
    "## New Files",
    "## File Delta",
    "## Task Graph",
    "## Testing Strategy",
    "## Acceptance Criteria",
    "## Key Considerations",
)

LITE_REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Files to Modify",
    "## Implementation Steps",
    "## Testing Strategy",
)

# Body length threshold for scale detection heuristic.
LITE_BODY_THRESHOLD = 500

# Title keywords suggesting a small fix (used with body length heuristic).
SMALL_FIX_WORDS: frozenset[str] = frozenset(
    {"fix", "typo", "correct", "patch", "update", "rename", "bump", "tweak"}
)
