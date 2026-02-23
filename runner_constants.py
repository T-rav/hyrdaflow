"""Shared constants for runner prompt templates."""

from __future__ import annotations

# The memory suggestion block is included verbatim in all four runner prompts.
# Each runner calls `MEMORY_SUGGESTION_PROMPT.format(context=...)` with its
# own context value: "implementation", "planning", "review", or "correction".
MEMORY_SUGGESTION_PROMPT = """\
## Optional: Memory Suggestion

If you discover a reusable pattern or insight during this {context} that would help future agent runs, you may output ONE suggestion:

MEMORY_SUGGESTION_START
title: Short descriptive title
type: knowledge | config | instruction | code
learning: What was learned and why it matters
context: How it was discovered (reference issue/PR numbers)
MEMORY_SUGGESTION_END

Types: knowledge (passive insight), config (suggests config change), instruction (new agent instruction), code (suggests code change).
Actionable types (config, instruction, code) will be routed for human approval.
Only suggest genuinely valuable learnings — not trivial observations.
"""
