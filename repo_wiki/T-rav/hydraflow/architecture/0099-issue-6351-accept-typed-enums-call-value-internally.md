---
id: 0099
topic: architecture
source_issue: 6351
source_phase: plan
created_at: 2026-04-10T06:58:24.321769+00:00
status: active
---

# Accept typed enums, call .value internally

Helper methods should accept typed enums (ReviewerStatus, ReviewVerdict) at the signature level for caller type safety, then call `.value` internally when building string-keyed payloads. This pattern improves type checking at call sites without forcing callers to extract enum values manually.
