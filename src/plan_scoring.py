"""Plan scoring — actionability assessment for implementation plans."""

from __future__ import annotations

import re

from plan_constants import PlanScale
from task_graph import extract_impl_step_texts, extract_phases


def _score_task_graph(plan: str, scale: PlanScale) -> tuple[int, bool]:
    """Score the Task Graph section. Returns ``(points, was_scored)``."""
    if scale == "lite":
        return 0, False

    task_graph_match = re.search(
        r"## Task Graph\s*\n(.*?)(?=\n## |\Z)",
        plan,
        re.DOTALL | re.IGNORECASE,
    )
    if not task_graph_match:
        return 0, False

    phases = extract_phases(task_graph_match.group(1))
    if not phases:
        return 0, False

    score = 20  # Has phases
    if len(phases) >= 2:
        score += 15
    if any(p.files for p in phases):
        score += 25
    if any(p.tests for p in phases):
        score += 10
    if any(p.depends_on for p in phases):
        score += 10
    return score, True


def _score_impl_steps(
    plan: str, scale: PlanScale, *, task_graph_already_scored: bool
) -> int:
    """Score the Implementation Steps section."""
    if task_graph_already_scored:
        return 0

    impl_steps_match = re.search(
        r"## Implementation Steps\s*\n(.*?)(?=\n## |\Z)",
        plan,
        re.DOTALL | re.IGNORECASE,
    )
    impl_step_texts = (
        extract_impl_step_texts(impl_steps_match.group(1)) if impl_steps_match else []
    )
    if not impl_step_texts:
        return 0

    score = 20
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

    shallow_steps = [s for s in impl_step_texts if len(re.findall(r"\b\w+\b", s)) < 3]
    if not shallow_steps:
        score += 10
    avg_words = sum(len(re.findall(r"\b\w+\b", s)) for s in impl_step_texts) / len(
        impl_step_texts
    )
    if avg_words >= 6:
        score += 10

    return score


def _score_file_delta(plan: str) -> int:
    """Score the File Delta section."""
    file_delta_match = re.search(
        r"## File Delta\s*\n(.*?)(?=\n## |\Z)", plan, re.DOTALL | re.IGNORECASE
    )
    if file_delta_match and re.search(
        r"^\s*(MODIFIED|ADDED|REMOVED):\s+\S",
        file_delta_match.group(1),
        re.MULTILINE,
    ):
        return 10
    return 0


def _score_testing_strategy(plan: str) -> int:
    """Score the Testing Strategy section."""
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
        return 10
    return 0


def score_actionability(plan: str, *, scale: PlanScale = "full") -> tuple[int, str]:
    """Return actionability ``(score, rank)`` for *plan*."""
    task_graph_points, was_scored = _score_task_graph(plan, scale)
    impl_points = _score_impl_steps(plan, scale, task_graph_already_scored=was_scored)
    file_delta_points = _score_file_delta(plan)
    testing_points = _score_testing_strategy(plan)

    score = max(
        0,
        min(100, task_graph_points + impl_points + file_delta_points + testing_points),
    )
    if score >= 85:
        rank = "high"
    elif score >= 65:
        rank = "medium"
    else:
        rank = "low"
    return score, rank
