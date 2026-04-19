---
id: 0001
topic: patterns
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:38:18.766106+00:00
status: active
---

# Backward compatibility and schema evolution

Schema changes must preserve backward compatibility through optional fields with sensible defaults, type narrowing on bare strings (safe if values already conform), and StrEnum coercion for auto-conversion. Pydantic v2 auto-coerces raw dicts from state.json into typed models with no migration validators. Distinguish bare `str` fields (safe to narrow) from union types like `str | None` (require union narrowing) and verify all call sites before narrowing types via exhaustive grep-based audits. Establish single source of truth via canonical constants (e.g., `ALL_LIFECYCLE_LABEL_FIELDS`); functions derive from this single source rather than duplicating label lists. Use metadata tags instead of enum variants for categorizing items in shared banks (e.g., `{"source": "adr_council"}`)—avoids syncing enum changes across type checks, prompts, and display order. Make new fields optional with sensible defaults on read (e.g., `.get("scope", "repo")`); no migration needed. Reference canonical constants in reset code, never magic numbers. Preserve exact retry counter state and escalation conditions during schema evolution when refactoring state machine dispatchers.

See also: Refactoring and testing practices — call site verification; Concurrency and I/O safety — metadata tag usage and atomic write patterns; Memory management — metadata tag usage and schema versioning.
