---
id: 0083
topic: architecture
source_issue: 6341
source_phase: plan
created_at: 2026-04-10T06:22:03.281145+00:00
status: active
---

# Export widely-reused constants without underscore prefix

Time duration constants imported across multiple modules (config.py, _common.py, tests/) should use public names without underscore prefix (ONE_DAY_SECS, not _ONE_DAY_SECS). Reserve underscore prefix for file-local-only constants to signal scope.
