---
id: 0015
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849574+00:00
status: active
---

# Consolidation Patterns for Duplicate Code

Three similar items (e.g., Handlers, Runners, Loops) warrant consolidation if the same pattern exists elsewhere (e.g., 8 runners total vs 3 currently refactored). Partial migrations create maintenance burden. Extract duplicated path patterns into module-level constants and shared helper functions. Consolidate label field lists via module-level constants (ALL_LIFECYCLE_LABEL_FIELDS) to allow cross-module imports without circular dependencies. When extracting methods from large classes, preserve original public API via thin delegation methods to avoid cascading changes across callers. Backward-compatible JSONL schema evolution: add optional fields with sensible defaults that existing consumers handle automatically. Example: fixing one missing label field requires fixing all missing label fields at once, not just the mentioned ones, to prevent latent bugs. See also: Backward Compatibility for preservation strategies, Dead Code Removal for cleanup verification.
