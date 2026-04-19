---
id: 0100
topic: architecture
source_issue: 6352
source_phase: plan
created_at: 2026-04-10T07:02:55.409396+00:00
status: active
---

# Path prefix pattern for hierarchical object keys

When building dotted paths for nested objects, use `f"{path_prefix}.{key}" if path_prefix else key` to correctly handle both root-level (`key`) and nested (`parent.key`) cases. This avoids leading dots and false positives in path matching.
