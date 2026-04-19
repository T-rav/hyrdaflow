---
id: 0006
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849538+00:00
status: active
---

# Functional Design: Pure Functions and Module-Level Utilities

Extract pure functions (taking primitives, returning primitives or tuples) for reusable business logic that should be independently testable. Pattern: classify_merge_outcome(verdict_score, comment_count, ...) → (outcome, confidence). Pure functions isolate rules from service coupling, enable unit testing without mocks, and clarify logic intent. Pass config objects as parameters to access configuration-dependent values. When scoring classification logic is split across modules, consolidate by creating a pure function in the domain module with named threshold constants. Simple tuple returns (3 elements) are preferable to new dataclasses. Prefer module-level utility functions (e.g., retain_safe(client, bank, content, metadata=...)) over instance methods. This pattern is more testable, avoids tight coupling, and provides cleaner APIs. Module-level functions accept the object as first argument. When converting a closure to a standalone function, convert each `nonlocal` variable to either a function parameter (input) or a field in a returned NamedTuple (output). This eliminates implicit state sharing and makes the function's dependencies explicit—critical for testing and reasoning about behavior.
