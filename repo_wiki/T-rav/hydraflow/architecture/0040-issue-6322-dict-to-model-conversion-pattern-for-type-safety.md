---
id: 0040
topic: architecture
source_issue: 6322
source_phase: plan
created_at: 2026-04-10T04:31:05.960687+00:00
status: active
---

# Dict-to-Model Conversion Pattern for Type Safety

When callers use `.get()` on return values, convert the return type from `list[dict[str, Any]]` to a typed Pydantic model like `list[GitHubIssue]`. This eliminates fragile dict access and enables type checking. Update all callers together—avoid partial migrations where some code uses attributes and some uses `.get()`.
