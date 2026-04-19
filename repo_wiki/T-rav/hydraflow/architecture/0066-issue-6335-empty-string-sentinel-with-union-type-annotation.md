---
id: 0066
topic: architecture
source_issue: 6335
source_phase: plan
created_at: 2026-04-10T05:43:58.108257+00:00
status: active
---

# Empty String Sentinel with Union Type Annotation

To allow a default empty string while maintaining type safety for valid values, use `FieldType | Literal[""]`. This pattern enables optional/unset states in strongly-typed fields without sacrificing validation of non-empty values.
