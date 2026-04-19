---
id: 0102
topic: architecture
source_issue: 6354
source_phase: plan
created_at: 2026-04-10T07:09:55.773138+00:00
status: active
---

# Use underscore prefix for local implementation details in functions

When defining intermediate variables in module-level functions (e.g., `_runner_kwargs`), use leading underscore to signal they are private implementation details, not public API. This convention improves readability and signals intent to future readers that the variable is not meant for external use.
