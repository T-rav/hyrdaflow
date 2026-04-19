---
id: 0031
topic: architecture
source_issue: 6295
source_phase: review
created_at: 2026-04-10T03:47:50.097424+00:00
status: active
---

# Define explicit scope for extraction refactors

Extraction issues should explicitly name the target files/functions in scope. This prevents scope creep and clarifies what duplicates are intentionally excluded (e.g., similar patterns in other modules). Scope clarity prevents false-positive review flags.
