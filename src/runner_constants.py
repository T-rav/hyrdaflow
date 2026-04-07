"""Shared constants for runner prompt templates."""

from __future__ import annotations

# The memory suggestion block is included verbatim in all runner and
# conflict-resolution prompts.  Each caller uses
# `MEMORY_SUGGESTION_PROMPT.format(context=...)` with its own context value:
# "implementation", "planning", "review", "correction", "conflict resolution",
# or "rebuild".
MEMORY_SUGGESTION_PROMPT = """\
## Optional: Tribal-Memory Suggestion

If during this {context} you discovered a durable, load-bearing insight that
future agent runs would be strictly worse without, you may output ONE tribal
memory suggestion. Bar is HIGH: the insight should be a principle-level rule
that prevents a real failure mode, not a trivial observation.

MEMORY_SUGGESTION_START
principle: A single-sentence rule agents should follow going forward
rationale: Why this rule holds — the causal reasoning behind it
failure_mode: The concrete bad outcome that occurs when the rule is violated
scope: The module/subsystem the rule applies to (e.g. hydraflow/shape, hydraflow/db)
MEMORY_SUGGESTION_END

All four fields are required. Blocks missing any field are silently dropped.
Do NOT emit a suggestion unless you can fill all four fields non-trivially.
"""
