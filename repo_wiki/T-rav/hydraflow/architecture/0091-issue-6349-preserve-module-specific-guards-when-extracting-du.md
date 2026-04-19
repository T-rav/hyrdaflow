---
id: 0091
topic: architecture
source_issue: 6349
source_phase: plan
created_at: 2026-04-10T06:47:04.972401+00:00
status: active
---

# Preserve module-specific guards when extracting duplicated logic

When consolidating duplicated parsing patterns, keep module-specific behavior (e.g., empty-transcript guards) outside the shared helper. In plan_compliance.py, the early-return guard precedes the shared pattern and must not be folded into the helper function. Extract only the common logic, leaving module-specific pre- or post-conditions in place.
