"""Plan scoring — actionability assessment for implementation plans."""

from __future__ import annotations

import re

from plan_constants import PlanScale
from task_graph import extract_impl_step_texts, extract_phases


def score_actionability(plan: str, *, scale: PlanScale = "full") -> tuple[int, str]:
    """Return actionability ``(score, rank)`` for *plan*."""
    score = 0

    # --- Task Graph scoring (full plans) ---
    task_graph_match = re.search(
        r"## Task Graph\s*\n(.*?)(?=\n## |\Z)",
        plan,
        re.DOTALL | re.IGNORECASE,
    )
    if task_graph_match and scale != "lite":
        phases = extract_phases(task_graph_match.group(1))
        if phases:
            score += 20  # Has phases
            if len(phases) >= 2:
                score += 15  # Multiple phases
            # Check for file references
            has_files = any(p.files for p in phases)
            if has_files:
                score += 25
            # Check for behavioral test specs
            has_tests = any(p.tests for p in phases)
            if has_tests:
                score += 10
            # Check for dependency structure
            has_deps = any(p.depends_on for p in phases)
            if has_deps:
                score += 10

    # --- Implementation Steps scoring (lite plans only, or fallback when
    #     no Task Graph phases were found) ---
    task_graph_already_scored = (
        task_graph_match
        and scale != "lite"
        and bool(extract_phases(task_graph_match.group(1)) if task_graph_match else [])
    )
    impl_steps_match = re.search(
        r"## Implementation Steps\s*\n(.*?)(?=\n## |\Z)",
        plan,
        re.DOTALL | re.IGNORECASE,
    )
    impl_step_texts = (
        extract_impl_step_texts(impl_steps_match.group(1)) if impl_steps_match else []
    )

    if not task_graph_already_scored and impl_step_texts:
        score += 20
        if scale != "lite" and len(impl_step_texts) >= 2:
            score += 15
        elif scale == "lite" and impl_step_texts:
            score += 10

        has_concrete_target = any(
            re.search(r"[\w\-]+(?:/[\w\-]+)+|[\w\-]+\.[\w]+|`[^`]+`|\w+\(", s)
            for s in impl_step_texts
        )
        if has_concrete_target:
            score += 25

        if impl_step_texts:
            shallow_steps = [
                s for s in impl_step_texts if len(re.findall(r"\b\w+\b", s)) < 3
            ]
            if not shallow_steps:
                score += 10
            avg_words = sum(
                len(re.findall(r"\b\w+\b", s)) for s in impl_step_texts
            ) / len(impl_step_texts)
            if avg_words >= 6:
                score += 10

    file_delta_match = re.search(
        r"## File Delta\s*\n(.*?)(?=\n## |\Z)", plan, re.DOTALL | re.IGNORECASE
    )
    if file_delta_match and re.search(
        r"^\s*(MODIFIED|ADDED|REMOVED):\s+\S",
        file_delta_match.group(1),
        re.MULTILINE,
    ):
        score += 10

    testing_strategy_match = re.search(
        r"## Testing Strategy\s*\n(.*?)(?=\n## |\Z)",
        plan,
        re.DOTALL | re.IGNORECASE,
    )
    if testing_strategy_match and re.search(
        r"test[\w\-]*\.[\w]+|tests/|pytest|unit test|integration test",
        testing_strategy_match.group(1),
        re.IGNORECASE,
    ):
        score += 10

    score = max(0, min(100, score))
    if score >= 85:
        rank = "high"
    elif score >= 65:
        rank = "medium"
    else:
        rank = "low"
    return score, rank
