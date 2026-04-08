"""Sensor output enricher — positive prompt injection for agent failures.

Wraps raw tool output (ruff, pyright, pytest, bandit, etc.) with project-
specific coaching hints before the text lands in an agent transcript.
The raw output is preserved verbatim; hints are appended as an
``## Agent Hints`` block so agents can prefer them over general reasoning
about unfamiliar errors.

Rules live in :mod:`sensor_rules` as a pure data registry. This module
contains only the matching engine and the public ``enrich`` function.

Part of the harness-engineering foundations (#6426).
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ANY_TOOL",
    "MATCH_ALL_TOOLS",
    "ErrorPattern",
    "FileChanged",
    "Rule",
    "RuleTrigger",
    "enrich",
    "matching_rules",
]

# Tool name sentinel meaning "fire for any tool output, not just a specific one".
# Used on the RULE side: Rule(tool=ANY_TOOL, ...) fires regardless of caller tool.
ANY_TOOL = "any"

# Caller-side sentinel meaning "match every rule regardless of tool scope".
# Used by callers that do not know which tool produced the output (e.g.
# :class:`HarnessInsightStore` enriching generic failure records).
MATCH_ALL_TOOLS = "*"


class RuleTrigger:
    """Base class for rule triggers. A trigger decides whether a rule fires."""

    def matches(self, *, raw_output: str, changed_files: Sequence[Path]) -> bool:
        del raw_output, changed_files
        raise NotImplementedError


@dataclass(frozen=True)
class FileChanged(RuleTrigger):
    """Fire when any changed file matches a glob pattern.

    Patterns are matched against forward-slash POSIX paths so globs work
    consistently on Windows and *nix. Use ``src/*_loop.py`` for background
    loop modules, ``src/models.py`` for exact files, etc.
    """

    pattern: str

    def matches(self, *, raw_output: str, changed_files: Sequence[Path]) -> bool:
        del raw_output  # unused for this trigger type
        for path in changed_files:
            posix = path.as_posix()
            if fnmatch.fnmatch(posix, self.pattern):
                return True
        return False


@dataclass(frozen=True)
class ErrorPattern(RuleTrigger):
    """Fire when the raw tool output matches a regex.

    The regex is compiled with ``re.MULTILINE`` so ``^`` / ``$`` work per-line.
    """

    regex: str

    def matches(self, *, raw_output: str, changed_files: Sequence[Path]) -> bool:
        del changed_files  # unused for this trigger type
        return bool(re.search(self.regex, raw_output, re.MULTILINE))


@dataclass(frozen=True)
class Rule:
    """A single enrichment rule.

    Attributes:
        id: Stable identifier used for telemetry (``harness_insights``
            records which rules fire on which tool failures).
        tool: Tool name to match (``ruff``, ``pyright``, ``pytest``,
            ``bandit``) or ``"any"`` to match regardless of tool.
        trigger: The condition that decides whether the rule fires.
        hint: Short prose appended to the Agent Hints block. Should
            reference a doc anchor when possible (e.g.
            ``docs/agents/avoided-patterns.md#...``).
    """

    id: str
    tool: str
    trigger: RuleTrigger
    hint: str


@dataclass
class EnrichmentResult:
    """Return value of :func:`matching_rules` — the rules that fired."""

    fired: list[Rule] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.fired)


def _tool_matches(rule_tool: str, tool: str) -> bool:
    if tool == MATCH_ALL_TOOLS:
        return True
    return rule_tool in (ANY_TOOL, tool)


def matching_rules(
    rules: Iterable[Rule],
    *,
    tool: str,
    raw_output: str,
    changed_files: Sequence[Path],
) -> EnrichmentResult:
    """Return the rules that fire for a given tool failure.

    Pure function: same inputs always yield the same fired-rule list.
    Suitable for unit testing without touching disk or subprocess state.
    """
    fired: list[Rule] = []
    for rule in rules:
        if not _tool_matches(rule.tool, tool):
            continue
        if rule.trigger.matches(raw_output=raw_output, changed_files=changed_files):
            fired.append(rule)
    return EnrichmentResult(fired=fired)


def enrich(
    *,
    tool: str,
    raw_output: str,
    changed_files: Sequence[Path],
    rules: Iterable[Rule],
) -> str:
    """Append an Agent Hints block to raw tool output for matching rules.

    The raw output is preserved verbatim and returned unchanged when no
    rules fire. When at least one rule fires, the return value is
    ``<raw_output>\\n\\n## Agent Hints\\n\\n- <hint1>\\n- <hint2>\\n``.

    Agents are instructed (in their system prompt, see #6426) to prefer
    the Agent Hints block over general reasoning when it is present.
    """
    result = matching_rules(
        rules,
        tool=tool,
        raw_output=raw_output,
        changed_files=changed_files,
    )
    if not result:
        return raw_output

    hint_lines = "\n".join(f"- {rule.hint}" for rule in result.fired)
    return f"{raw_output}\n\n## Agent Hints\n\n{hint_lines}\n"
