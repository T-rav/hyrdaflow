"""Declarative skill registry for agent post-implementation checks.

Skills are diff-based checks that run after implementation and before
verification. Each skill has a prompt builder, result parser, and
configuration for retry behavior. The registry replaces hardcoded
per-skill methods in ``agent.py`` with a data-driven loop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from diff_sanity import build_diff_sanity_prompt, parse_diff_sanity_result
from test_adequacy import build_test_adequacy_prompt, parse_test_adequacy_result

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class AgentSkill:
    """A post-implementation check that runs against the branch diff.

    Attributes
    ----------
    name:
        Short identifier (e.g. ``"diff-sanity"``).
    purpose:
        One-line description injected into the agent prompt so it knows
        what checks will run after it finishes.
    config_key:
        Name of the ``HydraFlowConfig`` field that controls max attempts.
        Set to 0 to disable the skill.
    blocking:
        If ``True``, a failed skill stops the pipeline. If ``False``,
        failures are logged as warnings.
    prompt_builder:
        ``(issue_number, issue_title, diff) -> str`` — builds the skill prompt.
    result_parser:
        ``(transcript) -> (passed, summary, findings)`` — parses structured
        markers from the agent's response.
    """

    name: str
    purpose: str
    config_key: str
    blocking: bool
    prompt_builder: Callable[..., str]
    result_parser: Callable[[str], tuple[bool, str, list[str]]]


# Built-in skills — registered in execution order
BUILTIN_SKILLS: list[AgentSkill] = [
    AgentSkill(
        name="diff-sanity",
        purpose="Review diff for accidental deletions, debug code, missing imports, scope creep, hardcoded secrets, and logic errors",
        config_key="max_diff_sanity_attempts",
        blocking=True,
        prompt_builder=build_diff_sanity_prompt,
        result_parser=parse_diff_sanity_result,
    ),
    AgentSkill(
        name="test-adequacy",
        purpose="Assess whether changed production code has adequate test coverage, edge cases, and regression safety",
        config_key="max_test_adequacy_attempts",
        blocking=False,
        prompt_builder=build_test_adequacy_prompt,
        result_parser=parse_test_adequacy_result,
    ),
]


def get_skills() -> list[AgentSkill]:
    """Return all registered skills in execution order."""
    return list(BUILTIN_SKILLS)


def format_skills_for_prompt(skills: list[AgentSkill]) -> str:
    """Format skills as a prompt section so the agent knows what checks will run.

    Injected into the implementation agent's instructions so it understands
    the post-implementation quality gates.
    """
    if not skills:
        return ""
    lines = ["## Post-Implementation Skills", ""]
    lines.append("The following checks run automatically after your implementation:")
    lines.append("")
    for skill in skills:
        blocking_tag = "[blocking]" if skill.blocking else "[non-blocking]"
        lines.append(f"- **{skill.name}** {blocking_tag} — {skill.purpose}")
    lines.append("")
    lines.append(
        "If a blocking skill fails, you will be asked to fix the issues and the skill will re-run."
    )
    return "\n".join(lines)
