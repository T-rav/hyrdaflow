---
id: 0097
topic: architecture
source_issue: 6350
source_phase: plan
created_at: 2026-04-10T06:55:39.084035+00:00
status: active
---

# Deferred imports preserve test mocking patterns

Import hindsight and recall_tracker inside method bodies (not module-level) to allow `patch("hindsight.recall_safe", ...)` to intercept calls correctly. When imports are at the top of the file, patches may not apply to the actual import binding used by the method. This pattern is critical for testing async helpers that depend on external services.
