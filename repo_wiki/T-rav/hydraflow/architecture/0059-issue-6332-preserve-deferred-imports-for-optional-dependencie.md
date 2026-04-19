---
id: 0059
topic: architecture
source_issue: 6332
source_phase: plan
created_at: 2026-04-10T05:33:08.098298+00:00
status: active
---

# Preserve deferred imports for optional dependencies

Use deferred imports (import inside method body, not module-level) for optional or infrequently-used dependencies like `prompt_dedup`. This avoids startup cost and avoids hard dependency failures in unrelated code paths. When refactoring such code, preserve the deferred import pattern.
