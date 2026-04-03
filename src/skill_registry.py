"""Declarative skill and tool registries for agent workflows.

Two registries:

1. **AgentSkill** — post-implementation checks run as separate subprocesses
   after the agent finishes (diff-sanity, test-adequacy). Orchestrated by
   ``AgentRunner._run_skill()``.

2. **AgentTool** — slash commands the agent should actively invoke during
   its work at specific workflow checkpoints. Injected into the agent's
   prompt so it knows what commands are available, when to run them, and why.
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


# ---------------------------------------------------------------------------
# Agent Tools — slash commands discovered from .claude/commands/hf.*.md
# ---------------------------------------------------------------------------

import logging
from pathlib import Path

_tool_logger = logging.getLogger("hydraflow.skill_registry")


@dataclass(frozen=True)
class AgentTool:
    """A slash command the agent should actively invoke during implementation.

    Discovered at runtime by scanning ``.claude/commands/hf.*.md`` files.
    """

    command: str
    purpose: str


def discover_tools(repo_root: str | Path) -> list[AgentTool]:
    """Scan ``.claude/commands/`` for ``hf.*.md`` files and build tool entries.

    Each file's stem becomes the command (e.g. ``hf.quality-gate.md`` →
    ``/hf.quality-gate``) and the first non-empty line starting with ``#``
    becomes the purpose.
    """
    commands_dir = Path(repo_root) / ".claude" / "commands"
    if not commands_dir.is_dir():
        return []

    tools: list[AgentTool] = []
    for path in sorted(commands_dir.glob("hf.*.md")):
        command = f"/{path.stem}"
        purpose = _extract_purpose(path)
        if purpose:
            tools.append(AgentTool(command=command, purpose=purpose))
        else:
            _tool_logger.debug("Skipping %s — no heading found", path.name)

    return tools


def _extract_purpose(path: Path) -> str:
    """Extract the first markdown heading from a command file as its purpose."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#"):
                    return stripped.lstrip("#").strip()
        return ""
    except OSError:
        return ""


def format_tools_for_prompt(tools: list[AgentTool]) -> str:
    """Format discovered tools as a prompt section for the agent.

    The agent sees what commands are available and is instructed to run
    them at appropriate checkpoints during its work.
    """
    if not tools:
        return ""
    lines = ["## Available Tools", ""]
    lines.append(
        "You have these slash commands available. Run them before committing your work:"
    )
    lines.append("")
    for tool in tools:
        lines.append(f"- `{tool.command}` — {tool.purpose}")
    lines.append("")
    lines.append(
        "Run each tool before committing. If a tool reports issues, fix them before continuing."
    )
    return "\n".join(lines)
