---
id: 0006
topic: patterns
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:38:18.766135+00:00
status: active
---

# Documentation and ADR consistency

Keep CLAUDE.md and README in sync—they may diverge on details (e.g., 'five concurrent async loops' vs actual implementation). ADR files must have corresponding README entries to be canonically referenceable—files without README entries become invisible. When renaming fixtures/command files, preserve namespace prefixes (hf. or hf-) for consistency. Skill prompts replicated across four backend locations (src/diff_sanity.py, .claude/commands/, .pi/skills/, .codex/skills/) must stay in sync; missed updates cause inconsistent LLM behavior.

See also: Backward compatibility and schema evolution — schema documentation; Refactoring and testing practices — documentation standards.
