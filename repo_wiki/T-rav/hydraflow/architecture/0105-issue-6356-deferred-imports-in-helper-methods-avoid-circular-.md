---
id: 0105
topic: architecture
source_issue: 6356
source_phase: plan
created_at: 2026-04-10T07:18:10.589088+00:00
status: active
---

# Deferred imports in helper methods avoid circular dependencies

When extracting helper methods that need imports like trace_rollup, tracing_context, or phase_utils, place deferred imports (with # noqa: PLC0415) at the start of each helper's method body rather than hoisting to module level. This prevents circular import chains while keeping dependencies explicit and scoped to the methods that use them.
