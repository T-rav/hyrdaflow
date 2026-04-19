---
id: 0074
topic: architecture
source_issue: 6336
source_phase: plan
created_at: 2026-04-10T05:57:03.732527+00:00
status: active
---

# Convert closure mutable state to class-based encapsulation

When extracting stateful closures (e.g., cache dicts, timestamp lists, file paths) into separate modules, convert them into a class that encapsulates mutable state and provides methods. This replaces closure-scoped variables with instance state and makes cache invalidation logic explicit and testable rather than implicit in helper functions.
