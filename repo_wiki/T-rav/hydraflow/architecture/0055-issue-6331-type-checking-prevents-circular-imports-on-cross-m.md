---
id: 0055
topic: architecture
source_issue: 6331
source_phase: plan
created_at: 2026-04-10T05:23:05.143432+00:00
status: active
---

# TYPE_CHECKING prevents circular imports on cross-module TypedDicts

When a TypedDict is shared between a loop module and service module (ADRReviewResult in adr_reviewer_loop.py used by adr_reviewer.py), import under TYPE_CHECKING guard to avoid circular imports while preserving type information for static analysis. Codebase already uses this pattern extensively.
