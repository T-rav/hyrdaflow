---
id: 0036
topic: architecture
source_issue: 6320
source_phase: plan
created_at: 2026-04-10T04:14:20.752849+00:00
status: active
---

# Use Literal types for bounded enum-like fields

Model fields with known bounded values should use Literal types rather than bare str. The codebase establishes this pattern (VisualEvidenceItem.status, Release.status). This provides compile-time validation and IDE autocomplete, catching invalid values at construction rather than runtime.
