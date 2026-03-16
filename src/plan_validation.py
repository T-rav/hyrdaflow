"""Plan validation — structural and content checks for implementation plans."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from plan_constants import (
    LITE_REQUIRED_SECTIONS,
    REQUIRED_SECTIONS,
    PlanScale,
)
from task_graph import extract_impl_step_texts, extract_phases

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import Task

logger = logging.getLogger("hydraflow.plan_validation")

# Pattern for detecting deferred testing strategy.
_TEST_LATER_RE = re.compile(
    r"\b(later|tbd|todo|to\s+be\s+determined|will\s+be\s+added\s+later)\b",
    re.IGNORECASE,
)


def _significant_words(text: str, min_length: int = 4) -> set[str]:
    """Return lowercase words from *text* that are at least *min_length* chars."""
    stop = {
        "this",
        "that",
        "with",
        "from",
        "have",
        "been",
        "will",
        "should",
        "would",
        "could",
        "about",
        "into",
        "when",
        "them",
        "then",
        "than",
        "also",
        "more",
        "some",
        "only",
        "each",
        "make",
        "like",
        "need",
        "does",
    }
    words = set()
    for w in re.findall(r"[a-zA-Z]+", text.lower()):
        if len(w) >= min_length and w not in stop:
            words.add(w)
    return words


def _validate_task_graph(plan: str) -> list[str]:
    """Validate the ``## Task Graph`` section of a full plan."""
    errors: list[str] = []
    task_graph_match = re.search(
        r"## Task Graph\s*\n(.*?)(?=\n## |\Z)",
        plan,
        re.DOTALL | re.IGNORECASE,
    )
    if not task_graph_match:
        return errors
    phases = extract_phases(task_graph_match.group(1))
    if not phases:
        errors.append("## Task Graph must contain at least one ### P{N} phase")
        return errors
    for phase in phases:
        if not phase.files:
            errors.append(
                f"Task Graph phase {phase.name} must include "
                f"**Files:** with at least one path"
            )
        if not phase.tests:
            errors.append(
                f"Task Graph phase {phase.name} must include "
                f"**Tests:** with at least one behavioral spec"
            )
    phase_ids = {p.id for p in phases}
    for phase in phases:
        for dep in phase.depends_on:
            if dep not in phase_ids:
                errors.append(
                    f"Task Graph phase {phase.name} depends on "
                    f"{dep} which does not exist"
                )
    return errors


