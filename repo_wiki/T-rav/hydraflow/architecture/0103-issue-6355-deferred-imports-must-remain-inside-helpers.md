---
id: 0103
topic: architecture
source_issue: 6355
source_phase: plan
created_at: 2026-04-10T07:14:58.678248+00:00
status: active
---

# Deferred Imports Must Remain Inside Helpers

Optional module imports that live inside a method should stay inside extracted helpers, not moved to module level. This preserves graceful degradation when optional modules are missing. Moving deferred imports breaks the intent of the original error-isolation pattern.
