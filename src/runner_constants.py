"""Shared constants for runner prompt templates."""

from __future__ import annotations

# The memory suggestion block is included verbatim in all runner and
# conflict-resolution prompts.  Each caller uses
# `MEMORY_SUGGESTION_PROMPT.format(context=...)` with its own context value:
# "implementation", "planning", "review", "correction", "conflict resolution",
# or "rebuild".
MEMORY_SUGGESTION_PROMPT = """\
## Optional: Tribal-Knowledge Suggestion

This {context} may have surfaced tribal knowledge — the kind of durable,
hard-won fact a senior engineer would write on a whiteboard for a new hire
on day one. If — and ONLY if — what you learned meets ALL of these criteria:

  1. Durable: still true a year from now, across releases and refactors.
  2. Non-obvious: a senior engineer would NOT figure it out by reading the code.
  3. Load-bearing: ignoring it causes a real failure or wastes real time.
  4. General: applies to a subsystem or pattern, not a single issue/PR.

…then emit a single block at the end of your response:

MEMORY_SUGGESTION_START
principle: <the durable rule, one sentence>
rationale: <why — historical incident, design constraint, or hard-won lesson>
failure_mode: <what concretely breaks if this is ignored>
scope: <subsystem path, file glob, or "all">
MEMORY_SUGGESTION_END

STRICT FORMATTING RULES:
- DO NOT include issue numbers, PR numbers, commit hashes, dates, or other
  short-lived references in any field. They will rot.
- DO NOT emit a block for routine observations, refactor notes, code-review
  nitpicks, or implementation details.
- DO NOT restate facts that are already obvious from CLAUDE.md or the code.
- All four fields are required and non-trivial. Blocks missing any field
  (or with empty/placeholder values) are silently dropped.

When in doubt, omit the block. The bar is "would I tell a new hire this on
day one." Most {context} runs should produce no block at all — that is the
expected and correct outcome.
"""