def validate_plan(
    issue: Task,
    plan: str,
    scale: PlanScale = "full",
    *,
    config: HydraFlowConfig,
) -> list[str]:
    """Validate that *plan* has all required sections and minimum content.

    Returns a list of validation error strings.  An empty list means the
    plan is valid.
    """
    errors: list[str] = []

    required = LITE_REQUIRED_SECTIONS if scale == "lite" else REQUIRED_SECTIONS

    # --- Required sections ---
    for section in required:
        if not re.search(re.escape(section), plan, re.IGNORECASE):
            errors.append(f"Missing required section: {section}")

    # --- Files to Modify must reference at least one file path ---
    files_to_modify_match = re.search(
        r"## Files to Modify\s*\n(.*?)(?=\n## |\Z)", plan, re.DOTALL | re.IGNORECASE
    )
    if files_to_modify_match:
        files_to_modify_body = files_to_modify_match.group(1)
        if not re.search(r"[\w\-]+(?:/[\w\-]+)+|[\w\-]+\.[\w]+", files_to_modify_body):
            errors.append("## Files to Modify must reference at least one file path")

    # --- Testing Strategy must reference at least one test file/pattern ---
    testing_strategy_match = re.search(
        r"## Testing Strategy\s*\n(.*?)(?=\n## |\Z)",
        plan,
        re.DOTALL | re.IGNORECASE,
    )
    if testing_strategy_match:
        testing_strategy_body = testing_strategy_match.group(1)
        if not re.search(
            r"test[\w\-]*\.[\w]+|tests/", testing_strategy_body, re.IGNORECASE
        ):
            errors.append(
                "## Testing Strategy must reference at least one test file or pattern"
            )

    # --- Task Graph validation (full plans) ---
    if scale != "lite":
        errors.extend(_validate_task_graph(plan))

    # --- Implementation Steps must contain at least one actionable step ---
    impl_steps_match = re.search(
        r"## Implementation Steps\s*\n(.*?)(?=\n## |\Z)",
        plan,
        re.DOTALL | re.IGNORECASE,
    )
    if impl_steps_match:
        impl_steps_body = impl_steps_match.group(1)
        impl_step_texts = extract_impl_step_texts(impl_steps_body)
        if not impl_step_texts:
            errors.append(
                "## Implementation Steps must include at least one actionable step"
            )
        else:
            if scale != "lite" and len(impl_step_texts) < 2:
                errors.append(
                    "## Implementation Steps must include at least 2 steps for full plans"
                )
            shallow_steps = [
                s for s in impl_step_texts if len(re.findall(r"\b\w+\b", s)) < 3
            ]
            if shallow_steps:
                errors.append(
                    "## Implementation Steps must include enough detail per step "
                    "(at least 3 words each)"
                )
            if scale != "lite":
                has_concrete_target = any(
                    re.search(
                        r"[\w\-]+(?:/[\w\-]+)+|[\w\-]+\.[\w]+|`[^`]+`|\w+\(",
                        s,
                    )
                    for s in impl_step_texts
                )
                if not has_concrete_target:
                    errors.append(
                        "## Implementation Steps must reference at least one concrete code target "
                        "(file path, symbol, or callable)"
                    )

    # --- Minimum word count (full plans only) ---
    if scale != "lite":
        word_count = len(plan.split())
        min_words = config.min_plan_words
        if word_count < min_words:
            errors.append(f"Plan has {word_count} words, minimum is {min_words}")

    # --- [NEEDS CLARIFICATION] marker count ---
    clarification_markers = re.findall(
        r"\[NEEDS CLARIFICATION(?::\s*[^\]]+)?\]", plan, re.IGNORECASE
    )
    if len(clarification_markers) >= 4:
        errors.append(
            f"Plan has {len(clarification_markers)} [NEEDS CLARIFICATION] markers "
            f"(max 3) — issue needs more detail before implementation"
        )

    # --- Soft word-overlap check (warning only) ---
    title_words = _significant_words(issue.title)
    plan_words = _significant_words(plan)
    overlap = title_words & plan_words
    if not overlap and title_words:
        logger.warning(
            "Plan for issue #%d may not address the issue title %r "
            "(no significant word overlap)",
            issue.id,
            issue.title,
        )

    return errors


def run_phase_gates(
    plan: str,
    config: HydraFlowConfig,
) -> tuple[list[str], list[str]]:
    """Run Phase -1 gates on *plan*.

    Returns ``(blocking_errors, warnings)``.
    """
    blocking: list[str] = []
    warnings: list[str] = []

    # --- Simplicity gate: warn if > max_new_files_warning new files ---
    new_files_match = re.search(
        r"## New Files\s*\n(.*?)(?=\n## |\Z)", plan, re.DOTALL | re.IGNORECASE
    )
    if new_files_match:
        new_files_body = new_files_match.group(1)
        new_file_entries = re.findall(
            r"[\w\-]+(?:/[\w\-]+)+\.[\w]+|[\w\-]+\.[\w]+", new_files_body
        )
        threshold = config.max_new_files_warning
        if len(new_file_entries) > threshold:
            warnings.append(
                f"Simplicity gate: plan creates {len(new_file_entries)} new files "
                f"(threshold is {threshold})"
            )

    # --- Testing gate: reject if Testing Strategy is empty or deferred ---
    testing_strategy_match = re.search(
        r"## Testing Strategy\s*\n(.*?)(?=\n## |\Z)",
        plan,
        re.DOTALL | re.IGNORECASE,
    )
    if testing_strategy_match:
        testing_strategy_body = testing_strategy_match.group(1).strip()
        if not testing_strategy_body or testing_strategy_body.lower() in (
            "none",
            "n/a",
            "-",
        ):
            blocking.append("Testing gate: Testing Strategy section is empty")
        elif _TEST_LATER_RE.search(testing_strategy_body):
            blocking.append(
                "Testing gate: Testing Strategy defers tests (e.g. 'later', 'TBD')"
            )

    # --- Constitution gate: check against constitution.md ---
    constitution_path = config.repo_root / "constitution.md"
    if constitution_path.is_file():
        try:
            constitution_text = constitution_path.read_text()
            principles = [
                line.strip().lstrip("-*").strip()
                for line in constitution_text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            plan_lower = plan.lower()
            for principle in principles:
                if principle and principle.lower() in plan_lower:
                    blocking.append(
                        f"Constitution gate: plan may violate principle: {principle!r}"
                    )
        except OSError:
            logger.warning("Could not read constitution.md")

    # Log warnings
    for w in warnings:
        logger.warning(w)

    return blocking, warnings
